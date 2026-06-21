# Bilinen Sınırlamalar (2026-06-21 itibarıyla)

Projenin bilimsel doğruluğunu şeffaf şekilde belgelemek amacıyla, kod tabanı genelinde bir tarama yapıldı. En önemli bulgu aşağıda; diğer (orta/düşük ciddiyetli) sezgisel eşik değerleri için bkz. ilgili modüllerin kodundaki yorumlar (`processing/conjunction.py`, `processing/maneuver_detection.py`, `service/ssa_service.py`) — bunların hiçbiri akademik/endüstriyel bir kaynağa dayanmaz, mühendislik tahminidir ve öyle sunulmalıdır.

## Çarpışma Tarama (Conjunction Screening) — Broad-Phase Budama Zaman Boşluğu

**Ciddiyet: Yüksek.** `service/conjunction_service.py:42-67`'deki KD-Tree budama (broad phase), tüm uyduların SADECE tarama anındaki (t0) konumlarına bakarak 300km içindeki çiftleri aday olarak seçiyor. Ardından her aday çift için `processing/conjunction.py`'deki analitik TCA çözücü, t0'daki konum/hızdan lineer ekstrapolasyonla **2 saatlik pencere içinde herhangi bir anda** en yakın geçişi arıyor (`ANALYTIC_WINDOW = 7200.0`).

**Sorun:** Eğer iki uydu t0 anında 300km'den uzaktaysa ama 2 saat içinde gerçekten yakınlaşacaksa, bu çift budama aşamasında hiç seçilmiyor ve analitik/SGP4 aşamasına asla ulaşmıyor. LEO'da bağıl hız tipik olarak 1-15 km/s; 300km'lik mesafe bu hızlarla 20 saniye - 5 dakika içinde kapanır. Yani sistem pratikte sadece TCA'sı tarama anına ±birkaç dakika içinde olan çiftleri yakalayabiliyor — "2 saatlik pencere" kapsamı büyük ölçüde nominal kalıyor. En yüksek bağıl hızlı (dolayısıyla en yüksek enerjili/en riskli) yakınlaşmalar bu etkiden en çok etkilenen senaryolardır, çünkü 300km'yi en hızlı geçen onlardır.

**Önerilen düzeltme (henüz uygulanmadı):** Tek snapshot yerine, 2 saatlik pencereyi birkaç dakikalık aralıklarla (örn. 5-10 dk) örnekleyip her örnekte KD-Tree budaması çalıştırmak, bulunan aday çiftlerin birleşimini (union) narrow-phase'e göndermek — gerçek SSA sistemlerinde (örn. CARA) kullanılan pratik bir yaklaşım. Bu, mevcut analitik TCA çözücüyü (`analytic_tca_and_miss`) değiştirmeden, sadece hangi çiftlerin ona ulaştığını düzeltir.

**Kapsam dışı bırakılma nedeni:** Bu bir mimari değişiklik gerektirir (performans etkisi: ~12-24x broad-phase çağrısı, ama narrow-phase maliyeti değişmez); şu an için sadece belgeleniyor, koda dokunulmadı.

## Kaynaksız Sezgisel Eşik Değerleri (Ciddiyet: Orta/Düşük)

Aşağıdaki sabitler matematiksel/fiziksel olarak geçersiz değildir, ancak akademik/endüstriyel bir kaynağa (örn. ITU-R, CARA, NASA DAS) dayanmaz — mühendislik tahminidir, "doğrulanmış endüstri standardı" olarak sunulmamalıdır:

- **Çarpışma risk eşikleri** (`processing/conjunction.py`): `CRITICAL_DISTANCE_KM=10.0`, `MONITORING_THRESHOLD_KM=75.0` — risk skoru gerçek kovaryans tabanlı çarpışma olasılığı (Pc) değil, mesafeye lineer interpolasyon.
- **Sönümlenme (decay) riski** (`service/ssa_service.py`): irtifa < 350km VE BSTAR > 0.0005 ikili kuralı — gerçek decay/lifetime tahmini atmosferik yoğunluk modelleri gerektirir, bu basit bir sezgisel kısayoldur.
- **Manevra tespiti eşikleri** (`processing/maneuver_detection.py`): `DV_THRESHOLD_M_S=0.5`, `SMA_THRESHOLD_KM=0.1`, `INCL_THRESHOLD_DEG=0.01`, `ECC_THRESHOLD=0.0001` — TLE fit gürültü mertebesiyle istatistiksel olarak kalibre edilmemiş.
- **ML hiperparametreleri** (`service/ssa_service.py`): GMM `n_components=5`, IsolationForest/LOF `contamination=0.03` — BIC/AIC veya veri-temelli bir seçim değil, sabit değer.

ΔV formülleri (tanjantsal/normal bileşenler, dairesel yörünge yaklaşımı) ve optimizasyon yöntemleri (L-BFGS-B, scipy `minimize_scalar(method='bounded')`) fiziksel/matematiksel olarak standart ve doğrudur — yukarıdaki liste yalnızca kaynaksız SABİT DEĞERLERİ kapsar, yöntemlerin kendisini değil.
