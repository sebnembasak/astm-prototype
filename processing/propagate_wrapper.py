from sgp4.api import Satrec, jday
from datetime import datetime
import numpy as np

"""
Verilen datetime anını Julian Date’e çevirir.
SGP4 modelini kullanarak uyduyu o anda propagate eder.
Uydunun konum (r) ve hız (v) vektörlerini (x, y, z – km, km/s) tuple olarak döndürür.
"""


def propagate_satrec_single(satrec: Satrec, dt: datetime) -> tuple[np.ndarray, np.ndarray]:
    jd, fr = jday(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second + dt.microsecond * 1e-6)
    err, r, v = satrec.sgp4(jd, fr)
    if err != 0:
        raise RuntimeError(f"SGP4 hatası: {err}")
    return np.array(r, dtype=float), np.array(v, dtype=float)
