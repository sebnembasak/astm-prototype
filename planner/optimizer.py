from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Tuple, Callable
import numpy as np
from scipy.optimize import minimize
from astropy.time import Time
import astropy.units as u
from poliastro.bodies import Earth
from poliastro.twobody import Orbit

"""
Eğer şu an motorları ateşleyip hız vektörüne X kadar ekleme yapsaydık, 
TCA anında diğer uyduya ne kadar uzak olurduk? Cevaplamak istediğimiz soru bu.
scipy.optimize kütüphanesi ile simülasyon fonksiyonu çağırılarak hem hedef mesafeyi hem
de deltaV yani yakıtı düşük tutan vektörü deneyip bulmayı amaçlıyoruz.
"""


@dataclass
class ManeuverProposal:
    dv_km_s: np.ndarray  # 3 boyutlu deltaV vektörü (vx, vy, vz)
    dv_mag_km_s: float  # deltaV büyüklüğü km/s, yakıt maliyeti
    dv_mag_m_s: float  # deltaV büyüklüğü m/s
    burn_time: datetime  # manevranın yapılacağı zaman
    predicted_tca: datetime  # tahmini en yakın yaklaşım zamanı
    predicted_miss_km: float  # tahmini miss distance (km)
    predicted_rel_vel_km_s: float
    success: bool  # başarı durumu
    message: str  # açıklama


def rv_to_orbit(r_km: np.ndarray, v_km_s: np.ndarray, epoch_dt: datetime) -> Orbit:
    """
    Konum (r) ve Hız (v) vektörlerinden bir 'poliastro.Orbit' nesnesi oluşturur.
    Manevra sonrası yörüngeyi iki cisim problemi olarak çözmek için kullanılır.
    """
    t = Time(epoch_dt.replace(tzinfo=None).strftime('%Y-%m-%dT%H:%M:%S.%f'), format="isot", scale="utc")
    # Vektörleri birimli hale getirip Dünya merkezli yörünge nesnesi oluştur
    return Orbit.from_vectors(Earth, r_km * u.km, v_km_s * u.km / u.s, epoch=t)


def propagate_orbit_to(orbit: Orbit, target_dt: datetime) -> np.ndarray:
    """
    Verilen bir yörüngeyi (bizim durumumuzda Orbit nesnesini),
    hedef zamana (target_dt) kadar ilerletir ve yeni konumu döndürür.
    """
    t_target = Time(target_dt.replace(tzinfo=None).strftime('%Y-%m-%dT%H:%M:%S.%f'), format="isot", scale="utc")
    tof = (t_target - orbit.epoch).to(u.s)  # time of flight
    new_orbit = orbit.propagate(tof)
    return np.array(new_orbit.r.to(u.km).value, dtype=float)


# Simülasyon Kısmı
def compute_miss_distance_after_burn(
        satrec_target, satrec_our, burn_time: datetime,
        dv_km_s: np.ndarray, tca_time: datetime,
        propagate_func: Callable[[object, datetime], tuple]
) -> Tuple[float, float]:
    """
    Belirli bir DeltaV (dv_km_s) manevrası yapıldığında, TCA anındaki
    yeni mesafeyi (miss distance) hesaplayan simülasyon fonksiyonudur.
    * SGP4 ile ateşleme anına git.
    * Hız vektörüne deltav ekle impulsive maneuver
    * yeni yörüngeyi Keplerian (poliastro) ile TCA anına ilerlet.
    """

    r_b, v_b = propagate_func(satrec_our, burn_time)
    r_b = np.array(r_b, dtype=float)
    v_b = np.array(v_b, dtype=float)

    # Poliastro sadece DV'nin delta etkisini hesaplamak için kullanılıyor.
    # Mutlak konum için SGP4 kullanılıyor; böylece LEO'daki J2/drag sapması baseline'ı bozmaz.
    orbit_base = rv_to_orbit(r_b, v_b, burn_time)
    orbit_dv = rv_to_orbit(r_b, v_b + np.array(dv_km_s, dtype=float), burn_time)
    r_kep_base = propagate_orbit_to(orbit_base, tca_time)
    r_kep_dv = propagate_orbit_to(orbit_dv, tca_time)
    delta_r = r_kep_dv - r_kep_base  # manevranın saf konum etkisi

    # SGP4 baseline: her iki uydu için gerçek TCA konumları
    r_our_sgp4, v_our_sgp4 = propagate_func(satrec_our, tca_time)
    r_other_tca, v_other_tca = propagate_func(satrec_target, tca_time)
    r_our_sgp4 = np.array(r_our_sgp4, dtype=float)
    r_other_tca = np.array(r_other_tca, dtype=float)
    v_our_sgp4 = np.array(v_our_sgp4, dtype=float)
    v_other_tca = np.array(v_other_tca, dtype=float)

    # Manevra sonrası konum = SGP4 konumu + Keplerian delta
    r_our_tca = r_our_sgp4 + delta_r
    miss = float(np.linalg.norm(r_other_tca - r_our_tca))

    # Bağıl hız: DV etkisi (~0.001 km/s) orbital hıza (~7 km/s) göre küçük, SGP4 hızları kullanılıyor
    rel_vel = float(np.linalg.norm(v_other_tca - v_our_sgp4))

    return miss, rel_vel


