from dataclasses import dataclass
from typing import Dict, List, Tuple

from processing.ground_station import PassWindow

"""
Aynı yer istasyonunda zaman içinde çakışan geçiş pencerelerini tespit eder.
Bir istasyon aynı anda sadece bir uydudan veri indirebileceği için, [aos, los)
aralığı çakışan iki PassWindow, istasyonun kapasitesini aşan bir taleptir.
"""


@dataclass
class ConflictPair:
    """Aynı istasyonda çakışan iki geçiş penceresi."""
    station_name: str
    window_a: PassWindow
    window_b: PassWindow

    @property
    def overlap_s(self) -> float:
        overlap_start = max(self.window_a.aos, self.window_b.aos)
        overlap_end = min(self.window_a.los, self.window_b.los)
        return max(0.0, (overlap_end - overlap_start).total_seconds())


def _windows_overlap(a: PassWindow, b: PassWindow) -> bool:
    return a.aos < b.los and b.aos < a.los


def detect_conflicts(windows: List[PassWindow]) -> List[ConflictPair]:
    """
    Geçiş pencerelerini istasyona göre gruplayıp, her grup içinde AOS zamanına
    göre sıralı bir tarama (sweep) ile çakışan çiftleri bulur. Karşılaştırma
    sayısı istasyon başına geçiş sayısının karesi ile orantılıdır; prototip
    ölçeğinde (80 uydu x birkaç istasyon, günlük geçiş sayısı) bu yeterlidir.
    """
    by_station: Dict[str, List[PassWindow]] = {}
    for w in windows:
        by_station.setdefault(w.station_name, []).append(w)

    conflicts: List[ConflictPair] = []
    for station_name, station_windows in by_station.items():
        ordered = sorted(station_windows, key=lambda w: w.aos)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                if ordered[j].aos >= ordered[i].los:
                    break  # AOS sıralı olduğundan, bu noktadan sonrası da çakışmaz
                if _windows_overlap(ordered[i], ordered[j]):
                    conflicts.append(ConflictPair(station_name, ordered[i], ordered[j]))

    return conflicts


def conflict_ratio(windows: List[PassWindow]) -> float:
    """
    Çakışmaya taraf olan (en az bir başka geçişle örtüşen) geçişlerin oranını
    döner. Örn. 0.0 -> hiç çakışma yok, 0.5 -> geçişlerin yarısı çakışıyor.
    """
    if not windows:
        return 0.0

    conflicting_ids: set[Tuple[int, str]] = set()
    for pair in detect_conflicts(windows):
        conflicting_ids.add((pair.window_a.sat_id, pair.window_a.aos.isoformat()))
        conflicting_ids.add((pair.window_b.sat_id, pair.window_b.aos.isoformat()))

    return len(conflicting_ids) / len(windows)
