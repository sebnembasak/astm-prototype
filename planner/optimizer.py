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
        propagate_func: Callable[[object, datetime], np.ndarray]
) -> Tuple[float, float]:
    """
    Belirli bir DeltaV (dv_km_s) manevrası yapıldığında, TCA anındaki
    yeni mesafeyi (miss distance) hesaplayan simülasyon fonksiyonudur.
    * SGP4 ile ateşleme anına git.
    * Hız vektörüne deltav ekle impulsive maneuver
    * yeni yörüngeyi Keplerian (poliastro) ile TCA anına ilerlet.
    """

    # ateşleme anındaki mevcut konum ve hızın bulunması
    # hız vektörünü bulmak için 1 saniye arayla iki konum alıp farkını alıyoruz (basit türev)
    # Not: SGP4 kütüphanesinin kendi hız çıktısı da kullanılabilir ama bu yöntem genel geçerdir.
    r_b = np.array(propagate_func(satrec_our, burn_time), dtype=float)
    r_b1 = np.array(propagate_func(satrec_our, burn_time + timedelta(seconds=1)), dtype=float)
    v_b = (r_b1 - r_b) / 1.0

    # Manevra v' = v + deltav işlemi
    v_new = v_b + np.array(dv_km_s, dtype=float)
    orbit_new = rv_to_orbit(r_b, v_new, burn_time)
    r_our_tca = propagate_orbit_to(orbit_new, tca_time)
    # risk oluşturan diğer uydunun TCA anındaki konumunu bul
    # dieğr uydu manevra yapmadığı için orijinal SGP4 propagator kullanılır
    r_other_tca = np.array(propagate_func(satrec_target, tca_time), dtype=float)

    # iki konum arasındaki öklid mesafesini (miss distance) hesapla
    miss = float(np.linalg.norm(r_other_tca - r_our_tca))

    # Bağıl hız hesabı
    # TCAdan 1 sn sonrasına bakarak hız vektörlerini tahmin et
    dt = 1.0
    r_our_tca_f = propagate_orbit_to(orbit_new, tca_time + timedelta(seconds=dt))
    r_other_tca_f = np.array(propagate_func(satrec_target, tca_time + timedelta(seconds=dt)), dtype=float)
    rel_vel = float(np.linalg.norm((r_other_tca_f - r_other_tca) - (r_our_tca_f - r_our_tca)) / dt)

    return miss, rel_vel


# Optimizasyon fonksiyonu
def find_minimal_dv(
        satrec_target,
        satrec_our,
        burn_time: datetime,
        tca_time: datetime,
        propagate_func: Callable[[object, datetime], np.ndarray],
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

    return ManeuverProposal(
        dv_km_s=dv_opt,
        dv_mag_km_s=float(np.linalg.norm(dv_opt)),
        dv_mag_m_s=float(np.linalg.norm(dv_opt) * 1000.0),
        burn_time=burn_time,
        predicted_tca=tca_time,
        predicted_miss_km=miss_opt,
        predicted_rel_vel_km_s=relv_opt,
        success=is_success,
        message="Optimization finished" if res.success else str(res.message)
    )
