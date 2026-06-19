import sys
import os
from datetime import datetime, timezone

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import numpy as np
import pytest

from processing.conjunction import (
    analytic_tca_and_miss,
    refine_tca_with_propagator,
    compute_conjunction_for_pair,
)


EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_linear_propagator():
    """
    Gerçek SGP4 yerine kullanılan, sabit hızla düz çizgi hareket eden
    deterministik bir test propagator'ı. satrec burada basit bir dict:
    {'r0': np.array, 'v0': np.array, 't0': datetime}.
    """
    def propagate(satrec, t):
        dt = (t - satrec['t0']).total_seconds()
        r = satrec['r0'] + satrec['v0'] * dt
        v = satrec['v0']
        return r, v
    return propagate


def make_satrec(r0, v0, t0=EPOCH, satnum=0):
    return {'r0': np.array(r0, dtype=float), 'v0': np.array(v0, dtype=float), 't0': t0, 'satnum': satnum}


def raising_propagator(*_args, **_kwargs):
    raise RuntimeError("propagate_func çağrılmamalıydı")


class TestAnalyticTcaAndMiss:
    def test_head_on_collision_course(self):
        # Sat1 sabit orijinde, Sat2 100 km uzakta -10 km/s ile yaklaşıyor -> 10s sonra çarpışma
        r1, v1 = np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 0.0])
        r2, v2 = np.array([100.0, 0.0, 0.0]), np.array([-10.0, 0.0, 0.0])
        tstar, miss = analytic_tca_and_miss(r1, v1, r2, v2, EPOCH)
        assert tstar == pytest.approx(10.0)
        assert miss == pytest.approx(0.0, abs=1e-9)

    def test_zero_relative_velocity_returns_current_distance(self):
        # Aynı hızla giden iki uydu: bağıl hız sıfır, mesafe asla değişmez
        r1, v1 = np.array([0.0, 0.0, 0.0]), np.array([5.0, 0.0, 0.0])
        r2, v2 = np.array([50.0, 0.0, 0.0]), np.array([5.0, 0.0, 0.0])
        tstar, miss = analytic_tca_and_miss(r1, v1, r2, v2, EPOCH)
        assert tstar == 0.0
        assert miss == pytest.approx(50.0)

    def test_moving_apart_closest_approach_in_past(self):
        # Sat2, Sat1'den uzaklaşıyor; en yakın geçiş 1 saniye önceydi (negatif t*)
        r1, v1 = np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 0.0])
        r2, v2 = np.array([10.0, 0.0, 0.0]), np.array([10.0, 0.0, 0.0])
        tstar, miss = analytic_tca_and_miss(r1, v1, r2, v2, EPOCH)
        assert tstar == pytest.approx(-1.0)
        assert miss == pytest.approx(0.0, abs=1e-9)

    def test_perpendicular_motion_large_miss(self):
        r1, v1 = np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 0.0])
        r2, v2 = np.array([1000.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
        tstar, miss = analytic_tca_and_miss(r1, v1, r2, v2, EPOCH)
        assert tstar == pytest.approx(0.0)
        assert miss == pytest.approx(1000.0)


class TestRefineTcaWithPropagator:
    def test_matches_analytic_result_for_linear_motion(self):
        # Propagator da doğrusal hareket varsaydığı için refine, analitik sonuçla
        # (xatol toleransı dahilinde) aynı çıkmalı.
        propagate = make_linear_propagator()
        sat1 = make_satrec([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
        sat2 = make_satrec([100.0, 0.0, 0.0], [-10.0, 0.0, 0.0])

        tca, miss, rel_vel = refine_tca_with_propagator(sat1, sat2, EPOCH, t_est_seconds=10.0,
                                                          propagate_func=propagate)
        assert (tca - EPOCH).total_seconds() == pytest.approx(10.0, abs=0.02)
        assert miss == pytest.approx(0.0, abs=1e-6)
        assert rel_vel == pytest.approx(10.0)

    def test_propagator_failure_returns_fallback_values(self):
        tca, miss, rel_vel = refine_tca_with_propagator(
            make_satrec([0, 0, 0], [0, 0, 0]), make_satrec([1, 0, 0], [0, 0, 0]),
            EPOCH, t_est_seconds=5.0, propagate_func=raising_propagator
        )
        assert miss == 99999.9
        assert rel_vel == 0.0


class TestComputeConjunctionForPair:
    def test_far_pair_skips_refinement(self):
        # miss > 150km -> analitik filtrede elenmeli, refine (propagate_func) HİÇ çağrılmamalı
        sat1 = make_satrec([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
        sat2 = make_satrec([1000.0, 0.0, 0.0], [0.0, 1.0, 0.0])
        r1, v1 = sat1['r0'], sat1['v0']
        r2, v2 = sat2['r0'], sat2['v0']

        result = compute_conjunction_for_pair(sat1, sat2, EPOCH, r1, v1, r2, v2, raising_propagator)

        assert result is not None
        assert result.score == 0.0
        assert result.miss_distance_km == pytest.approx(1000.0)

    def test_close_collision_course_classified_as_collision(self):
        propagate = make_linear_propagator()
        sat1 = make_satrec([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
        sat2 = make_satrec([100.0, 0.0, 0.0], [-10.0, 0.0, 0.0])
        r1, v1 = sat1['r0'], sat1['v0']
        r2, v2 = sat2['r0'], sat2['v0']

        result = compute_conjunction_for_pair(sat1, sat2, EPOCH, r1, v1, r2, v2, propagate)

        assert result is not None
        assert result.event_type == "COLLISION"
        assert result.miss_distance_km == pytest.approx(0.0, abs=1e-6)
        assert result.score == pytest.approx(1.0)
        assert result.rel_velocity_km_s == pytest.approx(10.0)

    def test_slow_close_approach_classified_as_docking(self):
        # Mesafe < 1km VE bağıl hız < 10 m/s (0.01 km/s) -> DOCKING
        propagate = make_linear_propagator()
        sat1 = make_satrec([0.0, 0.0, 0.0], [7.0, 0.0, 0.0])
        sat2 = make_satrec([0.5, 0.0, 0.0], [7.005, 0.0, 0.0])
        r1, v1 = sat1['r0'], sat1['v0']
        r2, v2 = sat2['r0'], sat2['v0']

        result = compute_conjunction_for_pair(sat1, sat2, EPOCH, r1, v1, r2, v2, propagate)

        assert result is not None
        assert result.event_type == "DOCKING"
        assert result.score == 1.0
        assert result.miss_distance_km < 1.0
        assert result.rel_velocity_km_s < 0.01

    def test_invalid_input_returns_none(self):
        # analytic_tca_and_miss'e geçersiz (None) vektör vermek bir exception fırlatmalı,
        # üst seviye try/except bunu yakalayıp None döndürmeli.
        result = compute_conjunction_for_pair(
            make_satrec([0, 0, 0], [0, 0, 0]), make_satrec([1, 0, 0], [0, 0, 0]),
            EPOCH, None, None, None, None, raising_propagator
        )
        assert result is None
