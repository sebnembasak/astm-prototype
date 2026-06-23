# Bilinen Sınırlamalar (2026-06 itibarıyla)

Projenin bilimsel doğruluğunu şeffaf şekilde belgelemek amacıyla, kod tabanı genelinde bir tarama yapıldı.

## Çarpışma Tarama — Broad-Phase Budama Zaman Boşluğu

`service/conjunction_service.py:42-67`'deki KD-Tree budama, tüm uyduların SADECE tarama anındaki (t0) konumlarına bakarak 300km içindeki çiftleri aday olarak seçiyor. Ardından her aday çift için `processing/conjunction.py`'deki analitik TCA çözücü, t0'daki konum/hızdan lineer ekstrapolasyonla **2 saatlik pencere içinde herhangi bir anda** en yakın geçişi arıyor (`ANALYTIC_WINDOW = 7200.0`).

**Sorun:** Eğer iki uydu t0 anında 300km'den uzaktaysa ama 2 saat içinde gerçekten yakınlaşacaksa, bu çift budama aşamasında hiç seçilmiyor ve analitik/SGP4 aşamasına asla ulaşmıyor. LEO'da bağıl hız tipik olarak 1-15 km/s; 300km'lik mesafe bu hızlarla 20 saniye - 5 dakika içinde kapanır. Yani sistem pratikte sadece TCA'sı tarama anına ±birkaç dakika içinde olan çiftleri yakalayabiliyor — "2 saatlik pencere" kapsamı büyük ölçüde nominal kalıyor. En yüksek bağıl hızlı (dolayısıyla en yüksek enerjili/en riskli) yakınlaşmalar bu etkiden en çok etkilenen senaryolardır, çünkü 300km'yi en hızlı geçen onlardır.

**Önerilen düzeltme (henüz uygulanmadı):** Tek snapshot yerine, 2 saatlik pencereyi birkaç dakikalık aralıklarla (örn. 5-10 dk) örnekleyip her örnekte KD-Tree budaması çalıştırmak, bulunan aday çiftlerin birleşimini narrow-phase'e göndermek. Bu, mevcut analitik TCA çözücüyü (`analytic_tca_and_miss`) değiştirmeden, sadece hangi çiftlerin ona ulaştığını düzeltir.

## Kenetli Nesnelerde Epoch Tutarsızlığı Artefaktı

Çin Uzay İstasyonu (CSS) gibi fiziksel olarak kenetli/dokunmuş modül grupları (örn. CSS-TIANHE, CSS-MENGTIAN, CSS-WENTIAN, TIANZHOU-10, SHENZHOU-23), Celestrak kataloğunda her modül için ayrı bir NORAD ID ile listelenir, ancak Celestrak bu modüllere genellikle istasyonun TEK bir takip çözümünü (aynı inklinasyon, RAAN, eksantriklik, argüman, mean anomaly) kopyalar. Aynı kenetli grup içindeki TLE'lerin **epoch'u farklı zamanlarda güncellenebilir** (gözlemlenen örnekte iki alt-küme arası ~16.9 saatlik epoch farkı).

**Sorun:** `processing/conjunction.py`'deki çarpışma tarama, iki nesneyi kendi TLE epoch'larından "şimdi"ye SGP4 ile ayrı ayrı yayıyor. Aynı epoch'lu kenetli nesneler arasında mesafe doğru şekilde ~0 km çıkar (DOCKING olarak sınıflandırılır). Ancak FARKLI epoch'lu iki alt-küme arasındaki herhangi bir çift karşılaştırıldığında, gösterilen mesafe (gözlemlenen örnekte 2.8364 km, sabit/tekrarlayan) **gerçek fiziksel ayrışmayı değil, iki epoch arasındaki SGP4 ekstrapolasyon farkının birikimini** yansıtır — nesneler gerçekte hâlâ kenetli/dokunmuş olabilir.

**Dashboard etkisi:** Bu durumda risk skoru `processing/conjunction.py`'deki mesafe-tabanlı lineer interpolasyon formülüyle hesaplandığından, 2.8364 km gibi bir mesafe `CRITICAL_DISTANCE_KM=10.0` eşiğinin altında kaldığı için **"%100 risk" (skor=1.0, COLLISION)** olarak etiketlenebilir. Bu gerçek bir çarpışma riski değil, epoch farkından kaynaklanan yanıltıcı bir alarmdır. Aynı istasyonun farklı modülleri arasında yüksek risk skoru görüldüğünde, önce ilgili TLE'lerin epoch'larının (`raw_tles.epoch`) birbirine yakın olup olmadığı kontrol edilmelidir.

**Kapsam dışı bırakılma nedeni:** Bu, veri kaynağının (Celestrak) doğasından kaynaklanan bir özellik. Düzeltmek için kenetli/aynı-istasyon nesne gruplarını tespit edip (örn. aynı yörünge elemanlarına sahip nesneleri kümeleyerek) epoch farkı büyük olduğunda alarm bastırma/uyarı eklemek gerekir. İlerleyen versiyonlarda bununla ilgili bir çalışma yapılacaktır.

## Eşik Değerleri

Aşağıdaki sabitler matematiksel/fiziksel olarak geçersiz değildir, ancak akademik/endüstriyel bir kaynağa (örn. ITU-R, CARA, NASA DAS) dayanan eşiklerimiz arasında da değillerdir. Tahmine dayanmaktadırlar bu nedenle de endüstri standardı olarak sunulmamalıdır:

- **Çarpışma risk eşikleri** (`processing/conjunction.py`): `CRITICAL_DISTANCE_KM=10.0`, `MONITORING_THRESHOLD_KM=75.0` — risk skoru gerçek kovaryans tabanlı çarpışma olasılığı (Pc) değil, mesafeye lineer interpolasyon.
- **Sönümlenme (decay) riski** (`service/ssa_service.py`): irtifa < 350km VE BSTAR > 0.0005 ikili kuralı — gerçek decay/lifetime tahmini atmosferik yoğunluk modelleri gerektirir, bu varsayımsal bir değerdir.
- **Manevra tespiti eşikleri** (`processing/maneuver_detection.py`): `DV_THRESHOLD_M_S=0.5`, `SMA_THRESHOLD_KM=0.1`, `INCL_THRESHOLD_DEG=0.01`, `ECC_THRESHOLD=0.0001` — TLE fit gürültü mertebesiyle istatistiksel olarak kalibre edilmemiş.
- **ML hiperparametreleri** (`service/ssa_service.py`): GMM `n_components=5`, IsolationForest/LOF `contamination=0.03` — BIC/AIC veya veri-temelli bir seçim değil, sabit değer.

ΔV formülleri (tanjantsal/normal bileşenler, dairesel yörünge yaklaşımı) ve optimizasyon yöntemleri (L-BFGS-B, scipy `minimize_scalar(method='bounded')`) fiziksel/matematiksel olarak standart ve doğrudur. Yukarıdaki liste yalnızca kaynaksız SABİT DEĞERLERİ kapsar, yöntemlerin kendisini değil.
