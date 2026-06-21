from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from backend.models.db import get_conn
from ground_scheduling_config import (
    CANDIDATE_GROUND_STATIONS,
    DEFAULT_SCENARIO_DURATION_HOURS,
    MAX_ADDITIONAL_STATIONS_SEARCH,
    SCENARIO_SATELLITE_COUNTS,
    SCENARIO_STATION_COUNTS,
    TARGET_CAPACITY_LOSS_REDUCTION_PCT,
)
from planner.ground_scheduler import schedule_passes
from processing.ground_station import GroundStation, compute_all_pass_windows
from processing.propagate_wrapper import propagate_satrec_single
from service.tle_service import tle_service

"""
Hello Space tipi büyüyen bir pocketqube constellation operatörü için kapasite
planlama senaryo motoru: farklı uydu sayısı (3/10/30/80) x farklı istasyon
sayısı (1/2/3) kombinasyonlarında, geçişlerin ne kadarının çakışmadan
kaybedildiğini (kapasite kaybı) hesaplar ve "bu kaybı %50 azaltmak için kaç
ek istasyon gerekir" sorusuna geriye-doğru arama ile cevap üretir.
"""


@dataclass
class ScenarioResult:
    num_satellites: int  # talep edilen uydu sayısı
    actual_satellites_used: int  # DB'de mevcut olup gerçekten kullanılan sayı
    num_stations: int
    total_passes: int
    missed_passes: int
    capacity_loss_pct: float
    additional_stations_for_target: Optional[int]  # kaybı hedef oranda azaltmak için gereken EK istasyon sayısı
    # None -> CANDIDATE_GROUND_STATIONS havuzu / MAX_ADDITIONAL_STATIONS_SEARCH içinde hedefe ulaşılamadı


