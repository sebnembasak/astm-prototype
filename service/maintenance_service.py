import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

from backend.models.db import get_conn
from ground_scheduling_config import CANDIDATE_GROUND_STATIONS, DEFAULT_MIN_ELEVATION_DEG, DEFAULT_STATION_ALT_KM
from processing.ground_station import GroundStation, PassWindow, compute_all_pass_windows
from processing.propagate_wrapper import propagate_satrec_single
from processing.propagator import tle_to_satrec
from service.tle_service import tle_service


ANALYSIS_DAYS = 7
CANDIDATE_STEP_MINUTES = 30
DEFAULT_SATELLITE_LIMIT = 30
TOP_N = 3

# Weight thresholds from requirements
_WEIGHT_HIGH = 3.0    # lifetime < 180 days
_WEIGHT_MED  = 2.0    # lifetime 180–365 days
_WEIGHT_LOW  = 1.0    # lifetime > 365 days or unknown

# ─── Atmospheric Model ───────────────────────────────────────────────────────
# Piecewise-exponential fit to 1976 US Standard Atmosphere (150–1000 km).
# Each row: (base_alt_km, density_at_base_kg_m3, scale_height_km)
# Source: Vallado, "Fundamentals of Astrodynamics", Table 8-4.
_ATM_LAYERS: List[Tuple[float, float, float]] = [
    (150,  2.07e-9,  22.5),
    (200,  2.79e-10, 29.7),
    (250,  5.46e-11, 36.7),
    (300,  1.92e-11, 42.7),
    (350,  8.65e-12, 47.7),
    (400,  4.17e-12, 52.1),
    (450,  2.05e-12, 54.1),
    (500,  1.00e-12, 55.8),
    (600,  2.54e-13, 60.7),
    (700,  7.21e-14, 65.2),
    (800,  2.25e-14, 72.1),
    (900,  8.22e-15, 80.0),
    (1000, 3.56e-15, 90.0),
]

# Calibration anchor: B* = 1e-4 /Re at 400 km → ~365 days lifetime.
# Derived from historical CubeSat reentry data in mid-solar-activity conditions
# (e.g., NOAA-reported Fsat catalogue decay statistics 2015–2020).
# Scaling: T_life ∝ 1 / (B* × ρ(h)), so for any (B*, h):
#   T_life = T_CAL × (ρ_CAL / ρ(h)) × (B*_CAL / B*)
_T_CAL_DAYS    = 365.0
_BSTAR_CAL     = 1.0e-4   # 1/Re
_RHO_CAL_KG_M3 = 4.17e-12 # ρ(400 km)

_EARTH_RADIUS_KM = 6378.137
_GM_KM3_S2       = 398600.4418


def _atm_density_kg_m3(h_km: float) -> float:
    """Exponential atmosphere density at altitude h_km [kg/m³]."""
    layer = _ATM_LAYERS[0]
    for entry in _ATM_LAYERS:
        if entry[0] <= h_km:
            layer = entry
        else:
            break
    h_base, rho_base, H = layer
    return rho_base * math.exp(-(h_km - h_base) / H)


def _orbital_altitude_km(satrec) -> float:
    """
    Derive mean orbital altitude from TLE mean motion.
    satrec.no_kozai is in rad/min (sgp4 ≥ 2.20).
    a = (GM / n²)^(1/3), h = a − Re.
    """
    n_rad_s = satrec.no_kozai / 60.0          # rad/min → rad/s
    a_km = (_GM_KM3_S2 / n_rad_s ** 2) ** (1.0 / 3.0)
    return a_km - _EARTH_RADIUS_KM


def _estimate_lifetime_days(bstar_1_per_re: float, altitude_km: float) -> float:
    """
    Calibrated scaling estimate of remaining orbital lifetime.

    Physics basis: for a circular orbit in an exponential atmosphere the
    altitude decay rate is dh/dt ∝ B* × ρ(h), so lifetime scales as
    1 / (B* × ρ(h)). The calibration anchor fixes the proportionality
    constant without requiring knowledge of SGP4's internal ρ₀ normalisation.

    Returns inf for zero/negative B* (no measurable drag) or h > 1200 km
    (Vallado scale height table boundary; solar radiation pressure dominates
    above ~800 km anyway).
    """
    if bstar_1_per_re <= 0 or altitude_km > 1200 or altitude_km < 0:
        return math.inf

    rho_h = _atm_density_kg_m3(altitude_km)
    if rho_h <= 0:
        return math.inf

    return _T_CAL_DAYS * (_RHO_CAL_KG_M3 / rho_h) * (_BSTAR_CAL / bstar_1_per_re)


