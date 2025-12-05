from sgp4.api import Satrec
from sgp4.api import jday
from datetime import datetime, timezone
from typing import List, Tuple


# TLE Dizilerini SGP4 Uydusuna Dönüştürme
def tle_to_satrec(line1: str, line2: str) -> Satrec:
    """
    Verilen TLE (Two-Line Element) verisinin 1. ve 2. satırlarını kullanarak
    sgp4 kütüphanesinin Satrec (Satellite Record) nesnesini oluşturur.
    Bu nesne propagasyon için gerekli tüm yörünge parametrelerini içerir.
    """
    return Satrec.twoline2rv(line1, line2)


# UTC Tarih Saatini Julian Tarihine Dönüştür
def utc_dt_to_jd(dt: datetime) -> Tuple[float, float]:
    """
    SGP4 algoritması zamanı Julian Tarihi formatında bekler.
    Bu nedenle UTC -> JD dönüşümü yapılır.
    """
    jd, fr = jday(
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second + dt.microsecond * 1e-6  # Mikrosaniyeyi saniyeye dönüştürerek ekle
    )
    return jd, fr


# Uydu Yörüngesini Propagasyon
def propagate_satrec(sat: Satrec, times_utc: List[datetime]):
    """
    Verilen Satrec nesnesini, liste içindeki her bir UTC zaman noktası için
    SGP4 algoritmasını kullanarak ilerletir (propagate).

    :param sat: tle_to_satrec tarafından oluşturulan Satrec nesnesi
    :param times_utc: Konum/hız hesaplamasının yapılacağı UTC datetime listesi
    :return: Her bir zaman noktası için TEME km cinsinden konum (r) ve
             km/s cinsinden hız (v) içeren sözlüklerin listesi.
    """
    results = []
    for t in times_utc:
        # UTC zamanını Julian Tarihine dönüştür
        jd, fr = utc_dt_to_jd(t)

        # SGP4 algoritmasını çalıştır
        # e: Hata kodu (0 = Başarılı)
        # r: Konum vektörü [Rx, Ry, Rz] (km, TEME koordinat sistemi)
        # v: Hız vektörü [Vx, Vy, Vz] (km/s, TEME koordinat sistemi)
        e, r, v = sat.sgp4(jd, fr)

        if e != 0:
            # SGP4 bir hata kodu döndürürse (örneğin, -1 = uydu düştü, -2 = uydu yükseldi)
            # bir RuntimeError yükseltir.
            raise RuntimeError(f"SGP4 error code {e}")

        # Sonuçları listeye ekle
        # r, v değerleri TEME (True Equator, Mean Equinox) koordinat sistemindedir.
        results.append({
            "time": t,
            "r_km": r,  # Konum (km)
            "v_km_s": v  # Hız (km/s)
        })
    return results