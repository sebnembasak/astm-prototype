"""
Ground Station Scheduling & Capacity Planning modülü için sabitler.
Büyüyen pocketqube/IoT uydu constellation operatörleri için tasarlandı:
büyüyen uydu sayısı (3 -> 80) ile sınırlı yer istasyonu kapasitesi arasındaki
çakışmaları analiz eder.
"""

# Geçiş (pass) hesaplama varsayılanları
DEFAULT_MIN_ELEVATION_DEG = 10.0  # Bu açının altı genelde link bütçesi için kullanılamaz sayılır
DEFAULT_STATION_ALT_KM = 0.0
DEFAULT_PASS_SCAN_STEP_SECONDS = 60  # AOS/LOS tarama adımı; ardışık örnekler arası lineer interpolasyonla saniyeye iyileştirilir.
# 60s, dakikalar süren geçiş pencereleri için zamanlama hassasiyeti açısından yeterlidir;
# kapasite planlama senaryolarında (80 uydu x birkaç istasyon x 24 saat) hesaplama maliyetini
# 30s'ye göre yarıya indirir.

# Kapasite planlama senaryo motoru varsayılanları
DEFAULT_SCENARIO_DURATION_HOURS = 24
SCENARIO_SATELLITE_COUNTS = [3, 10, 30, 80]
SCENARIO_STATION_COUNTS = [1, 2, 3]

# Hedeflenen referans yörünge profili: 525km güneş-senkron (SSO), büyüyen
# pocketqube/IoT constellation operatörlerinde tipik bir profil.
# Senaryo motoru, DB'deki TÜM TLE kataloğundan (stations/visual/debris/resource
# karışımı) rastgele/alfabetik seçim yapmak yerine, bu profile yakın GERÇEK
# nesneleri (TLE'den çıkarılan inklinasyon + irtifa) seçer — böylece "25/80
# uydu" senaryoları alakasız debris/ISS gibi nesnelerle değil, benzer yörünge
# geometrisine (dolayısıyla benzer geçiş süresi/sıklığı istatistiğine) sahip
# gerçek LEO/SSO nesneleriyle çalışır.
REFERENCE_ORBIT_ALTITUDE_KM = 525.0
REFERENCE_ORBIT_INCLINATION_DEG = 97.5

# Polar/SSO bandı: kutup yörüngeleri ~90°, SSO'lar irtifaya bağlı olarak
# ~97-99° arası sürünme (regresyon) inklinasyonu gerektirir; 90-100° aralığı
# bu ailenin tamamını (ve birkaç derece marjını) kapsar. 400-700km, tipik LEO
# SSO yer gözlem kuşağıdır (örn. Landsat ~705km, Sentinel-2 ~786km'nin biraz
# üstünde kalır ama SCD/CBERS/ALOS gibi çoğu SSO EO uydusu bu bantta).
ORBIT_FILTER_INCLINATION_RANGE_DEG = (90.0, 100.0)
ORBIT_FILTER_ALTITUDE_RANGE_KM = (400.0, 700.0)

# "Kaybı %50 azaltmak için kaç ek istasyon gerekir" geriye-doğru hesabı
TARGET_CAPACITY_LOSS_REDUCTION_PCT = 50.0
MAX_ADDITIONAL_STATIONS_SEARCH = 10

# Senaryolarda asıl yapılandırılan istasyon sayısının ötesine geçilince
# eklenecek aday istasyon havuzu (küresel kapsama çeşitliliği için dağıtılmış).
# Operatör merkezi Ankara kabul edildiği için ilk istasyon Ankara.
CANDIDATE_GROUND_STATIONS = [
    {"name": "Ankara", "lat_deg": 39.93, "lon_deg": 32.86},
    {"name": "Svalbard", "lat_deg": 78.23, "lon_deg": 15.39},
    {"name": "Punta Arenas", "lat_deg": -53.16, "lon_deg": -70.91},
    {"name": "Singapore", "lat_deg": 1.35, "lon_deg": 103.82},
    {"name": "Fairbanks", "lat_deg": 64.84, "lon_deg": -147.72},
    {"name": "Cape Town", "lat_deg": -33.92, "lon_deg": 18.42},
    {"name": "Wellington", "lat_deg": -41.29, "lon_deg": 174.78},
    {"name": "Reykjavik", "lat_deg": 64.13, "lon_deg": -21.82},
    {"name": "Quito", "lat_deg": -0.18, "lon_deg": -78.47},
    {"name": "Perth", "lat_deg": -31.95, "lon_deg": 115.86},
    {"name": "Toronto", "lat_deg": 43.65, "lon_deg": -79.38},
    {"name": "Tokyo", "lat_deg": 35.68, "lon_deg": 139.65},
]
