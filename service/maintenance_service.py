from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
import time

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


@dataclass
class PassLostDetail:
    sat_norad_id: int
    sat_name: str
    aos: datetime
    los: datetime
    duration_s: float
    max_elevation_deg: float
    satellite_weight: float  # Phase 2: replaced by B*-derived value


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
    best_windows: List[WindowRecommendation]   # lowest cost → schedule here
    worst_windows: List[WindowRecommendation]  # highest cost → avoid these
    computation_time_s: float


class MaintenanceService:

    def _resolve_station(self, name: str) -> Optional[GroundStation]:
        """DB → config cascade. Returns None if name not found anywhere."""
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT name, lat, lon, alt_km, min_elevation_deg FROM ground_stations WHERE LOWER(name) = LOWER(?)",
            (name,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return GroundStation(
                name=row["name"],
                lat_deg=row["lat"],
                lon_deg=row["lon"],
                alt_km=row["alt_km"],
                min_elevation_deg=row["min_elevation_deg"],
            )

        for cfg in CANDIDATE_GROUND_STATIONS:
            if cfg["name"].lower() == name.lower():
                return GroundStation(
                    name=cfg["name"],
                    lat_deg=cfg["lat_deg"],
                    lon_deg=cfg["lon_deg"],
                    alt_km=DEFAULT_STATION_ALT_KM,
                    min_elevation_deg=DEFAULT_MIN_ELEVATION_DEG,
                )
        return None

    def _load_satellites(
        self, priority_norad_ids: List[int], limit: int = DEFAULT_SATELLITE_LIMIT
    ) -> Tuple[List[Tuple[int, str, object]], Dict[int, float]]:
        """
        Returns (satellites, weights).
        Priority IDs are guaranteed included; remainder filled from tle_service.
        weights dict maps norad_id → float (all 1.0 in Phase 1).
        Phase 2: replace _build_weights() to inject B*-derived values.
        """
        conn = get_conn()
        cur = conn.cursor()

        # Force-load priority satellites first (by NORAD ID, not DB PK)
        priority_rows = []
        if priority_norad_ids:
            placeholders = ",".join("?" * len(priority_norad_ids))
            cur.execute(
                f"SELECT id, norad_id, sat_name, line1, line2 FROM raw_tles WHERE norad_id IN ({placeholders})",
                priority_norad_ids,
            )
            priority_rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        priority_db_ids = {r["id"] for r in priority_rows}

        # Fill remainder from general pool (orbit-profile filtered, best-match first)
        remaining = limit - len(priority_rows)
        general_rows = []
        if remaining > 0:
            pool = tle_service.get_satellites_by_orbit_profile(limit=limit)
            for row in pool:
                if row["id"] not in priority_db_ids:
                    general_rows.append(row)
                    if len(general_rows) >= remaining:
                        break

        all_rows = priority_rows + general_rows

        satellites: List[Tuple[int, str, object]] = []
        for row in all_rows:
            try:
                satrec = tle_to_satrec(row["line1"], row["line2"])
                norad_id = row.get("norad_id") or int(row["line1"][2:7])
                satellites.append((norad_id, row["sat_name"], satrec))
            except Exception:
                continue

        weights = self._build_weights(satellites)
        return satellites, weights

    def _build_weights(self, satellites: List[Tuple[int, str, object]]) -> Dict[int, float]:
        """Phase 1: uniform weights. Phase 2: derive from B* orbital decay term."""
        return {norad_id: 1.0 for norad_id, _, _ in satellites}

    def _score_window(
        self,
        win_start: datetime,
        win_end: datetime,
        all_passes: List[PassWindow],
        weights: Dict[int, float],
    ) -> Tuple[float, List[PassLostDetail]]:
        """
        A pass is lost if it overlaps the maintenance window at all.
        Overlap condition: pass.aos < win_end AND pass.los > win_start
        Cost = Σ (pass.duration_s × weight)
        """
        lost: List[PassLostDetail] = []
        cost = 0.0
        for pw in all_passes:
            if pw.aos < win_end and pw.los > win_start:
                norad_id = pw.sat_id
                w = weights.get(norad_id, 1.0)
                cost += pw.duration_s * w
                lost.append(PassLostDetail(
                    sat_norad_id=norad_id,
                    sat_name=pw.sat_name,
                    aos=pw.aos,
                    los=pw.los,
                    duration_s=pw.duration_s,
                    max_elevation_deg=pw.max_elevation_deg,
                    satellite_weight=w,
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

        satellites, weights = self._load_satellites(priority_norad_ids or [], limit=satellite_limit)
        if not satellites:
            raise RuntimeError("No satellites in database. Run TLE fetch first.")

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        analysis_end = now_utc + timedelta(days=ANALYSIS_DAYS)

        all_passes = compute_all_pass_windows(
            satellites=satellites,
            stations=[station],
            start_utc=now_utc,
            end_utc=analysis_end,
            propagate_func=propagate_satrec_single,
            step_seconds=60,
        )

        total_contact_minutes = sum(pw.duration_s for pw in all_passes) / 60.0

        # Generate candidate maintenance windows (30-min step grid)
        step = timedelta(minutes=CANDIDATE_STEP_MINUTES)
        duration = timedelta(hours=duration_hours)
        # Stop generating if window would extend past analysis_end
        candidates: List[datetime] = []
        t = now_utc
        while t + duration <= analysis_end:
            candidates.append(t)
            t += step

        # Score every candidate
        scored: List[Tuple[float, datetime, List[PassLostDetail]]] = []
        for win_start in candidates:
            win_end = win_start + duration
            cost, lost = self._score_window(win_start, win_end, all_passes, weights)
            scored.append((cost, win_start, lost))

        scored.sort(key=lambda x: x[0])

        def _make_recommendation(rank: int, cost: float, start: datetime, lost: List[PassLostDetail]) -> WindowRecommendation:
            return WindowRecommendation(
                rank=rank,
                start_utc=start,
                end_utc=start + duration,
                cost_score=round(cost, 1),
                passes_lost=len(lost),
                contact_minutes_lost=round(sum(p.duration_s for p in lost) / 60.0, 1),
                passes_lost_detail=sorted(lost, key=lambda p: p.aos),
            )

        best = [_make_recommendation(i + 1, *item) for i, item in enumerate(scored[:TOP_N])]
        worst_raw = scored[-TOP_N:][::-1]  # highest cost first
        worst = [_make_recommendation(i + 1, *item) for i, item in enumerate(worst_raw)]

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
            best_windows=best,
            worst_windows=worst,
            computation_time_s=round(time.monotonic() - t0, 1),
        )


maintenance_service = MaintenanceService()
