from typing import Tuple, Optional
from datetime import datetime, timedelta
import numpy as np
from scipy.optimize import minimize_scalar
from dataclasses import dataclass


@dataclass
class Conjunction:
    """
    Tespit edilen bir yakınlaşma olayının özet verisi.
    Sistemin diğer parçalarına (Database, API) gidecek olan DTO.
    """
    sat1: int  # 1. uydu norad id
    sat2: int  # 2. uydu norad id
    tca: datetime  # time of closest approach
    miss_distance_km: float  # 2 obje arası beklenen en kısa mesafe km cinsinden
    rel_velocity_km_s: float  # yaklaşma anı bağıl hız km/s
    score: float  # 0.0, 1.0 arası risk skoru
    event_type: str = "COLLISION"  # 'COLLISION' (Çarpışma) veya 'DOCKING' (Kenetlenme)


def analytic_tca_and_miss(r1, v1, r2, v2, epoch) -> Tuple[float, float]:
    """
    Lineer Varsayım ile TCA Tahmini.
    Uyduların kısa bir süre için doğrusal (linear) hareket ettiği varsayılarak,
    en yakın geçiş zamanı (t*) analitik bir formülle hesaplanır.
    Bu yöntem çok hızlıdır ancak sadece "ilk eleme" (filter) için kullanılır.
    Girdi:
        r1, v1: 1. Uydunun konum ve hız vektörleri
        r2, v2: 2. Uydunun konum ve hız vektörleri
    Çıktı:
        tstar: Referans zamandan (epoch) kaç saniye sonra en yakın geçiş olacak?
        miss: O andaki tahmini mesafe (km)
    """
    r = r2 - r1
    v = v2 - v1
    vv = np.dot(v, v)

    if vv < 1e-12:  # # Eğer bağıl hız 0 ise (uydular paralel ve aynı hızda gidiyorsa)
        return 0.0, float(np.linalg.norm(r))

    # t* = - (r . v) / (v . v)
    # Bu formül türev alınarak minimum mesafenin olduğu zamanı verir.
    tstar = - np.dot(r, v) / vv

    # o andaki tahmini konum farkı: r(t) = r0 + v * t
    r_t = r + v * tstar
    miss = np.linalg.norm(r_t)  # Öklid mesafesi
    return float(tstar), float(miss)


# Refine Aşaması
def refine_tca_with_propagator(satrec1, satrec2, epoch, t_est_seconds, propagate_func, search_radius=600.0):
    """
    Lineer varsayımı düzeltmek için SGP4 ile hassas arama.
    Analitik yöntemle bulunan t* zamanı etrafında,
    gerçek yörünge mekaniğini (SGP4) kullanarak minimum mesafeyi arar.

    Neden Gerekli?
    Yörüngeler düz çizgi değil, elipstir. Lineer yöntem 5-10 saniyelik hatalar yapabilir.
    Raporda bahsedilen 5 dakikalık farkın bir kısmı buradan gelir.
    """

    # Cost Function minimize edilecek hedef fonksiyon
    def dist_sq_offset(dt_offset):
        try:
            t = epoch + timedelta(seconds=(t_est_seconds + dt_offset))
            r1, _ = propagate_func(satrec1, t)
            r2, _ = propagate_func(satrec2, t)
            # Karekök işlemi maliyetli olduğu için optimizasyonda kare kullanılır
            return float(np.sum((r2 - r1) ** 2))
        except Exception:
            return 1e9  # Hata durumunda çok uzak mesafe döndür ki orası seçilmesin

    # minimize_scalar optimizasyon tekniği kullanımı
    # Arama Aralığı: tahmin edilen zamanın +/- 600 saniye (10 dk) çevresi
    res = minimize_scalar(dist_sq_offset, bounds=(-search_radius, search_radius), method='bounded',
                          options={'xatol': 0.01})  # 0.01 saniye hassasiyet

    tca = epoch + timedelta(seconds=(t_est_seconds + res.x))

    try:
        r1, v1 = propagate_func(satrec1, tca)
        r2, v2 = propagate_func(satrec2, tca)
        miss = float(np.linalg.norm(r2 - r1))
        rel_vel = float(np.linalg.norm(v2 - v1))
    except Exception:
        return tca, 99999.9, 0.0

    return tca, miss, rel_vel


