from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, List, Optional, Tuple

import numpy as np
from astropy import units as u
from astropy.coordinates import AltAz, CartesianRepresentation, EarthLocation, ITRS, TEME
from astropy.time import Time

from ground_scheduling_config import DEFAULT_MIN_ELEVATION_DEG, DEFAULT_PASS_SCAN_STEP_SECONDS, \
    DEFAULT_STATION_ALT_KM

"""
Yer istasyonu - uydu görüş geometrisi (AOS/LOS) hesaplama modülü.
ASTM'in mevcut SGP4 propagasyon (processing/propagator.py) ve koordinat
dönüşümü (processing/coord_utils.py) altyapısını DEĞİŞTİRMEDEN, sadece
import edip kullanır; bu dosya sadece topocentric (yer istasyonu merkezli)
elevasyon hesabını ekler — coord_utils.py'de bu hesap yoktu.
"""


@dataclass
class GroundStation:
    """Bir yer istasyonunun konumu ve minimum görüş açısı eşiği."""
    name: str
    lat_deg: float
    lon_deg: float
    alt_km: float = DEFAULT_STATION_ALT_KM
    min_elevation_deg: float = DEFAULT_MIN_ELEVATION_DEG


@dataclass
class PassWindow:
    """Bir uydunun bir istasyon üzerinden tek bir geçişi (AOS -> LOS)."""
    sat_id: int
    sat_name: str
    station_name: str
    aos: datetime  # Acquisition of Signal
    los: datetime  # Loss of Signal
    max_elevation_deg: float

    @property
    def duration_s(self) -> float:
        return (self.los - self.aos).total_seconds()


def elevation_deg(r_km, time_utc: datetime, station: GroundStation) -> float:
    """
    Uydunun TEME konum vektöründen (r_km, propagator.py'nin ürettiği format),
    verilen yer istasyonuna göre topocentric elevasyon açısını (derece) hesaplar.

    coord_utils.teme_pos_to_latlon ile aynı TEME->ITRS dönüşüm zincirini izler,
    farkı ITRS sonrasında EarthLocation merkezli AltAz çerçevesine geçmesidir
    (uydunun mutlak konumu değil, istasyondan görünen açısı hesaplanır).
    """
    r_m = [x * 1000.0 for x in r_km]
    t = Time(time_utc.strftime('%Y-%m-%dT%H:%M:%S.%f'), format="isot", scale="utc")
    vec = CartesianRepresentation(r_m * u.m)
    teme_coord = TEME(vec, obstime=t)
    itrs = teme_coord.transform_to(ITRS(obstime=t))

    location = EarthLocation(
        lat=station.lat_deg * u.deg, lon=station.lon_deg * u.deg, height=station.alt_km * u.km
    )
    altaz = itrs.transform_to(AltAz(obstime=t, location=location))
    return float(altaz.alt.to(u.deg).value)


def elevation_deg_batch(rs_km: np.ndarray, times_utc: List[datetime], station: GroundStation) -> np.ndarray:
    """
    elevation_deg ile aynı matematiği, bir (uydu, istasyon) çifti için TÜM
    zaman örneklerine TEK bir astropy dönüşüm çağrısında (vektörize) uygular.
    Tek tek Time/transform_to çağrısı astropy'de pahalı olduğundan (her
    çağrıda ERFA rotasyon hesabı tekrarlanır), find_pass_windows içinde
    varsayılan (gerçek) elevasyon hesabı için bu kullanılır — ~8x hızlanma.
    """
    rs_m = np.asarray(rs_km, dtype=float) * 1000.0
    t = Time(times_utc)
    vec = CartesianRepresentation(rs_m[:, 0] * u.m, rs_m[:, 1] * u.m, rs_m[:, 2] * u.m)
    teme_coord = TEME(vec, obstime=t)
    itrs = teme_coord.transform_to(ITRS(obstime=t))

    location = EarthLocation(
        lat=station.lat_deg * u.deg, lon=station.lon_deg * u.deg, height=station.alt_km * u.km
    )
    altaz = itrs.transform_to(AltAz(obstime=t, location=location))
    return altaz.alt.to(u.deg).value