# Optimizasyon fonksiyonu
def find_minimal_dv(
        satrec_target,
        satrec_our,
        burn_time: datetime,
        tca_time: datetime,
        propagate_func: Callable[[object, datetime], tuple],
        target_miss_km: float = 2.0,  # hedeflenen güvenli mesafe (örn: 2 km)
        dv_bound_km_s: float = 0.001,  # izin verilen max deltav
        penalty_lambda: float = 1e6,  # ceza katsayısı
        verbose: bool = False
) -> ManeuverProposal:
    """
    Hedeflenen 'miss distance'ı sağlamak için gerekli en küçük DeltaV vektörünü bulur.
    Kısıtlanmamış optimizasyon yöntemini uygular.
    """

    # Amaç Fonksiyonu
    # Optimizer bu fonksiyonun döndürdüğü değeri sıfıra yaklaştırmaya çalışacak
    def obj_func(dv_flat):
        dv = np.array(dv_flat)  # anlık deltav değeri
        # simülasyonu çalıştır, manevra yapılırsa yeni mesafe ne olur ona bak
        miss, _ = compute_miss_distance_after_burn(
            satrec_target, satrec_our, burn_time, dv, tca_time, propagate_func
        )
        # Maliyet
        norm = float(np.linalg.norm(dv))

        # Ceza
        # Hedef mesafenin altındaysak devasa ceza uygula
        # Penalty = λ * max(0, Target - Miss) ^ 2
        # Eğer miss > target ise (güvendeyiz), max(0, negatif) -> 0 olur, ceza eklenmez.
        # Sadece yakıt maliyeti (norm) minimize edilir.
        penalty = penalty_lambda * max(0.0, (target_miss_km - miss)) ** 2
        return norm + penalty

    # Başlangıç tahmini (0,0,0) - Hiç manevra yapmama durumu
    x0 = np.zeros(3, dtype=float)
    # Arama sınırları (Bounds): Delta-V her eksende max 'dv_bound_km_s' olabilir.
    bounds = [(-dv_bound_km_s, dv_bound_km_s)] * 3

    # OPTIMIZASYON:
    try:
        # L-BFGS-B: Sınırlandırılmış (Box-constrained) optimizasyon algoritması
        res = minimize(
            obj_func,
            x0,
            bounds=bounds,
            method="L-BFGS-B",
            # ftol: Fonksiyon toleransı. Hassasiyet ile hız arasındaki denge.
            options={"ftol": 1e-9, "maxiter": 1000}
        )
    except Exception as e:
        return ManeuverProposal(
            dv_km_s=x0, dv_mag_km_s=0.0, dv_mag_m_s=0.0,
            burn_time=burn_time, predicted_tca=tca_time, predicted_miss_km=0.0,
            predicted_rel_vel_km_s=0.0, success=False, message=f"Optimizer Error: {str(e)}"
        )

    # optimizasyon tammalandı en iyi sonucu alalım
    dv_opt = np.array(res.x, dtype=float)
    # bu en iyi sonuçla son bir kez simülasyon yapıp kesin değerleri al
    miss_opt, relv_opt = compute_miss_distance_after_burn(
        satrec_target, satrec_our, burn_time, dv_opt, tca_time, propagate_func
    )

    # Bulunan mesafe hedefe (tolerans dahilinde) ulaştı mı?
    is_success = miss_opt >= (target_miss_km - 0.001)
    dv_mag_km_s = float(np.linalg.norm(dv_opt))

    # Mesaj seçimi is_success'e (gerçek karar kriterimiz) göre yapılır, scipy'nin
    # kendi res.success/res.message'ına DEĞİL. Neden: maliyet fonksiyonu
    # np.linalg.norm(dv) içerir, bu fonksiyon dv=0 noktasında türevsizdir
    # (köşeli/kink bir nokta). Hedef mesafe manevrasız (dv=0) zaten
    # sağlanıyorsa, optimum tam bu türevsiz noktada olur; L-BFGS-B'nin line
    # search'ü buradan ilerleyemeyip scipy'de "ABNORMAL: " gibi anlaşılmaz bir
    # dahili durum mesajıyla başarısız (res.success=False) dönebilir — ama
    # is_success ölçütümüze göre sonuç YİNE doğrudur (hedef zaten karşılanmış).
    # Bu durumu scipy'nin ham mesajını kullanıcıya sızdırmadan ayırt ediyoruz.
    if is_success:
        if dv_mag_km_s < 1e-9:
            message = "Manevra gerekli değil: mevcut mesafe hedefi zaten karşılıyor."
        else:
            message = "Optimum ateşleme bulundu."
    else:
        message = f"Hedefe ulaşılamadı (optimizer durumu: {res.message})"

    return ManeuverProposal(
        dv_km_s=dv_opt,
        dv_mag_km_s=dv_mag_km_s,
        dv_mag_m_s=dv_mag_km_s * 1000.0,
        burn_time=burn_time,
        predicted_tca=tca_time,
        predicted_miss_km=miss_opt,
        predicted_rel_vel_km_s=relv_opt,
        success=is_success,
        message=message
    )