def _bstar_regression(norad_id: int, now_utc: datetime) -> Tuple[Optional[float], int, str]:
    """
    Queries tle_history for `norad_id`, parses B* from each snapshot, fits a
    linear trend (B* vs time), and projects to now_utc.

    Returns (projected_bstar, n_valid_points, source) where source is
    "regression" when ≥3 valid points were found, "snapshot" otherwise.

    Physics rationale: B* absorbs atmospheric drag plus solar-flux variation.
    A rising B* trend signals faster-than-current-snapshot decay; projecting
    to now gives a more conservative (shorter) lifetime than the latest TLE alone.

    Cap: projected B* is clipped to [1e-7, 2 × historical_mean] to prevent
    extrapolation noise from producing implausible values.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT line1, line2, epoch FROM tle_history WHERE norad_id = ? ORDER BY epoch",
        (norad_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    if not rows:
        return None, 0, "snapshot"

    try:
        ref_epoch = datetime.fromisoformat(rows[0]["epoch"])
    except ValueError:
        ref_epoch = datetime.strptime(rows[0]["epoch"][:19], "%Y-%m-%dT%H:%M:%S")

    xs: List[float] = []
    ys: List[float] = []
    for row in rows:
        try:
            st = tle_to_satrec(row["line1"], row["line2"])
            bstar = float(st.bstar)
            if bstar <= 0:
                continue
            try:
                epoch_t = datetime.fromisoformat(row["epoch"])
            except ValueError:
                epoch_t = datetime.strptime(row["epoch"][:19], "%Y-%m-%dT%H:%M:%S")
            xs.append((epoch_t - ref_epoch).total_seconds() / 86400.0)
            ys.append(bstar)
        except Exception:
            continue

    if len(xs) < 3:
        return None, len(xs), "snapshot"

    xs_arr = np.array(xs, dtype=float)
    ys_arr = np.array(ys, dtype=float)
    coeffs = np.polyfit(xs_arr, ys_arr, 1)

    days_to_now = (now_utc - ref_epoch).total_seconds() / 86400.0
    projected = float(np.polyval(coeffs, days_to_now))

    hist_mean = float(np.mean(ys_arr))
    projected = max(1e-7, min(projected, 2.0 * hist_mean))

    return projected, len(xs), "regression"


def _weight_from_lifetime(lifetime_days: float) -> float:
    if lifetime_days < 180:
        return _WEIGHT_HIGH
    if lifetime_days < 365:
        return _WEIGHT_MED
    return _WEIGHT_LOW


# ─── Data classes ────────────────────────────────────────────────────────────

@dataclass
class SatelliteWeightDetail:
    norad_id: int
    sat_name: str
    altitude_km: float
    bstar: float
    estimated_lifetime_days: Optional[float]  # None = inf (no measurable drag)
    weight: float
    bstar_history_points: int = 0
    bstar_source: str = "snapshot"  # "regression" | "snapshot"


@dataclass
class PassLostDetail:
    sat_norad_id: int
    sat_name: str
    aos: datetime
    los: datetime
    duration_s: float
    max_elevation_deg: float
    satellite_weight: float


@dataclass
class WindowRecommendation:
    rank: int
    start_utc: datetime
    end_utc: datetime
    cost_score: float
    passes_lost: int
    contact_minutes_lost: float
    passes_lost_detail: List[PassLostDetail]


@dataclass
class MaintenanceAnalysisResult:
    station_name: str
    station_lat: float
    station_lon: float
    duration_hours: float
    analysis_start_utc: datetime
    analysis_end_utc: datetime
    total_satellites_analyzed: int
    total_passes_in_period: int
    total_contact_minutes: float
    candidate_windows_evaluated: int
    satellite_weight_details: List[SatelliteWeightDetail]
    best_windows: List[WindowRecommendation]
    worst_windows: List[WindowRecommendation]
    computation_time_s: float


# ─── Service ─────────────────────────────────────────────────────────────────

class MaintenanceService:

    def _resolve_station(self, name: str) -> Optional[GroundStation]:
        """DB → config cascade. Returns None if name not found anywhere."""
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT name, lat, lon, alt_km, min_elevation_deg "
            "FROM ground_stations WHERE LOWER(name) = LOWER(?)",
            (name,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return GroundStation(
                name=row["name"], lat_deg=row["lat"], lon_deg=row["lon"],
                alt_km=row["alt_km"], min_elevation_deg=row["min_elevation_deg"],
            )
        for cfg in CANDIDATE_GROUND_STATIONS:
            if cfg["name"].lower() == name.lower():
                return GroundStation(
                    name=cfg["name"], lat_deg=cfg["lat_deg"], lon_deg=cfg["lon_deg"],
                    alt_km=DEFAULT_STATION_ALT_KM, min_elevation_deg=DEFAULT_MIN_ELEVATION_DEG,
                )
        return None

    def _load_satellites(
        self, priority_norad_ids: List[int], limit: int = DEFAULT_SATELLITE_LIMIT
    ) -> List[Tuple[int, str, object]]:
        """Priority NORAD IDs are force-included; remainder from orbit-profile pool."""
        conn = get_conn()
        cur = conn.cursor()
        priority_rows = []
        if priority_norad_ids:
            ph = ",".join("?" * len(priority_norad_ids))
            cur.execute(
                f"SELECT id, norad_id, sat_name, line1, line2 FROM raw_tles WHERE norad_id IN ({ph})",
                priority_norad_ids,
            )
            priority_rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        priority_db_ids = {r["id"] for r in priority_rows}
        remaining = limit - len(priority_rows)
        general_rows: List[dict] = []
        if remaining > 0:
            for row in tle_service.get_satellites_by_orbit_profile(limit=limit):
                if row["id"] not in priority_db_ids:
                    general_rows.append(row)
                    if len(general_rows) >= remaining:
                        break

        satellites: List[Tuple[int, str, object]] = []
        for row in priority_rows + general_rows:
            try:
                satrec = tle_to_satrec(row["line1"], row["line2"])
                norad_id = row.get("norad_id") or int(row["line1"][2:7])
                satellites.append((norad_id, row["sat_name"], satrec))
            except Exception:
                continue
        return satellites

    def _build_weights(
        self, satellites: List[Tuple[int, str, object]], now_utc: datetime
    ) -> Tuple[Dict[int, float], List[SatelliteWeightDetail]]:
        """
        Phase 2: derive per-satellite weight from B* drag term and altitude.

        B* (satrec.bstar, units: 1/Re) combined with atmospheric density at
        current altitude gives an order-of-magnitude orbital lifetime estimate.
        Satellites with shorter predicted lifetimes receive higher weights —
        their contact windows are harder to recover if missed.

        Weight ladder:
          < 180 days → 3.0  (approaching reentry, every pass matters)
          180–365 days → 2.0  (within-year decay risk)
          > 365 days → 1.0  (operationally stable; safe default for B*=0)
        """
        weights: Dict[int, float] = {}
        details: List[SatelliteWeightDetail] = []

        for norad_id, name, satrec in satellites:
            try:
                snapshot_bstar = float(satrec.bstar)
                alt_km = _orbital_altitude_km(satrec)
                reg_bstar, hist_pts, bstar_source = _bstar_regression(norad_id, now_utc)
                effective_bstar = reg_bstar if reg_bstar is not None else snapshot_bstar
                lifetime = _estimate_lifetime_days(effective_bstar, alt_km)
                weight = _weight_from_lifetime(lifetime)
                lifetime_out = None if math.isinf(lifetime) else round(lifetime, 0)
            except Exception:
                effective_bstar, alt_km, lifetime_out, weight = 0.0, 0.0, None, _WEIGHT_LOW
                hist_pts, bstar_source = 0, "snapshot"

            weights[norad_id] = weight
            details.append(SatelliteWeightDetail(
                norad_id=norad_id,
                sat_name=name,
                altitude_km=round(alt_km, 1),
                bstar=effective_bstar,
                estimated_lifetime_days=lifetime_out,
                weight=weight,
                bstar_history_points=hist_pts,
                bstar_source=bstar_source,
            ))

        return weights, details

    def _score_window(
        self,
        win_start: datetime,
        win_end: datetime,
        all_passes: List[PassWindow],
        weights: Dict[int, float],
    ) -> Tuple[float, List[PassLostDetail]]:
        """
        Cost = Σ (pass.duration_s × weight) for all passes overlapping window.
        Overlap: pass.aos < win_end AND pass.los > win_start.
        """
        lost: List[PassLostDetail] = []
        cost = 0.0
        for pw in all_passes:
            if pw.aos < win_end and pw.los > win_start:
                w = weights.get(pw.sat_id, _WEIGHT_LOW)
                cost += pw.duration_s * w
                lost.append(PassLostDetail(
                    sat_norad_id=pw.sat_id, sat_name=pw.sat_name,
                    aos=pw.aos, los=pw.los, duration_s=pw.duration_s,
                    max_elevation_deg=pw.max_elevation_deg, satellite_weight=w,
                ))
        return cost, lost

    def analyze(
        self,
        station_name: str,
        duration_hours: float,
        priority_norad_ids: Optional[List[int]] = None,
        satellite_limit: int = DEFAULT_SATELLITE_LIMIT,
    ) -> MaintenanceAnalysisResult:
        t0 = time.monotonic()

        station = self._resolve_station(station_name)
        if station is None:
            raise ValueError(f"Station '{station_name}' not found in DB or candidate config.")

        satellites = self._load_satellites(priority_norad_ids or [], limit=satellite_limit)
        if not satellites:
            raise RuntimeError("No satellites in database. Run TLE fetch first.")

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        analysis_end = now_utc + timedelta(days=ANALYSIS_DAYS)

        weights, weight_details = self._build_weights(satellites, now_utc)

        all_passes = compute_all_pass_windows(
            satellites=satellites,
            stations=[station],
            start_utc=now_utc,
            end_utc=analysis_end,
            propagate_func=propagate_satrec_single,
            step_seconds=60,
        )

        total_contact_minutes = sum(pw.duration_s for pw in all_passes) / 60.0

        step = timedelta(minutes=CANDIDATE_STEP_MINUTES)
        duration = timedelta(hours=duration_hours)
        candidates: List[datetime] = []
        t = now_utc
        while t + duration <= analysis_end:
            candidates.append(t)
            t += step

        scored: List[Tuple[float, datetime, List[PassLostDetail]]] = []
        for win_start in candidates:
            cost, lost = self._score_window(win_start, win_start + duration, all_passes, weights)
            scored.append((cost, win_start, lost))

        scored.sort(key=lambda x: x[0])

        def _rec(rank, cost, start, lost) -> WindowRecommendation:
            return WindowRecommendation(
                rank=rank, start_utc=start, end_utc=start + duration,
                cost_score=round(cost, 1), passes_lost=len(lost),
                contact_minutes_lost=round(sum(p.duration_s for p in lost) / 60.0, 1),
                passes_lost_detail=sorted(lost, key=lambda p: p.aos),
            )

        best  = [_rec(i + 1, *item) for i, item in enumerate(scored[:TOP_N])]
        worst = [_rec(i + 1, *item) for i, item in enumerate(scored[-TOP_N:][::-1])]

        return MaintenanceAnalysisResult(
            station_name=station.name,
            station_lat=station.lat_deg,
            station_lon=station.lon_deg,
            duration_hours=duration_hours,
            analysis_start_utc=now_utc,
            analysis_end_utc=analysis_end,
            total_satellites_analyzed=len(satellites),
            total_passes_in_period=len(all_passes),
            total_contact_minutes=round(total_contact_minutes, 1),
            candidate_windows_evaluated=len(candidates),
            satellite_weight_details=weight_details,
            best_windows=best,
            worst_windows=worst,
            computation_time_s=round(time.monotonic() - t0, 1),
        )


maintenance_service = MaintenanceService()
