import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from processing.ground_station import PassWindow
from service.capacity_planning_service import CapacityPlanningService

"""
_stations_needed_for_target, gerçek SGP4/astropy çağırmadan, GREEDY
EN-İYİ-İSTASYON seçiminin sabit liste sırası değil gerçek kayıp-azaltma
etkisine göre çalıştığını doğrulayan testler. compute_all_pass_windows
mock'lanarak her aday istasyonun "kendi başına" üreteceği pencereler
sabitlenir; CANDIDATE_GROUND_STATIONS da test içinde sahte bir havuzla
değiştirilir (liste sırası kasıtlı olarak en iyi adayı SON sıraya koyar,
böylece eski sıralı yaklaşım yanlış sonucu, greedy ise doğru sonucu verir).
"""

EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_window(sat_id, station_name, aos_offset_s, los_offset_s):
    return PassWindow(
        sat_id=sat_id, sat_name=f"SAT-{sat_id}", station_name=station_name,
        aos=EPOCH + timedelta(seconds=aos_offset_s),
        los=EPOCH + timedelta(seconds=los_offset_s),
        max_elevation_deg=45.0,
    )


# Liste sırası kasıtlı olarak en kötü (Worse) önce, en iyi (Big) en sonda —
# eski "sıralı ekleme" yaklaşımı Worse'u seçer, greedy ise Big'i seçmeli.
FAKE_STATION_POOL = [
    {"name": "Worse", "lat_deg": 0.0, "lon_deg": 0.0},
    {"name": "Small", "lat_deg": 10.0, "lon_deg": 10.0},
    {"name": "Big", "lat_deg": 20.0, "lon_deg": 20.0},
]

# Her aday istasyonun "kendi başına" (çakışmasız) üreteceği pencere sayısı.
# Daha çok çakışmasız pencere -> toplam geçiş sayısını daha çok seyrelterek
# genel kapasite kaybı oranını daha çok düşürür.
CANDIDATE_WINDOW_COUNTS = {"Worse": 0, "Small": 1, "Big": 5}


def fake_compute_all_pass_windows(satellites, stations, start_utc, end_utc, propagate_func):
    station = stations[0]
    count = CANDIDATE_WINDOW_COUNTS[station.name]
    return [
        make_window(sat_id=100 + i, station_name=station.name, aos_offset_s=i * 1000, los_offset_s=i * 1000 + 100)
        for i in range(count)
    ]


class TestStationsNeededForTargetGreedy:

    def setup_method(self):
        self.svc = CapacityPlanningService()
        # base: aynı istasyonda çakışan 2 geçiş -> 1 atanır, 1 kaybedilir (loss=0.5)
        self.base_windows = [
            make_window(sat_id=1, station_name="Base", aos_offset_s=0, los_offset_s=100),
            make_window(sat_id=2, station_name="Base", aos_offset_s=50, los_offset_s=150),
        ]

    @patch("service.capacity_planning_service.CANDIDATE_GROUND_STATIONS", FAKE_STATION_POOL)
    @patch("service.capacity_planning_service.compute_all_pass_windows", side_effect=fake_compute_all_pass_windows)
    def test_greedy_picks_best_station_not_list_order(self, mock_compute):
        extra, path = self.svc._stations_needed_for_target(
            satellites=[], base_station_count=0, base_windows=self.base_windows,
            base_loss_ratio=0.5, start_utc=EPOCH, end_utc=EPOCH + timedelta(hours=24),
            reduction_pct=50.0,
        )
        # Hedef: loss <= 0.5 * (1 - 0.5) = 0.25.
        # "Worse" (liste sırasında ilk) eklenirse loss değişmez (0.5 > 0.25).
        # Greedy, sıradaki değil EN ÇOK azaltan "Big"i (loss=1/7≈0.143) seçmeli.
        assert path[0] == "Big"
        assert extra == 1

    @patch("service.capacity_planning_service.CANDIDATE_GROUND_STATIONS", FAKE_STATION_POOL)
    @patch("service.capacity_planning_service.compute_all_pass_windows", side_effect=fake_compute_all_pass_windows)
    def test_unreachable_target_returns_none_with_attempted_path(self, mock_compute):
        extra, path = self.svc._stations_needed_for_target(
            satellites=[], base_station_count=0, base_windows=self.base_windows,
            base_loss_ratio=0.5, start_utc=EPOCH, end_utc=EPOCH + timedelta(hours=24),
            reduction_pct=99.0,  # loss <= 0.005 -- bu sahte havuzla asla ulaşılamaz
        )
        assert extra is None
        # Tüm adaylar tükenene kadar denenmiş olmalı, en iyiden en kötüye sırayla.
        assert path == ["Big", "Small", "Worse"]

    def test_zero_base_loss_returns_zero_without_computing(self):
        extra, path = self.svc._stations_needed_for_target(
            satellites=[], base_station_count=0, base_windows=[],
            base_loss_ratio=0.0, start_utc=EPOCH, end_utc=EPOCH + timedelta(hours=24),
        )
        assert (extra, path) == (0, [])
