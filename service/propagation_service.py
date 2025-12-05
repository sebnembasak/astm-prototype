from datetime import datetime, timedelta
from typing import List, Dict, Any
from service.tle_service import tle_service
from processing.propagator import propagate_satrec
from processing.coord_utils import teme_pos_to_latlon


class PropagationService:
    """
    Bu servis uydunun belirli bir zaman aralığındaki hareketini (Lat/Lon/Alt) simüle eder.
    Çarpışma analizinden farklı olarak, buradaki amaç 'Görselleştirme'dir.
    Frontend tarafında uydu yörüngesini çizmek için kullanılır.
    """

    def propagate_satellite(self, sat_id: int, start_time: datetime, end_time: datetime, step_seconds: int = 60) -> \
            List[Dict[str, Any]]:
        """
        Belirtilen uyduyu, başlangıç ve bitiş zamanları arasında 'step_seconds' adımlarla ilerletir.
        Args:
            sat_id: Uydunun veritabanı IDsi.
            start_time: Simülasyon başlangıcı.
            end_time: Simülasyon bitişi.
            step_seconds: Hassasiyet ayarı. (Örn: 60sn = 1 dakikada bir nokta koy).
                Düşük değer = Daha pürüzsüz çizgi ama daha çok işlemci yükü.
        """

        # uydunun sgp4 modelini TLE servisinden al
        satrec = tle_service.get_satrec_by_id(sat_id)
        if not satrec:
            raise ValueError(f"Bu id ile uydu bulunamadı. ID: {sat_id}")

        # Zaman adımlarını oluştur
        # SGP4 kütüphaneleri genellikle toplu (vectorized) işleme göre yazılmıştır
        # Bu yüzden önce hesaplanacak tüm zaman noktalarını bir listeye dolduruyoruz
        times = []
        current = start_time
        while current <= end_time:
            times.append(current)
            current += timedelta(seconds=step_seconds)

        # Yörünge Yayılımı (Propagation) - TEME Koordinatları
        # processing.propagator modülü, SGP4 algoritmasını kullanarak
        # uydunun bu zamanlardaki X, Y, Z konumlarını (Dünya Merkezli Eylemsiz - TEME) hesaplar
        states = propagate_satrec(satrec, times)

        results = []
        for state in states:
            # SGP4 çıktısı ham uzay koordinatlarıdır
            r_km = state["r_km"]
            t_utc = state["time"]

            # Koordinat Dönüşümü (TEME -> Lat/Lon/Alt)
            # Dünya yüzeyinde anlaşılır olan enlem ve boylam değerlerine çevirme
            # Bu fonksiyon Dünya'nın dönüşünü (GST - Greenwich Sidereal Time) hesaba katarak
            # uzaydaki sabit noktayı, dönen Dünya üzerindeki harita noktasına izdüşürür
            lat, lon, alt = teme_pos_to_latlon(r_km, t_utc)

            results.append({
                "time": t_utc.isoformat(),
                # SGP4 veya numpy bazen 'tuple' veya 'numpy array' döndürür
                # JSON serileştirici bunları tanımaz, bu nedenle standart Python listesine çevirdik
                "position_km": list(r_km),
                "velocity_km_s": list(state["v_km_s"]),
                "lat": lat,
                "lon": lon,
                "alt_km": alt
            })

        return results


# Singleton instance
propagation_service = PropagationService()
