import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import numpy as np
import pytest

from planner.optimizer import (
    rv_to_orbit,
    propagate_orbit_to,
    compute_miss_distance_after_burn,
    find_minimal_dv,
)


EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)

# ~400 km irtifa, dairesel yörünge yarıçapı ve hızı (MU_EARTH=398600.4418 km^3/s^2)
R_CIRC = 6778.0
V_CIRC = float(np.sqrt(398600.4418 / R_CIRC))


def make_linear_propagator():
    def propagate(satrec, t):
        dt = (t - satrec['t0']).total_seconds()
        r = satrec['r0'] + satrec['v0'] * dt
        v = satrec['v0']
        return r, v
    return propagate


def make_satrec(r0, v0, t0=EPOCH):
    return {'r0': np.array(r0, dtype=float), 'v0': np.array(v0, dtype=float), 't0': t0}


def raising_propagator(*_args, **_kwargs):
    raise RuntimeError("propagate_func çağrılmamalıydı")


class TestRvToOrbitAndPropagate:
    def test_rv_to_orbit_round_trip(self):
        r = np.array([R_CIRC, 0.0, 0.0])
        v = np.array([0.0, V_CIRC, 0.0])
        orbit = rv_to_orbit(r, v, EPOCH)
        assert orbit.r.to('km').value == pytest.approx(r, abs=1e-6)
        assert orbit.v.to('km/s').value == pytest.approx(v, abs=1e-6)

    def test_propagate_zero_time_returns_same_position(self):
        r = np.array([R_CIRC, 0.0, 0.0])
        v = np.array([0.0, V_CIRC, 0.0])
        orbit = rv_to_orbit(r, v, EPOCH)
        r_after = propagate_orbit_to(orbit, EPOCH)
        assert r_after == pytest.approx(r, abs=1e-3)

    def test_propagate_preserves_circular_radius(self):
        r = np.array([R_CIRC, 0.0, 0.0])
        v = np.array([0.0, V_CIRC, 0.0])
        orbit = rv_to_orbit(r, v, EPOCH)
        r_after = propagate_orbit_to(orbit, EPOCH + timedelta(seconds=300))
        assert np.linalg.norm(r_after) == pytest.approx(R_CIRC, abs=1e-2)
        # 300 saniyede dairesel yörüngede konum değişmiş olmalı
        assert np.linalg.norm(r_after - r) > 1.0


class TestComputeMissDistanceAfterBurn:
    """
    'our' ve 'target' uydular aynı hızla (rel v=0), 0.5 km z-ofsetiyle co-moving.
    burn_time != tca_time olduğu için DV'nin Keplerian etkisi (delta_r) ölçülebilir.
    """

    def _make_pair(self):
        burn_time = EPOCH
        tca_time = EPOCH + timedelta(seconds=300)
        our = make_satrec([R_CIRC, 0.0, 0.0], [0.0, V_CIRC, 0.0], t0=burn_time)
        target = make_satrec([R_CIRC, 0.0, 0.5], [0.0, V_CIRC, 0.0], t0=burn_time)
        return our, target, burn_time, tca_time

    def test_zero_dv_keeps_baseline_miss_distance(self):
        our, target, burn_time, tca_time = self._make_pair()
        propagate = make_linear_propagator()
        miss, rel_vel = compute_miss_distance_after_burn(
            target, our, burn_time, np.zeros(3), tca_time, propagate
        )
        # DV=0 -> delta_r=0 -> miss tam olarak başlangıç ofsetine (0.5km) eşit olmalı
        assert miss == pytest.approx(0.5, abs=1e-6)
        assert rel_vel == pytest.approx(0.0, abs=1e-6)

    def test_nonzero_dv_changes_miss_distance(self):
        # Yörünge düzlemine dik (z) bir DV, kısa vade için periyodik/doğrusal-olmayan bir
        # konum etkisi yaratır (out-of-plane salınım); bu yüzden yönünü değil, sadece
        # DV=0 temel çizgisinden FARKLI bir sonuç ürettiğini doğruluyoruz.
        our, target, burn_time, tca_time = self._make_pair()
        propagate = make_linear_propagator()
        miss_a, _ = compute_miss_distance_after_burn(
            target, our, burn_time, np.array([0.0, 0.0, -0.001]), tca_time, propagate
        )
        miss_b, _ = compute_miss_distance_after_burn(
            target, our, burn_time, np.array([0.0, 0.0, 0.001]), tca_time, propagate
        )
        assert miss_a != pytest.approx(0.5, abs=1e-6)
        assert miss_b != pytest.approx(0.5, abs=1e-6)
        # +z ve -z dv'ler birbirinin simetriği olduğu için farklı sonuç vermeli
        assert miss_a != pytest.approx(miss_b, abs=1e-6)


class TestFindMinimalDv:
    def test_optimizer_error_path_returns_failure(self):
        our = make_satrec([R_CIRC, 0.0, 0.0], [0.0, V_CIRC, 0.0])
        target = make_satrec([R_CIRC, 0.0, 0.5], [0.0, V_CIRC, 0.0])
        proposal = find_minimal_dv(
            target, our, EPOCH, EPOCH + timedelta(seconds=300), raising_propagator
        )
        assert proposal.success is False
        assert "Optimizer Error" in proposal.message

    def test_small_dv_bound_cannot_reach_far_target(self):
        # Başlangıç mesafesi 0.5km; hedef 5km, çok uzak. dv_bound küçük (1 m/s, 300s)
        # olduğu için hedefe ulaşılamamalı (success=False). `bounds` her eksene ayrı
        # ayrı uygulandığından (küresel değil kutu kısıt), vektör büyüklüğü en fazla
        # dv_bound*sqrt(3) olabilir.
        our = make_satrec([R_CIRC, 0.0, 0.0], [0.0, V_CIRC, 0.0])
        target = make_satrec([R_CIRC, 0.0, 0.5], [0.0, V_CIRC, 0.0])
        propagate = make_linear_propagator()
        dv_bound = 0.001
        proposal = find_minimal_dv(
            target, our, EPOCH, EPOCH + timedelta(seconds=300), propagate,
            target_miss_km=5.0, dv_bound_km_s=dv_bound
        )
        assert proposal.success is False
        assert proposal.dv_mag_km_s <= dv_bound * np.sqrt(3) + 1e-6
        assert proposal.predicted_miss_km < 5.0

    def test_sufficient_dv_bound_reaches_target(self):
        # Aynı senaryo ama dv_bound bol (100 m/s) -> hedefe ulaşılabilmeli (success=True)
        our = make_satrec([R_CIRC, 0.0, 0.0], [0.0, V_CIRC, 0.0])
        target = make_satrec([R_CIRC, 0.0, 0.5], [0.0, V_CIRC, 0.0])
        propagate = make_linear_propagator()
        proposal = find_minimal_dv(
            target, our, EPOCH, EPOCH + timedelta(seconds=300), propagate,
            target_miss_km=1.0, dv_bound_km_s=0.1
        )
        assert proposal.success is True
        assert proposal.predicted_miss_km >= 1.0 - 0.001
