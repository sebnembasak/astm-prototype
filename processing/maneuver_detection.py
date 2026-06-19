from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict
import numpy as np

from processing.propagator import tle_to_satrec

# Dünya'nın standart yer çekimsel parametresi (km^3/s^2)
MU_EARTH = 398600.4418

# Eşikler
DV_THRESHOLD_M_S = 0.5       # Bu artık-hızın üzerinde ise manevra var sayılır
SMA_THRESHOLD_KM = 0.1        # Yarı büyük eksen farkı için "anlamlı" eşiği
INCL_THRESHOLD_DEG = 0.01     # Eğim farkı için "anlamlı" eşiği
ECC_THRESHOLD = 0.0001        # Eksantriklik farkı için "anlamlı" eşiği


@dataclass
class ManeuverDetection:
    """
    İki ardışık TLE epoch'u arasında tespit edilen manevra (varsa) için DTO.
    Sistemin diğer parçalarına (Database, API) gidecek olan veri yapısı.
    """
    epoch_before: str
    epoch_after: str
    dt_hours: float
    delta_semi_major_km: float
    delta_inclination_deg: float
    delta_eccentricity: float
    velocity_residual_m_s: float
    is_maneuver: bool
    maneuver_type: str
    confidence: float
    estimated_dv_m_s: float


def extract_orbital_elements(satrec) -> Dict[str, float]:
    """
    Bir Satrec nesnesinden, ardışık TLE'leri karşılaştırmak için gereken
    temel orbital elementleri çıkarır. Bu mean elementler (semi-major axis,
    inclination, eccentricity), faz/mean-anomaly'den bağımsızdır — yani iki
    TLE'nin epoch'ları arasında saatlerce/günlerce fark olsa bile doğrudan
    karşılaştırılabilirler.
    """
    n_rad_s = satrec.no_kozai / 60.0  # rad/dakika -> rad/saniye
    semi_major_km = (MU_EARTH / (n_rad_s ** 2)) ** (1.0 / 3.0)
    return {
        "semi_major_km": semi_major_km,
        "inclination_deg": np.degrees(satrec.inclo),
        "eccentricity": satrec.ecco,
    }


def _classify_maneuver_type(delta_a: float, delta_i: float, delta_e: float) -> str:
    significant = []
    if abs(delta_a) > SMA_THRESHOLD_KM:
        significant.append("ALTITUDE_CHANGE")
    if abs(delta_i) > INCL_THRESHOLD_DEG:
        significant.append("INCLINATION_CHANGE")
    if abs(delta_e) > ECC_THRESHOLD:
        significant.append("ECCENTRICITY_CHANGE")

    if len(significant) == 0:
        return "ORBIT_ADJUSTMENT"
    if len(significant) == 1:
        return significant[0]
    return "COMBINED"


def detect_maneuver(tle_before: dict, tle_after: dict) -> Optional[ManeuverDetection]:
    """
    Ardışık iki TLE arasında, mean orbital element farklarına dayalı bir
    ΔV tahminiyle manevra tespiti yapar.

    Yöntem (faz-bağımsız element farkı yöntemi):
        1. Her iki TLE'den de mean elementler çıkarılır: semi-major axis (a),
           inclination (i), eccentricity (e). Bunlar SGP4'ün mean-anomaly
           (faz) bileşeninden bağımsızdır.
        2. Δa, Δi, Δe hesaplanır.
        3. Δa'dan tanjantsal (in-track/irtifa) ΔV, Δi'den normal (düzlem
           değişimi) ΔV türetilir; toplam ΔV bu iki bileşenin vektörel
           toplamı (sqrt(dv_t^2 + dv_n^2)) olarak tahmin edilir.

    Not: İlk tasarımda (SGP4 ile epoch_after'a propagate edip ham hız
    vektörlerini karşılaştırmak) denenmişti, ancak iki TLE'nin mean-anomaly
    fazları arasındaki normal TLE-fit farkları, saatler/günler boyunca
    propagate edildiğinde km/s mertebesinde sahte "artık hız" üretiyordu
    (orbital hız ~7.6km/s olduğundan, küçük bir faz kayması bile devasa bir
    vektör farkına dönüşüyor). Mean element farkları bu sorunu ortadan
    kaldırır çünkü faz bilgisi hiç kullanılmaz.
    """
    try:
        epoch_before = datetime.fromisoformat(tle_before["epoch"])
        epoch_after = datetime.fromisoformat(tle_after["epoch"])
    except (KeyError, ValueError):
        return None

    dt_hours = (epoch_after - epoch_before).total_seconds() / 3600.0
    if dt_hours <= 0:
        return None

    try:
        satrec_before = tle_to_satrec(tle_before["line1"], tle_before["line2"])
        satrec_after = tle_to_satrec(tle_after["line1"], tle_after["line2"])
        elements_before = extract_orbital_elements(satrec_before)
        elements_after = extract_orbital_elements(satrec_after)
    except Exception:
        return None

    a_before = elements_before["semi_major_km"]
    delta_a = elements_after["semi_major_km"] - a_before
    delta_i = elements_after["inclination_deg"] - elements_before["inclination_deg"]
    delta_e = elements_after["eccentricity"] - elements_before["eccentricity"]

    # Dairesel yörünge varsayımıyla referans hız (km/s)
    v_circular = np.sqrt(MU_EARTH / a_before)

    # Tanjantsal (irtifa) ΔV: dv = (v/2) * (Δa/a)
    dv_tangential = 0.5 * v_circular * abs(delta_a) / a_before
    # Normal (düzlem değişimi) ΔV: dv = v * sin(Δi)
    dv_normal = v_circular * np.sin(np.radians(abs(delta_i)))

    velocity_residual_m_s = float(np.sqrt(dv_tangential ** 2 + dv_normal ** 2)) * 1000.0

    is_maneuver = velocity_residual_m_s > DV_THRESHOLD_M_S
    maneuver_type = _classify_maneuver_type(delta_a, delta_i, delta_e) if is_maneuver else "NONE"
    confidence = min(1.0, velocity_residual_m_s / (3 * DV_THRESHOLD_M_S))

    return ManeuverDetection(
        epoch_before=tle_before["epoch"],
        epoch_after=tle_after["epoch"],
        dt_hours=dt_hours,
        delta_semi_major_km=delta_a,
        delta_inclination_deg=delta_i,
        delta_eccentricity=delta_e,
        velocity_residual_m_s=velocity_residual_m_s,
        is_maneuver=is_maneuver,
        maneuver_type=maneuver_type,
        confidence=confidence,
        estimated_dv_m_s=velocity_residual_m_s,
    )
