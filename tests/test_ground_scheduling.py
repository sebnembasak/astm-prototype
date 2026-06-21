import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import numpy as np
import pytest

from processing.ground_station import GroundStation, PassWindow, elevation_deg, find_pass_windows
from processing.schedule_conflict import detect_conflicts, conflict_ratio
from planner.ground_scheduler import schedule_passes


EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_window(sat_id, station_name, aos_offset_s, los_offset_s, max_elev=45.0, sat_name=None):
    return PassWindow(
        sat_id=sat_id,
        sat_name=sat_name or f"SAT-{sat_id}",
        station_name=station_name,
        aos=EPOCH + timedelta(seconds=aos_offset_s),
        los=EPOCH + timedelta(seconds=los_offset_s),
        max_elevation_deg=max_elev,
    )


class TestElevationDeg:
    """
    elevation_deg, coord_utils.teme_pos_to_latlon ile aynı astropy TEME->ITRS
    zincirini kullanır; burada gerçek SGP4 yerine bilinen geometrik
    noktalarla (round-trip ITRS->TEME) doğrulanır.
    """

    def test_point_directly_overhead_has_high_elevation(self):
        from astropy.time import Time
        from astropy import units as u
        from astropy.coordinates import CartesianRepresentation, ITRS, TEME, EarthLocation

        t = Time(EPOCH.strftime('%Y-%m-%dT%H:%M:%S.%f'), format="isot", scale="utc")
        station = GroundStation(name="Equator", lat_deg=0.0, lon_deg=0.0)
        loc = EarthLocation(lat=0.0 * u.deg, lon=0.0 * u.deg, height=0.0 * u.km)

        # İstasyonun tam üstünde, 500km irtifada bir nokta (ITRS) -> TEME'e çevir
        zenith_ecef = loc.itrs.cartesian.xyz.to(u.m).value
        zenith_ecef = zenith_ecef + zenith_ecef / np.linalg.norm(zenith_ecef) * 500_000.0
        itrs_point = ITRS(CartesianRepresentation(zenith_ecef * u.m), obstime=t)
        teme_point = itrs_point.transform_to(TEME(obstime=t))
        r_km = teme_point.cartesian.xyz.to(u.km).value

        elev = elevation_deg(r_km, EPOCH, station)
        assert elev == pytest.approx(90.0, abs=1.0)

    def test_point_on_opposite_side_of_earth_is_below_horizon(self):
        from astropy.time import Time
        from astropy import units as u
        from astropy.coordinates import CartesianRepresentation, ITRS, TEME, EarthLocation

        t = Time(EPOCH.strftime('%Y-%m-%dT%H:%M:%S.%f'), format="isot", scale="utc")
        station = GroundStation(name="Equator", lat_deg=0.0, lon_deg=0.0)
        loc = EarthLocation(lat=0.0 * u.deg, lon=0.0 * u.deg, height=0.0 * u.km)

        # Dünyanın tam karşı tarafında (antipod) 500km irtifada bir nokta
        antipode_loc = EarthLocation(lat=0.0 * u.deg, lon=180.0 * u.deg, height=0.0 * u.km)
        antipode_ecef = antipode_loc.itrs.cartesian.xyz.to(u.m).value
        antipode_ecef = antipode_ecef + antipode_ecef / np.linalg.norm(antipode_ecef) * 500_000.0
        itrs_point = ITRS(CartesianRepresentation(antipode_ecef * u.m), obstime=t)
        teme_point = itrs_point.transform_to(TEME(obstime=t))
        r_km = teme_point.cartesian.xyz.to(u.km).value

        elev = elevation_deg(r_km, EPOCH, station)
        assert elev < 0.0


