from datetime import datetime, timedelta
from typing import Dict, Any
from service.tle_service import tle_service
from planner.optimizer import find_minimal_dv
from processing.propagate_wrapper import propagate_satrec_single


class ManeuverService:
    """
    Bu servis tespit edilen bir çarpışma riski için en uygun kaçınma manevrasını hesaplar.
    Matematiksel optimizasyon motorunu (find_minimal_dv) kullanır ve sonuçları
    API'nin anlayacağı formatta sunar.
    """
    def calculate_avoidance_maneuver(self,
                                     sat_id_primary: int,
                                     sat_id_secondary: int,
                                     tca: datetime,
                                     target_miss_km: float = 2.0) -> Dict[str, Any]:
        """
        İki uydu arasındaki çarpışmayı önlemek için gerekli ateşleme planını oluşturur.
        Args:
            sat_id_primary: Manevrayı yapacak olan uydumuz.
            sat_id_secondary: Çarpışma riski taşıyan diğer obje (enkaz veya uydu).
            tca: Time of Closest Approach (En Yakın Geçiş Zamanı).
            target_miss_km: Hedeflenen güvenli mesafe (Varsayılan: 2 km).
        """
        # Uyduların matematiksel modellerini yani SGP4 nesnelerini getir
        sat1 = tle_service.get_satrec_by_id(sat_id_primary)
        sat2 = tle_service.get_satrec_by_id(sat_id_secondary)

        if not sat1 or not sat2:
            raise ValueError("Uydular bulunamadı")

        # Zaman Kaldıracı (Time Leverage) Stratejisi
        # Raporda manevra simülasyonu için 'burn time' kavramından bahsetmiştik
        # Burada ateşleme zamanını TCA'dan 1 saat (3600 sn) öncesine çekiyoruz.
        # Çünkü çarpışmadan ne kadar önce manevra yaparsak, o kadar az yakıt (DeltaV) harcarız.
        # Çok küçük bir açı değişikliği, 1 saatlik uçuş süresinde km'lerce fark yaratır.
        burn_time = tca - timedelta(seconds=3600)

        # Optimizasyon Motorunu Çalıştır - Minimize J(dv) fonksiyonu
        proposal = find_minimal_dv(
            satrec_target=sat2,
            satrec_our=sat1,
            burn_time=burn_time,
            tca_time=tca,
            propagate_func=propagate_satrec_single,
            target_miss_km=target_miss_km,
            # DeltaV sınırı
            # impulsive hız değişimi büyüklüğü (dv_mag) optimize edilir
            # burada motora "Maksimum 2 m/s (0.002 km/s) harcayabilirsin" diyoruz
            # bu sınır uydunun yakıt bütçesini korumak için ayarlanabilir
            dv_bound_km_s=0.002,
            # miss distance hedefine ulaşmak, yakıt tasarrufundan daha önceliklidir
            # katsayı bu nedenle yüksek tutulmuştur
            penalty_lambda=100000.0,
            verbose=False
        )

        return {
            "success": proposal.success,
            "burn_time": proposal.burn_time.isoformat(),
            "tca_original": tca.isoformat(),
            "predicted_miss_km": proposal.predicted_miss_km,
            "dv_vector_m_s": (proposal.dv_km_s * 1000).tolist(),
            "dv_magnitude_m_s": proposal.dv_mag_m_s,
            "message": proposal.message
        }


# Singleton instance
maneuver_service = ManeuverService()