def find_pass_windows(
        sat_id: int,
        sat_name: str,
        satrec,
        station: GroundStation,
        start_utc: datetime,
        end_utc: datetime,
        propagate_func: Callable[[object, datetime], Tuple[np.ndarray, np.ndarray]],
        step_seconds: int = DEFAULT_PASS_SCAN_STEP_SECONDS,
        elevation_func: Callable[[np.ndarray, datetime, GroundStation], float] = elevation_deg,
) -> List[PassWindow]:
    """
    [start_utc, end_utc] aralığını step_seconds adımlarla tarayıp, elevasyonun
    station.min_elevation_deg eşiğini yukarı kestiği an AOS, aşağı kestiği an
    LOS kabul edilir. Eşik geçiş zamanı, ardışık örnekler arasında lineer
    interpolasyonla saniye hassasiyetinde bulunur (conjunction.py'deki gibi
    SGP4-seviyesi bir refinement burada gerekmez, çünkü geçiş pencereleri
    dakikalar sürer ve zamanlama hassasiyeti saniye düzeyinde yeterlidir).

    propagate_func ve elevation_func dependency injection ile alınır
    (propagate_func, processing/propagate_wrapper.py içindeki
    propagate_satrec_single ile aynı imza); bu sayede gerçek SGP4/astropy
    çağırmadan sahte/deterministik fonksiyonlarla test edilebilir.

    Not: Tarama aralığının sonunda hâlâ devam eden (LOS'a ulaşmamış) bir geçiş
    varsa, tamamlanmamış olduğu için sonuçlara dahil edilmez.
    """
    n_steps = int((end_utc - start_utc).total_seconds() // step_seconds) + 1
    times = [start_utc + timedelta(seconds=i * step_seconds) for i in range(n_steps)]
    rs = [propagate_func(satrec, t)[0] for t in times]

    if elevation_func is elevation_deg:
        # Varsayılan (gerçek astropy) elevasyon hesabı: tüm örnekleri tek seferde
        # vektörize ederek hesapla (bkz. elevation_deg_batch docstring'i).
        elevations = list(elevation_deg_batch(np.array(rs), times, station))
    else:
        # Test/enjeksiyon amaçlı sahte elevation_func: örnek başına çağrılır.
        elevations = [elevation_func(r, t, station) for r, t in zip(rs, times)]

    windows: List[PassWindow] = []
    in_pass = False
    aos_time: Optional[datetime] = None
    max_elev = -90.0

    for i in range(1, len(times)):
        t_prev = times[i - 1]
        e_prev, e_curr = elevations[i - 1], elevations[i]

        if not in_pass and e_prev < station.min_elevation_deg <= e_curr:
            frac = (station.min_elevation_deg - e_prev) / (e_curr - e_prev)
            aos_time = t_prev + timedelta(seconds=frac * step_seconds)
            in_pass = True
            max_elev = max(e_prev, e_curr)
        elif in_pass:
            max_elev = max(max_elev, e_curr)
            if e_prev >= station.min_elevation_deg > e_curr:
                frac = (e_prev - station.min_elevation_deg) / (e_prev - e_curr)
                los_time = t_prev + timedelta(seconds=frac * step_seconds)
                windows.append(PassWindow(
                    sat_id=sat_id, sat_name=sat_name, station_name=station.name,
                    aos=aos_time, los=los_time, max_elevation_deg=max_elev,
                ))
                in_pass = False
                aos_time = None
                max_elev = -90.0

    return windows


def compute_all_pass_windows(
        satellites: List[Tuple[int, str, object]],
        stations: List[GroundStation],
        start_utc: datetime,
        end_utc: datetime,
        propagate_func: Callable[[object, datetime], Tuple[np.ndarray, np.ndarray]],
        step_seconds: int = DEFAULT_PASS_SCAN_STEP_SECONDS,
        elevation_func: Callable[[np.ndarray, datetime, GroundStation], float] = elevation_deg,
) -> List[PassWindow]:
    """Birden fazla uydu x birden fazla istasyon için tüm geçiş pencerelerini toplu hesaplar."""
    all_windows: List[PassWindow] = []
    for sat_id, sat_name, satrec in satellites:
        for station in stations:
            all_windows.extend(find_pass_windows(
                sat_id, sat_name, satrec, station, start_utc, end_utc, propagate_func, step_seconds, elevation_func
            ))
    return all_windows