class TestFindPassWindows:
    """
    Gerçek SGP4/astropy yerine, propagate_func ve elevation_func dependency
    injection ile tamamen deterministik bir elevasyon profili enjekte edilip
    AOS/LOS tespit + lineer interpolasyon mantığı sınanır (conjunction.py'deki
    propagate_func injection testleriyle aynı yaklaşım).
    """

    STEP_SECONDS = 60
    # t=0,60,...,600s için trapezoid elevasyon profili (eşik=10 derece)
    ELEVATIONS = [-20, -20, -5, 10, 25, 25, 10, -5, -20, -20, -20]

    def make_fake_funcs(self):
        def fake_propagate(satrec, t):
            return np.zeros(3), np.zeros(3)

        def fake_elevation(r, t, station):
            idx = round((t - EPOCH).total_seconds() / self.STEP_SECONDS)
            return float(self.ELEVATIONS[idx])

        return fake_propagate, fake_elevation

    def test_detects_single_trapezoid_pass(self):
        fake_propagate, fake_elevation = self.make_fake_funcs()
        station = GroundStation(name="TestStation", lat_deg=0.0, lon_deg=0.0, min_elevation_deg=10.0)

        windows = find_pass_windows(
            sat_id=1, sat_name="SAT-1", satrec=None, station=station,
            start_utc=EPOCH, end_utc=EPOCH + timedelta(seconds=600),
            propagate_func=fake_propagate, step_seconds=self.STEP_SECONDS,
            elevation_func=fake_elevation,
        )

        assert len(windows) == 1
        w = windows[0]
        assert (w.aos - EPOCH).total_seconds() == pytest.approx(180.0)
        assert (w.los - EPOCH).total_seconds() == pytest.approx(360.0)
        assert w.duration_s == pytest.approx(180.0)
        assert w.max_elevation_deg == pytest.approx(25.0)

    def test_no_pass_when_elevation_never_crosses_threshold(self):
        def fake_propagate(satrec, t):
            return np.zeros(3), np.zeros(3)

        def fake_elevation_always_low(r, t, station):
            return -5.0

        station = GroundStation(name="TestStation", lat_deg=0.0, lon_deg=0.0, min_elevation_deg=10.0)
        windows = find_pass_windows(
            sat_id=1, sat_name="SAT-1", satrec=None, station=station,
            start_utc=EPOCH, end_utc=EPOCH + timedelta(seconds=600),
            propagate_func=fake_propagate, step_seconds=60,
            elevation_func=fake_elevation_always_low,
        )
        assert windows == []

    def test_incomplete_trailing_pass_is_dropped(self):
        # Tarama penceresi bitene kadar LOS'a ulaşmayan bir geçiş sonuçlara dahil edilmemeli
        def fake_propagate(satrec, t):
            return np.zeros(3), np.zeros(3)

        def fake_elevation_rising(r, t, station):
            sec = (t - EPOCH).total_seconds()
            return -50.0 + sec  # sürekli yükseliyor, hiç düşmüyor

        station = GroundStation(name="TestStation", lat_deg=0.0, lon_deg=0.0, min_elevation_deg=10.0)
        windows = find_pass_windows(
            sat_id=1, sat_name="SAT-1", satrec=None, station=station,
            start_utc=EPOCH, end_utc=EPOCH + timedelta(seconds=120),
            propagate_func=fake_propagate, step_seconds=60,
            elevation_func=fake_elevation_rising,
        )
        assert windows == []