class CapacityPlanningService:

    def _load_satellites(self, count: int) -> List[Tuple[int, str, object]]:
        """tle_service'ten Hello Space'in 525km/97.5° SSO profiline yakın
        GERÇEK TLE'leri okur (bkz. tle_service.get_satellites_by_orbit_profile),
        sgp4 Satrec'e çevirir. Katalogda bu yörünge bandında istenen sayıdan az
        nesne varsa mevcut olanlarla devam eder."""
        rows = tle_service.get_satellites_by_orbit_profile(limit=count)
        satellites = []
        for row in rows:
            satrec = tle_service.get_satrec_by_id(row["id"])
            if satrec is not None:
                satellites.append((row["id"], row["sat_name"], satrec))
        return satellites

    def _build_stations(self, count: int) -> List[GroundStation]:
        """CANDIDATE_GROUND_STATIONS havuzundan ilk `count` istasyonu GroundStation olarak döner."""
        pool = CANDIDATE_GROUND_STATIONS[:count]
        return [GroundStation(name=s["name"], lat_deg=s["lat_deg"], lon_deg=s["lon_deg"]) for s in pool]

    def _stations_needed_for_target(
            self,
            satellites: List[Tuple[int, str, object]],
            base_station_count: int,
            base_windows: list,
            base_loss_ratio: float,
            start_utc: datetime,
            end_utc: datetime,
            reduction_pct: float = TARGET_CAPACITY_LOSS_REDUCTION_PCT,
    ) -> Optional[int]:
        """
        Mevcut istasyon sayısına kaç istasyon EKLENİRSE kapasite kaybının
        `reduction_pct` kadar azalacağını, CANDIDATE_GROUND_STATIONS havuzundan
        sırayla istasyon ekleyerek arar. Zaten kayıp yoksa 0 döner.
        Havuz veya MAX_ADDITIONAL_STATIONS_SEARCH sınırı içinde hedefe
        ulaşılamazsa None döner.

        Performans: her adımda SADECE yeni eklenen tek istasyonun geçiş
        pencereleri hesaplanır ve önceki pencerelere eklenir (kümülatif) —
        her adımda tüm istasyon kümesini sıfırdan yeniden hesaplamak
        (O(extra²)) yerine O(extra) maliyetle çalışır.
        """
        if base_loss_ratio <= 0.0:
            return 0

        target_ratio = base_loss_ratio * (1.0 - reduction_pct / 100.0)
        max_extra = min(MAX_ADDITIONAL_STATIONS_SEARCH, len(CANDIDATE_GROUND_STATIONS) - base_station_count)

        accumulated_windows = list(base_windows)
        for extra in range(1, max_extra + 1):
            new_station = self._build_stations(base_station_count + extra)[-1]
            new_windows = compute_all_pass_windows(
                satellites, [new_station], start_utc, end_utc, propagate_satrec_single
            )
            accumulated_windows.extend(new_windows)

            loss_ratio = schedule_passes(accumulated_windows).capacity_loss_ratio
            if loss_ratio <= target_ratio:
                return extra

        return None

    def run_scenario(
            self,
            num_satellites: int,
            num_stations: int,
            duration_hours: int = DEFAULT_SCENARIO_DURATION_HOURS,
    ) -> ScenarioResult:
        """Tek bir (uydu sayısı, istasyon sayısı) kombinasyonu için kapasite kaybı senaryosu çalıştırır."""
        start_utc = datetime.now(timezone.utc)
        end_utc = start_utc + timedelta(hours=duration_hours)

        satellites = self._load_satellites(num_satellites)
        stations = self._build_stations(num_stations)

        windows = compute_all_pass_windows(satellites, stations, start_utc, end_utc, propagate_satrec_single)
        base_result = schedule_passes(windows)

        additional_needed = self._stations_needed_for_target(
            satellites, num_stations, windows, base_result.capacity_loss_ratio, start_utc, end_utc
        )

        return ScenarioResult(
            num_satellites=num_satellites,
            actual_satellites_used=len(satellites),
            num_stations=num_stations,
            total_passes=base_result.total_passes,
            missed_passes=base_result.missed_passes,
            capacity_loss_pct=base_result.capacity_loss_ratio * 100.0,
            additional_stations_for_target=additional_needed,
        )

    def run_all_scenarios(
            self,
            satellite_counts: List[int] = None,
            station_counts: List[int] = None,
            duration_hours: int = DEFAULT_SCENARIO_DURATION_HOURS,
    ) -> List[ScenarioResult]:
        """Hello Space'in büyüme hedefine paralel uydu sayıları x istasyon sayıları
        ızgarasını tarayıp, her kombinasyon için kapasite kaybı senaryosu üretir."""
        satellite_counts = satellite_counts or SCENARIO_SATELLITE_COUNTS
        station_counts = station_counts or SCENARIO_STATION_COUNTS

        return [
            self.run_scenario(num_satellites=n_sat, num_stations=n_stat, duration_hours=duration_hours)
            for n_sat in satellite_counts
            for n_stat in station_counts
        ]

    def save_scenario_results(self, scenario_label: str, num_stations: int, num_satellites: int) -> None:
        """Tekil bir senaryonun çizelgeleme atamalarını scheduling_results tablosuna kalıcı olarak yazar."""
        start_utc = datetime.now(timezone.utc)
        end_utc = start_utc + timedelta(hours=DEFAULT_SCENARIO_DURATION_HOURS)

        satellites = self._load_satellites(num_satellites)
        stations = self._build_stations(num_stations)
        windows = compute_all_pass_windows(satellites, stations, start_utc, end_utc, propagate_satrec_single)
        result = schedule_passes(windows)

        now = datetime.now(timezone.utc).isoformat()
        conn = get_conn()
        cur = conn.cursor()
        for a in result.assignments:
            cur.execute("""
                INSERT INTO scheduling_results
                    (scenario_label, sat_id, station_name, aos, los, assigned, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                scenario_label, a.sat_id, a.station_name, a.aos.isoformat(), a.los.isoformat(),
                int(a.assigned), now,
            ))
        conn.commit()
        conn.close()


# Singleton instance
capacity_planning_service = CapacityPlanningService()
