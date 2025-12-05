from skyfield.api import load, EarthSatellite
from skyfield.timelib import Time
import numpy as np
from datetime import datetime, timezone, timedelta

# Test Edilecek TLE'ler ---
# sat1 = 25544 (ISS ZARYA)
# sat2 = 49044 (ISS NAUKA)
tca_str = "2025-12-02T05:44:53.98501Z"
tle_iss_zarya = [
    'ISS (ZARYA)',
    '1 25544U 98067A   25335.57620886  .00008648  00000+0  16366-3 0  9990',
    '2 25544  51.6309 197.7449 0003647 190.9481 169.1428 15.49226524541123'
]
tle_iss_nauka = [
    'ISS (NAUKA)',
    '1 49044U 21066A   25335.57620886  .00008648  00000+0  16366-3 0  9996',
    '2 49044  51.6309 197.7449 0003647 190.9481 169.1428 15.49226524230444'
]


def verify_conjunction(tle1, tle2, tca_utc_str):
    """
    Verilen TLE'ler ve tahmini TCA zamanı etrafında yörünge yayılımı yapar
    ve minimum mesafeyi (miss distance) hesaplar.
    """
    ts = load.timescale()

    # TLE'leri EarthSatellite nesnelerine dönüştür
    sat1 = EarthSatellite(tle1[1], tle1[2], tle1[0], ts)
    sat2 = EarthSatellite(tle2[1], tle2[2], tle2[0], ts)

    # Zaman adımlarını oluştur (1 saniyelik adımlar)
    # Skyfield zaman nesnesi oluştur
    # TCA zamanını ve etrafındaki zaman aralığını tanımla
    tca_dt = datetime.strptime(tca_utc_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)

    # TCA'nın 5 dakika öncesinden 5 dakika sonrasına kadar her saniye hesapla
    start_dt = tca_dt - timedelta(minutes=5)
    end_dt = tca_dt + timedelta(minutes=5)

    # 1 saniyelik adımlarla tüm zaman noktalarını oluşturun
    times_dt = []
    current_time = start_dt
    while current_time <= end_dt:
        times_dt.append(current_time)
        current_time += timedelta(seconds=1)

    if not times_dt:
        print("Hata: Zaman aralığı oluşturulamadı.")
        return

    # Oluşturulan tüm datetime nesnelerini tek bir Skyfield zaman nesnesine dönüştürün
    times = ts.utc(times_dt)

    # Pozisyonları hesapla
    # Geocentric pozisyonlar (km cinsinden)
    p1 = sat1.at(times).position.km
    p2 = sat2.at(times).position.km

    # Aralarındaki vektör farkını bul
    difference = p1 - p2

    # Her an için mesafeyi hesapla
    distances_km = np.sqrt(np.sum(difference ** 2, axis=0))

    # Minimum mesafeyi ve zaman indeksini bul
    min_distance_km = np.min(distances_km)
    min_index = np.argmin(distances_km)

    # Minimum mesafenin gerçekleştiği zamanı bul
    tca_recalculated = times[min_index]

    print(f"--- Doğrulama Sonuçları ({tle1[0]} vs {tle2[0]}) ---")
    print(f"Orijinal TCA (Çıktı): {tca_str}")
    print(f"Orijinal Miss Distance:   {0.005401871371767645:.6f} km")
    print("-" * 50)
    print(f"Hesaplanan Minimum Mesafe (SGP4): {min_distance_km:.6f} km")
    print(f"Hesaplanan TCA (UTC):           {tca_recalculated.utc_strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} UTC")

    # Karşılaştırma
    tolerance = 0.01  # 10 metre tolerans
    if np.abs(min_distance_km - 0.00540187) < tolerance:
        print("\nSonuçlar TUTARLI görünüyor. Hesaplanan mesafe, orijinal çıktıdaki değere çok yakın.")
    else:
        print("\nSonuçlar TUTARSIZ. Hesaplanan mesafe, orijinal çıktıdaki değerden farklı çıktı.")


# Script'i çalıştır
verify_conjunction(tle_iss_zarya, tle_iss_nauka, tca_str)