class TestDetectConflicts:
    def test_overlapping_windows_at_same_station_are_conflicts(self):
        w1 = make_window(sat_id=1, station_name="A", aos_offset_s=0, los_offset_s=100)
        w2 = make_window(sat_id=2, station_name="A", aos_offset_s=50, los_offset_s=150)
        w3 = make_window(sat_id=3, station_name="A", aos_offset_s=200, los_offset_s=300)
        w4 = make_window(sat_id=4, station_name="B", aos_offset_s=0, los_offset_s=50)

        conflicts = detect_conflicts([w1, w2, w3, w4])

        assert len(conflicts) == 1
        assert conflicts[0].station_name == "A"
        assert conflicts[0].overlap_s == pytest.approx(50.0)

    def test_different_stations_never_conflict(self):
        w1 = make_window(sat_id=1, station_name="A", aos_offset_s=0, los_offset_s=100)
        w2 = make_window(sat_id=2, station_name="B", aos_offset_s=0, los_offset_s=100)
        assert detect_conflicts([w1, w2]) == []

    def test_conflict_ratio_counts_distinct_conflicting_windows(self):
        w1 = make_window(sat_id=1, station_name="A", aos_offset_s=0, los_offset_s=100)
        w2 = make_window(sat_id=2, station_name="A", aos_offset_s=50, los_offset_s=150)
        w3 = make_window(sat_id=3, station_name="A", aos_offset_s=200, los_offset_s=300)
        w4 = make_window(sat_id=4, station_name="B", aos_offset_s=0, los_offset_s=50)

        ratio = conflict_ratio([w1, w2, w3, w4])
        assert ratio == pytest.approx(2 / 4)

    def test_empty_input_returns_zero_ratio(self):
        assert conflict_ratio([]) == 0.0


class TestSchedulePasses:
    def test_non_overlapping_passes_all_assigned(self):
        windows = [
            make_window(sat_id=1, station_name="A", aos_offset_s=0, los_offset_s=100),
            make_window(sat_id=2, station_name="A", aos_offset_s=200, los_offset_s=300),
        ]
        result = schedule_passes(windows)

        assert result.total_passes == 2
        assert result.missed_passes == 0
        assert result.capacity_loss_ratio == 0.0
        assert result.station_utilization["A"] == 2

    def test_overlapping_passes_at_same_station_one_is_missed(self):
        # w1 (0-100) ve w2 (50-150) çakışıyor; EFT-greedy LOS'a göre sıralar,
        # w1 önce biter, w1 atanır, w2 (aos=50 < w1.los=100) kaçırılır.
        w1 = make_window(sat_id=1, station_name="A", aos_offset_s=0, los_offset_s=100)
        w2 = make_window(sat_id=2, station_name="A", aos_offset_s=50, los_offset_s=150)
        result = schedule_passes([w1, w2])

        assert result.total_passes == 2
        assert result.missed_passes == 1
        assert result.capacity_loss_ratio == pytest.approx(0.5)

        assigned = [a for a in result.assignments if a.assigned]
        missed = [a for a in result.assignments if not a.assigned]
        assert len(assigned) == 1 and assigned[0].sat_id == 1
        assert len(missed) == 1 and missed[0].sat_id == 2

    def test_a_window_is_never_assigned_to_a_different_station(self):
        # Bir pencere yalnızca kendi station_name'ine atanabilir; başka bir
        # istasyonun kuyruğu boş olsa bile o pencereye "ödünç verilmez".
        w1 = make_window(sat_id=1, station_name="A", aos_offset_s=0, los_offset_s=100)
        w2 = make_window(sat_id=2, station_name="A", aos_offset_s=50, los_offset_s=150)
        # B istasyonu tamamen boş, ama w2 B'nin geometrisine ait değil -> kaçırılmalı
        result = schedule_passes([w1, w2])

        missed = [a for a in result.assignments if not a.assigned]
        assert len(missed) == 1
        assert missed[0].sat_id == 2
        assert "B" not in result.station_utilization

    def test_independent_stations_do_not_affect_each_others_capacity(self):
        w1 = make_window(sat_id=1, station_name="A", aos_offset_s=0, los_offset_s=100)
        w2 = make_window(sat_id=2, station_name="A", aos_offset_s=50, los_offset_s=150)
        w3 = make_window(sat_id=3, station_name="B", aos_offset_s=0, los_offset_s=100)

        result = schedule_passes([w1, w2, w3])

        assert result.missed_passes == 1  # sadece A'daki çakışma kaybedilir
        assert result.station_utilization["A"] == 1
        assert result.station_utilization["B"] == 1

    def test_empty_input(self):
        result = schedule_passes([])
        assert result.total_passes == 0
        assert result.capacity_loss_ratio == 0.0