# İş Akışı
def compute_conjunction_for_pair(satrec1, satrec2, ref_epoch, r1, v1, r2, v2, propagate_func,
                                 analytic_window_sec=7200.0,
                                 sat1_name: str = "", sat2_name: str = "") -> Optional[Conjunction]:
    """
    İki uydu arasındaki çarpışma riskini analiz eden ana fonksiyon.
    Algoritma:
        1. Hızlı Analitik Filtre: Eğer lineer hesap uyduları çok uzak bulursa işlemi bitir.
        2. Hassas İyileştirme: Yakınsa, SGP4 ve Optimizasyon ile kesin zamanı/mesafeyi bul.
        3. Skorlama: Mesafeye göre risk puanı ata.
        4. Sınıflandırma: Çarpışma mı yoksa Kenetlenme (Docking) mi?
    """
    try:
        # İlk adım lineer tahmin
        tstar, miss = analytic_tca_and_miss(r1, v1, r2, v2, ref_epoch)
        MONITORING_THRESHOLD_KM = 75.0  # Bu mesafenin altı izlenmeye değer
        CRITICAL_DISTANCE_KM = 10.0  # Bu mesafe "Kırmızı Alarm"

        # Analitik filtreleme, optimizasyon, pruning
        # Eğer en yakın geçiş çok ilerideyse (>2 saat) veya mesafe çok büyükse (>150km)
        # detaylı işlem yapma, boş yere kaynak harcama
        if abs(tstar) > analytic_window_sec or miss > (MONITORING_THRESHOLD_KM * 2):
            return Conjunction(
                sat1=getattr(satrec1, 'satnum', -1),
                sat2=getattr(satrec2, 'satnum', -1),
                tca=ref_epoch + timedelta(seconds=tstar),
                miss_distance_km=float(miss),
                rel_velocity_km_s=float(np.linalg.norm(v2 - v1)),
                score=0.0,
                event_type="COLLISION"
            )

        # Eğer potansiyel risk varsa, hassas hesaplama (refinement) yap
        tca, miss_refined, rel_vel = refine_tca_with_propagator(
            satrec1, satrec2, ref_epoch, tstar, propagate_func, search_radius=600.0
        )

        # Riski skorla
        if miss_refined > MONITORING_THRESHOLD_KM:
            normalized_score = 0.0
        elif miss_refined <= CRITICAL_DISTANCE_KM:
            normalized_score = 1.0
        else:
            normalized_score = (MONITORING_THRESHOLD_KM - miss_refined) / (
                        MONITORING_THRESHOLD_KM - CRITICAL_DISTANCE_KM)
            normalized_score = max(0.0, min(1.0, normalized_score))

        # DOCKING (Kenetlenme) Analizi
        # ── Dört kategori — bağıl hız (rel_vel) birincil ayraç ─────────────────
        #
        # DOCKING     : miss < 5 km  VE vel < 0.05 km/s
        #               Fiziksel temas / randevu (ISS, CSS modülleri).
        #               TLE doğruluk sınırı ~1-2 km olduğundan 5 km eşiği gerekli.
        #
        # FORMATION   : miss < 15 km VE vel < 0.05 km/s (docking değil)
        #               Aynı konstellasyondan eş yörüngeli aktif uydular.
        #               Gerçek çarpışma riski ihmal edilebilir.
        #
        # GEO_NEIGHBOR: FORMATION kriterlerini karşılayan ama her iki nesne de
        #               GEO yörüngesinde olanlar. Bunlar slot komşularıdır; ne
        #               çarpışma riski ne de gerçek formasyon uçuşu söz konusudur.
        #
        # COLLISION   : diğer her şey.
        #
        # ── Kural 1: GEO Slot Komşuluğu ──────────────────────────────────────
        # GEO yörüngesi iki şartı aynı anda karşılamalıdır:
        #
        #  (a) Düşük ortalama hareket — GEO dönme süresi ~1436 dk →
        #      n ≈ 0.00437 rad/min. %50 marjla eşik 0.00656 rad/min.
        #
        #  (b) Neredeyse dairesel yörünge (eksantriklik < 0.01) —
        #      PROBA-3 gibi HEO uydular düşük n'e sahip olsa da
        #      eksantrikliği ~0.8'e ulaşır; bunlar GEO değil, gerçek
        #      formasyon uçuşu yapan aktif uyduLardır.
        #      Yalnızca (a) PROBA-3'ü yanlışlıkla GEO_NEIGHBOR yapar;
        #      (b) bu durumu engeller.
        _GEO_N_THRESHOLD = 1.5 * 2 * np.pi / 1436.0  # rad/min
        _GEO_ECC_MAX     = 0.01                        # GEO daireseldir; HEO hariç
        sat1_is_geo = (float(satrec1.no_kozai) < _GEO_N_THRESHOLD
                       and float(satrec1.ecco) < _GEO_ECC_MAX)
        sat2_is_geo = (float(satrec2.no_kozai) < _GEO_N_THRESHOLD
                       and float(satrec2.ecco) < _GEO_ECC_MAX)
        both_geo    = sat1_is_geo and sat2_is_geo

        # ── Kural 2: Aktif Olmayan Nesne Kontrolü ────────────────────────────
        # Formasyon uçuşu tanımı gereği koordineli, aktif nesneler arasında olur.
        # Uzay çöpü (debris), roket gövdesi (rocket body) veya pasifleşmiş nesne
        # yavaş bağıl hızla yakınlaşıyorsa bu koordineli bir oluşum değil, gerçek
        # bir yakın geçiş tehlikesidir — COLLISION olarak sınıflandırılır.
        # Tespit yöntemi: Celestrak/NORAD adlandırma kuralı; bu nesneler adında
        # aşağıdaki anahtar kelimeleri içerir:
        #   DEB   → space debris parçası
        #   R/B   → roket gövdesi (rocket body)
        #   ROCKET / STAGE / BODY → fırlatma sistemi kalıntısı
        _INACTIVE_KW = ("DEB", "R/B", "ROCKET", "STAGE", "BODY")
        n1 = sat1_name.upper()
        n2 = sat2_name.upper()
        either_inactive = any(kw in n1 or kw in n2 for kw in _INACTIVE_KW)

        # FORMATION hız eşiği 0.10 km/s (100 m/s): 0.05 km/s çok dar kalıyordu;
        # LEMUR-2 gibi aynı konstellasyondan iki uydunun 66 m/s bağıl hızla
        # karşılaşması COLLISION'a düşüyordu. 100 m/s eşiği bu borderline
        # konstellasyon çiftlerini FORMATION'a çeker, cross-inclination (>150 m/s)
        # karşılaşmaları COLLISION olarak doğru kalır.
        _FORMATION_VEL = 0.10  # km/s
        is_docking   = (miss_refined <  5.0) and (rel_vel < _FORMATION_VEL)
        is_formation = (miss_refined < 15.0) and (rel_vel < _FORMATION_VEL) and not is_docking

        if is_docking:
            final_event_type = "DOCKING"
            normalized_score = 1.0
        elif is_formation and either_inactive:
            # Aktif olmayan bir nesne FORMATION eşiğini karşılasa bile
            # koordineli formasyon uçuşu mümkün değildir → gerçek risk.
            final_event_type = "COLLISION"
        elif is_formation and both_geo:
            # İki GEO nesnesi birbirine 15 km içinde ve hemen hemen
            # aynı hızda → slot komşuları, alarm değil.
            final_event_type = "GEO_NEIGHBOR"
        elif is_formation:
            final_event_type = "FORMATION"
        else:
            final_event_type = "COLLISION"

        return Conjunction(
            sat1=getattr(satrec1, 'satnum', -1),
            sat2=getattr(satrec2, 'satnum', -1),
            tca=tca,
            miss_distance_km=miss_refined,
            rel_velocity_km_s=rel_vel,
            score=normalized_score,
            event_type=final_event_type
        )
    except Exception as e:
        # Herhangi bir beklenmedik hatada none dön, service katmanı bunu loglayacak
        print(f"Calculation error: {e}")
        return None