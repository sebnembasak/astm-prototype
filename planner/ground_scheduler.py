from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

from processing.ground_station import PassWindow

"""
Bir istasyonda aynı anda yalnızca bir uydudan veri indirilebilir. Her
PassWindow zaten kendi station_name'ine özgü bir geometridir (AOS/LOS, o
istasyonun lat/lon'una göre hesaplanmıştır) — bir pencere başka bir
istasyona "aktarılamaz", çünkü o istasyonun o anda o uyduyla görüş hattı
olduğu garanti değildir. Bu nedenle çizelgeleme, istasyon başına bağımsız
bir tek-kaynak (single-resource) problemdir.

Algoritma: Earliest-Finish-Time (EFT) greedy. Tek kaynak için bu, çakışmasız
maksimum geçiş sayısını seçmede ispatlanmış optimaldir (klasik interval
scheduling teoremi) — ILP/OR-Tools gibi ağır bağımlılıklar gerekmez.

İstasyon sayısının kapasiteyi artırması, çakışmaların istasyonlar arasında
"dağıtılmasından" değil, her istasyonun (farklı coğrafi konumda, dolayısıyla
farklı/örtüşen uydu kümesini gören) kendi kuyruğunun küçülmesinden gelir.
"""


@dataclass
class ScheduleAssignment:
    sat_id: int
    sat_name: str
    station_name: str
    aos: datetime
    los: datetime
    assigned: bool


@dataclass
class ScheduleResult:
    assignments: List[ScheduleAssignment]
    total_passes: int
    missed_passes: int
    missed_duration_s: float
    capacity_loss_ratio: float  # missed_passes / total_passes
    station_utilization: Dict[str, int]  # istasyon adı -> atanan geçiş sayısı


def schedule_passes(windows: List[PassWindow]) -> ScheduleResult:
    """
    Geçişleri kendi istasyonlarına göre gruplar, her istasyonun kuyruğunda
    LOS zamanına göre (earliest finish time) sıralı greedy atama yapar:
    istasyon o anda boşsa geçiş atanır, değilse (önceki geçiş henüz
    bitmediyse) çakışmadan kaybedilmiş sayılır.
    """
    by_station: Dict[str, List[PassWindow]] = defaultdict(list)
    for w in windows:
        by_station[w.station_name].append(w)

    assignments: List[ScheduleAssignment] = []
    missed_passes = 0
    missed_duration_s = 0.0
    station_utilization: Dict[str, int] = {}

    for station_name, station_windows in by_station.items():
        ordered = sorted(station_windows, key=lambda w: w.los)
        busy_until: datetime = None
        assigned_count = 0

        for w in ordered:
            if busy_until is None or busy_until <= w.aos:
                busy_until = w.los
                assigned_count += 1
                assignments.append(ScheduleAssignment(
                    sat_id=w.sat_id, sat_name=w.sat_name, station_name=station_name,
                    aos=w.aos, los=w.los, assigned=True,
                ))
            else:
                missed_passes += 1
                missed_duration_s += w.duration_s
                assignments.append(ScheduleAssignment(
                    sat_id=w.sat_id, sat_name=w.sat_name, station_name=station_name,
                    aos=w.aos, los=w.los, assigned=False,
                ))

        station_utilization[station_name] = assigned_count

    total_passes = len(windows)
    capacity_loss_ratio = (missed_passes / total_passes) if total_passes else 0.0

    return ScheduleResult(
        assignments=assignments,
        total_passes=total_passes,
        missed_passes=missed_passes,
        missed_duration_s=missed_duration_s,
        capacity_loss_ratio=capacity_loss_ratio,
        station_utilization=station_utilization,
    )
