# ASTM-PROTOTYPE: Uzay Trafik Kontrol ve Çarpışma Yönetimi

**<em>Bu proje Türkiye Uzay Ajansı'nın Milli Uzay Programı'nda belirtilen 'Uzay Nesnelerinin Yerden Gözlemi ve Takibi' (Hedef 7) stratejisi doğrultusunda; ülkemizin uzay trafik yönetimi alanındaki yazılım kabiliyetini artırmak, yerli ve milli karar destek mekanizmaları geliştirmek amacıyla tasarlanmış bir Ar-Ge prototipidir.</em>**

Proje; Alçak Dünya Yörüngesi (LEO) uydularının çarpışma risklerini (Conjunction Assessment) yönetmek ve optimal kaçınma manevralarını planlar. 
Backend, hesaplama yoğunluklu uzay mekaniği görevlerini yöneten FastAPI üzerine kurulmuştur. 
Frontend ise etkileşimli bir Dashboard, Uydu Kataloğu ve Canlı Harita Görselleştirmesi sunan modern bir HTML/JavaScript arayüzüdür.

![ASTM](dashboard/assets/img/sat2.jpg "Main")


## Temel Özellikler

### Backend

* **Çarpışma Tarama (Conjunction Screening):**
    * **Broad Phase:** Uyduları coğrafi olarak gruplayarak (KD-Tree ile O(N logN)) potansiyel çarpışma adaylarını hızla eler/budar (`processing/pruner.py`).
    * **Narrow Phase:** Kalan aday çiftler için SGP4 modeli ve Skalar Optimizasyon (Bisection/Brent) kullanarak En Yakın Geçiş Zamanı (TCA) ve En Kısa Mesafe'yi (Miss Distance) hassas bir şekilde hesaplar.
    * **Bilinen sınırlama (bkz. [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)):** Broad-phase budama TEK bir anlık görüntüde (tarama anı, t0) çalışır; 2 saatlik analiz penceresi içinde TCA'sı t0'a göre uzak olan (ama t0 anında 300km'den fazla mesafede olan) çiftler budama aşamasını hiç geçemeyebilir. Yüksek bağıl hızlı (dolayısıyla en riskli) yakınlaşmalar bu etkiden en çok etkilenenlerdir.
* **Manevra Optimizasyonu (Maneuver Optimization):**
    * Çarpışma riskini azaltmak için gereken minimum DeltaV (yakıt maliyeti) vektörünü bulmak için kısıtlanmış L-BFGS-B (Box-Constrained Broyden–Fletcher–Goldfarb–Shanno) algoritmasını kullanır.
    * Manevra, TCA'dan belirli bir süre önce (örneğin 1 saat) yapılan anlık (impulsive) bir hız değişimi olarak modellenir.
* **Veri Yönetimi:** SQLite veritabanı kullanarak TLE verilerini ve çarpışma uyarılarını kaydeder.

### Yapay Zeka ve SSA (Uzay Durum Farkındalığı) Modülü
Sistem, ham TLE verilerini kullanarak uyduların davranışlarını ve gizli görev parametrelerini analiz eden bir Makine Öğrenmesi (ML) katmanı içerir:

* **Görev Sınıflandırma (Calibrated Random Forest):** 7.500+ uyduluk UCS veri seti ile eğitilen model; eğim, basıklık, periyot, perije ve apoje verilerinden (Kepler'in 3. Kanunu ile türetilmiş) uydunun kullanım amacını ~%90 doğrulukla tahmin eder. Ham olasılık çıktıları `CalibratedClassifierCV` (sigmoid, çapraz doğrulamalı) ile kalibre edilerek güven (confidence) skorlarının gerçek isabet oranını yansıtması sağlanır.
* **Anomali Tespiti (Isolation Forest + Local Outlier Factor Ensemble):** Isolation Forest global/eksen-hizalı aykırılıkları, Local Outlier Factor (LOF) ise yoğun bir kümenin içindeki lokal aykırılıkları yakalar; iki yöntemden biri anomali derse nesne işaretlenir (OR mantığı, kaçırılan gerçek bir anomalinin maliyetinin fazladan bir uyarıdan daha yüksek olduğu prensibiyle).
* **Yörünge Rejimi Kümeleme (Gaussian Mixture Model):** Uyduları fiziksel özelliklerine göre LEO, MEO, GEO, HEO ve VLEO olarak 5 ana kümede gruplandırır; K-Means'in sert (hard) küme sınırları yerine olasılıksal (soft) üyelik ataması kullanır.
* **Manevra Tespiti (Mean-Element Farkı):** `tle_history` tablosunda arşivlenen ardışık TLE çiftlerinden mean orbital elementleri (yarı-büyük eksen, eğim, dış merkezlik) faz/mean-anomaly bilgisinden bağımsız olarak çıkarır; aradaki farktan tanjantsal ve normal ΔV bileşenlerini fizik formülüyle (dairesel yörünge yaklaşımı) türeterek İrtifa Değişimi, Düzlem Değişimi, Eksantriklik Değişimi veya Kombine manevra tiplerini sınıflandırır.
* **Sönümlenme (Decay) Analizi:** BSTAR sürüklenme katsayısı ve irtifa verilerini hibritleyerek uydunun atmosfere düşme riskini (Düşük/Orta/Yüksek) hesaplar.
* **Teknik Performans Raporu:** Modelin başarı metriklerini (Accuracy, F1-Score, ROC-AUC, Confusion Matrix) radar grafikler ve ısı haritaları ile anlık olarak sunar.

### Yer İstasyonu Planlama & Kapasite Analizi (Ground Station Scheduling)
Büyüyen pocketqube/IoT uydu constellation operatörleri için, sınırlı yer istasyonu sayısıyla artan uydu sayısı arasındaki operasyonel darboğazı modeller:

* **AOS/LOS Hesabı:** Mevcut SGP4 propagasyon altyapısını (`processing/propagator.py`) yer istasyonuna göre topocentric elevasyon açısına (AltAz dönüşümü) genişletir; bir uydunun istasyon üzerinden geçiş penceresini (Acquisition/Loss of Signal) ve maksimum elevasyonunu hesaplar.
* **Çakışma Tespiti:** Aynı istasyonda zaman içinde örtüşen geçiş pencerelerini ve çakışma oranını tespit eder.
* **İstasyon-Bağımlı EFT Greedy Çizelgeleme:** Her geçiş penceresi kendi istasyonunun geometrisine bağlı olduğundan, çizelgeleme istasyon başına bağımsız bir tek-kaynak (single-resource) problemi olarak Earliest-Finish-Time greedy algoritmasıyla çözülür (tek kaynak için ispatlanmış optimal).
* **Kapasite Planlama Senaryoları:** 525km/97.5° SSO referans yörünge profiline yakın **gerçek** Celestrak nesneleri (`tle_service.get_satellites_by_orbit_profile`, debris/ISS gibi alakasız yörünge aileleri elenerek) kullanılarak, 3/10/30/80 uydu × 1/2/3 istasyon ızgarasında kapasite kaybını (kaçırılan geçiş oranı) karşılaştırır ve "kaybı %50 azaltmak için kaç ek istasyon gerekir" sorusuna geriye-doğru arama ile cevap üretir.

#### Bulgu: Kutup İstasyonu Darboğazı
Bu senaryolardan çıkan en önemli sonuç: **istasyon eklemek kapasiteyi otomatik artırmıyor.** SSO/polar yörüngeli (97.5° inklinasyon) uydular, kutup-bölgesi istasyonlarından (örn. Svalbard, 78°N) her turda görülür (günde ~10-15 kez), orta enlemden (örn. Ankara, 40°N) ise sadece birkaç kez. Yeni eklenen istasyon da yüksek-görünürlük (kutup) bölgesindeyse, kapasiteden çok talebi büyütüp mevcut darboğazı genişletebiliyor:

| Uydu | 1 İstasyon | 2 İstasyon (+Svalbard) | 3 İstasyon (+Punta Arenas) |
|:---:|:---:|:---:|:---:|
| 25 | %37.8 kayıp | **%52.8 kayıp** | %50.0 kayıp |
| 80 | %54.6 kayıp | **%73.3 kayıp** | %70.0 kayıp |

**Daha güçlü bulgu:** Bu sıralı sonucun "yanlış istasyon seçimi" değil yapısal bir kısıt olduğunu doğrulamak için, sabit liste sırası yerine her adımda kalan tüm adayları deneyip kaybı en çok azaltanı seçen bir **greedy en-iyi-istasyon araması** çalıştırıldı. Greedy doğru çalışıyor, kutup-bölgesi istasyonlarını (Punta Arenas, Reykjavik, Fairbanks) bilerek en sona bırakıyor (örn. 10 uydu/1 istasyon için seçilen sıra: Singapore→Perth→Toronto→Quito→Cape Town→Wellington→Tokyo→Punta Arenas→Reykjavik→Fairbanks). Buna rağmen **12 adaylık havuzun tamamı en iyi sırayla eklense bile** hiçbir senaryoda %50 kayıp-azaltma hedefine ulaşılamadı. Bu, basit coğrafi istasyon eklemenin (en iyi seçimle bile) yeterli olmayabileceğine işaret eden bir gözlem — yüksek-verim/çoklu-anten istasyon veya inter-satellite link gibi farklı bir yer-segmenti stratejisi gerekebilir, ama bu kesin bir çözüm değil, bir hipotezdir.

Gerçek dünyada SSO ağırlıklı yer gözlem operatörleri bu nedenle kutup/yarı-kutup bölgesinde çoklu istasyon veya yüksek-verim yer segmentine yatırım yapar. Modelin varsayımları (10° elevasyon eşiği, istasyon başına tek-kanal, 12 aday lokasyon, 24 saatlik pencere) altında geçerli bir gözlemdir, kesin bir imkansızlık iddiası değildir. Detaylı analiz ve tam senaryo tablosu: [RELEASE.md](RELEASE.md#bulgu-kutup-istasyonu-darboğazı).

#### Veri ve Varsayımlar Şeffaflığı
| Parametre | Etiket |
|---|---|
| TLE verisi | **Gerçek** (Celestrak `stations`/`visual`/`debris`/`resource`, canlı fetch) |
| Senaryo uydu seçimi | **Gerçek veri**, referans SSO profiline en yakın nesneler — operatörün kendi constellation'ı değil, benzer yörünge fiziğine sahip gerçek nesneler |
| İstasyon koordinatları | **Gerçek koordinat**, varsayımsal aday havuzu (fiilen kurulu istasyon iddiası yok) |
| `min_elevation_deg=10°` | **Mühendislik varsayımı**, SATCOM endüstri pratiğine uygun (ITU-R P.618), operatöre özgü kalibre edilmemiş |
| Tarama adımı / senaryo süresi / uydu sayıları | **Mühendislik varsayımları** (performans-hassasiyet dengesi, günlük döngü, büyüme tahmini) |

Tam tablo ve gerekçeler: [RELEASE.md](RELEASE.md#veri-ve-varsayımlar-şeffaflığı).

### Bakım Etki Analizi (Maintenance Impact Analyzer)
Bir yer istasyonunda planlanan bakım çalışmasının (anten söküm, yazılım güncellemesi vb.) hangi uydu geçişlerini kaybettireceğini hesaplar:

* **B* → Ömür Dönüşümü:** 1976 US Standard Atmosphere piecewise-exponential atmosfer modeli (150–1000 km) ile TLE'deki B* sürüklenme katsayısından tahmini yörünge ömrü türetilir; ömre göre uyduya bir "kayıp önceliği" ağırlığı atanır (<180 gün → 3.0, 180-365 gün → 2.0, >365 gün → 1.0).
* **B* Regresyonu:** B*, tek bir TLE anlık görüntüsü yerine `tle_history` tablosundaki geçmiş kayıtlara doğrusal regresyon uygulanarak hesaplanır — bozunma trendi hızlanan bir uydu daha yüksek ağırlık alır.
* **Pencere Skorlama:** 7 günlük ufku 30 dakikalık adımlarla tarayarak her aday bakım penceresi için maliyet puanını (kayıp geçişlerin `süre × ağırlık` toplamı) hesaplar ve en iyi/en kötü zaman aralıklarını sıralar.

Detaylı doğrulama sonuçları: [RELEASE.md](RELEASE.md#bakım-etki-analizi-maintenance-impact-analyzer).

### Frontend

* **Canlı Harita Görünümü:** Leaflet.js haritası üzerinde, seçilen uyduların SGP4 ile hesaplanmış yörünge yollarını (Lat/Lon/Alt) görselleştirir.
* **Çarpışma Analizi Arayüzü:** Kritik Riskler (`COLLISION`) ve Yakın Formasyon Uçuşları/Kenetlenmeler (`DOCKING`) olaylarını ayırarak görüntüler.
* **Manevra Planlama Modalı:** Seçilen bir çarpışma uyarısı için, hedeflenen güvenli mesafeye ulaşmak için gereken optimal DeltaV değerlerini gösteren etkileşimli bir arayüz sunar.
* **Manevra Tespiti Paneli:** Katalogdaki uydular için otomatik taranan geçmiş manevra olaylarını (tip, Δa/Δi/Δe, tahmini ΔV, güven skoru) listeler.
* **Canlı Yörünge Yenileme:** Haritadaki uydu işaretçisi, 100 dakikalık hesaplama penceresinin sonuna yaklaştığında arka planda otomatik olarak yeni bir yörünge parçası çekerek kesintisiz takip sağlar.
* **Sunucu Taraflı Sayfalama:** Uydu Kataloğu, CDM Çarpışma Uyarıları, Manevra Tespiti ve SSA Zekası listeleri `page`/`limit` parametreleriyle sayfalanır; binlerce kaydın tamamı tek seferde DOM'a basılmaz.

### ASTM-Demo Örneği
[![ASTM Demo Video](docs/Screenshots/dashboard.png)](https://vimeo.com/1145363572)
> *Demoyu izlemek için yukarıdaki görsele tıklayınız.*
Demo videosuna ve rapora ```docs``` dizininden ulaşabilirsiniz. Demo videosunu görüntülemek için ```view raw``` seçeneğine basıp videoyu indirebilirsiniz. **Video Aralık 2025 tarihli olduğundan güncel modülleri ve değişiklikleri içermemektedir**.

## Kurulum ve Çalıştırma

### Gereksinimler

* Python 3.10+
* Git

### Adımlar

1.  **Projeyi Klonlama:**
    ```bash
    git clone https://github.com/sebnembasak/astm-prototype
    cd astm-prototype
    ```

2.  **Sanal Ortam Oluşturma ve Bağımlılıkları Yükleme:**
    ```bash
    # Sanal ortamı oluştur ve etkinleştir
    python -m venv .venv
    source .venv/bin/activate
    
    # Bağımlılıkları yükle
    pip install -r requirements.txt
    ```

3.  **Veritabanını Başlatma:**
    Veritabanı tablolarını (`raw_tles`, `conjunction_alerts`) oluşturur.
    ```bash
    python backend/models/db.py
    # Çıktı: Veritabanı tabloları başarıyla oluşturuldu/güncellendi.
    ```

4.  **TLE Verilerini Çekme (İlk Yükleme):**
    Celestrak'tan güncel uydu verilerini çeker ve yerel veritabanına kaydeder.
    ```bash
    python ingest/tle_fetcher.py
    ```

5.  **API Sunucusunu Başlatma:**
    Uvicorn ile FastAPI uygulamasını çalıştırın.
    ```bash
    uvicorn main:app --reload
    ```
    Sunucu varsayılan olarak `http://127.0.0.1:8000` adresinde başlayacaktır.

### Erişilebilirlik

* **Web Arayüzü:** `http://127.0.0.1:8000/`
* **API Dokümantasyonu (Swagger UI):** `http://127.0.0.1:8000/docs`

## Temel Hesaplama Modülleri

| Modül | Dosya Yolu | Sorumluluk                                                                                             |
| :--- | :--- |:-------------------------------------------------------------------------------------------------------|
| **SGP4 Propagatör** | `processing/propagator.py` | TLE'den alınan yörüngeyi belirli bir zamana kadar ilerletir (r ve v vektörlerini TEME'de verir).       |
| **Koordinat Dönüşümü** | `processing/coord_utils.py` | TEME (uzay) koordinatlarını haritada çizmek için Lat/Lon/Alt (Dünya yüzeyi) değerlerine çevirir        |
| **Budama (Pruner)** | `processing/pruner.py` | **cKDTree** kullanarak binlerce uydu arasından sadece birbirine yakın olan aday çiftleri hızlıca seçer |
| **Manevra Optimizasyonu** | `planner/optimizer.py` | **Scipy.optimize** (L-BFGS-B) kullanarak çarpışma sonrası güvenli mesafeyi sağlayan minimum DeltaV değerini bulur |
| **Manevra Tespiti** | `processing/maneuver_detection.py` | Ardışık TLE'lerin mean orbital elementlerinden (faz-bağımsız) fizik tabanlı ΔV tahminiyle geçmiş manevraları tespit eder |
| **Yer İstasyonu Görüş Geometrisi** | `processing/ground_station.py` | TEME konumundan topocentric elevasyon açısı hesaplar, AOS/LOS geçiş pencerelerini bulur |
| **Çakışma Tespiti (İstasyon)** | `processing/schedule_conflict.py` | Aynı istasyonda zaman içinde örtüşen geçiş pencerelerini ve çakışma oranını tespit eder |
| **Yer İstasyonu Çizelgeleme** | `planner/ground_scheduler.py` | İstasyon-bağımlı Earliest-Finish-Time greedy algoritmasıyla çakışan geçişler arasından atama yapar |
| **Bakım Etki Analizi** | `service/maintenance_service.py` | B*'tan atmosfer modeliyle yörünge ömrü/ağırlık türetir, 7 günlük ufukta bakım penceresi maliyetini puanlar |

## Test ve Doğrulama

Çekirdek uzay mekaniği modülleri (`processing/conjunction.py`, `planner/optimizer.py`) için `tests/` dizininde deterministik birim testleri bulunur. Testler, gerçek SGP4/poliastro çağrıları yerine doğrusal hareket varsayan sahte (mock) propagator fonksiyonları kullanarak el ile doğrulanabilir kapalı-form sonuçlar üzerinden çalışır:

```bash
pytest tests/ -v
```

## Proje Yapısı

Proje, Servis Katmanı Mimarisi (Service Layer Architecture) kullanılarak tasarlanmıştır.

| Dizin | Amaç                                                                                                      |
| :--- |:----------------------------------------------------------------------------------------------------------|
| **backend/api** | FastAPI router'ları, HTTP isteklerini (`router_*.py`) işler                                               |
| **service** | İş mantığı katmanı. API ile çekirdek hesaplama (`processing`, `planner`) modüllerini bağlar               |
| **processing** | Çekirdek uzay mekaniği ve matematiksel hesaplamalar (SGP4, koordinat dönüşümü, budama, çarpışma analizi). |
| **planner** | Optimizasyon motorunu ve manevra hesaplama algoritmalarını içerir.                                        |
| **ingest** | Harici veri kaynaklarından (Celestrak) veri çekme işlemleri (`tle_fetcher.py`).                           |
| **backend/models** | Veritabanı şemaları ve bağlantı ayarları (`db.py`).                                                       |
| **main.py** | FastAPI uygulamasının ana giriş noktası.                                                                  |
| **assets/** | CSS, JS ve görsel dosyaları.                                                                              |

Projenin bilinen sınırlamaları ve kaynaksız varsayımları şeffafça belgelenmiştir: [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

## Diyagramlar
Tüm diyagramların düzenlenebilir `.drawio` kaynakları ve açık/koyu tema PNG çıktıları `docs/Diagrams/` altındadır.

### Sistem Mimarisi (v1.4.0):
![Sistem Mimarisi](docs/Diagrams/sistem_mimarisi.png "Katmanlı Sistem Mimarisi")

### Çarpışma Tarama Pipeline (TLE'den Karara):
![Çarpışma Tarama Pipeline](docs/Diagrams/conjunction_pipeline.png "Çarpışma Tarama Pipeline")

### Kaçınma Manevrası Optimizasyonu (Sequence):
![Manevra Optimizasyonu](docs/Diagrams/manevra_optimizasyonu.png "Manevra Optimizasyonu Sequence Diyagramı")

### SSA / Yapay Zeka Pipeline:
![SSA ML Pipeline](docs/Diagrams/ssa_ml_pipeline.png "SSA ML Pipeline")

### Yer İstasyonu Kapasite Planlama — Modül Mimarisi & Akış:
![Ground Station Scheduling](docs/Diagrams/ground_station_scheduling.png "Ground Station Scheduling")

Sistem hakkında detaylı bilgiye ```docs``` klasörü altındaki ```astm-rapor.pdf``` dosyasından ulaşabilirsiniz.


## Ekran Görüntüleri

> Aşağıdaki tüm görüntüler `docs/Screenshots_v2/` klasöründedir ve v2.0.0 itibarıyla gerçek backend'e bağlı, gerçek veriyle (canlı Celestrak TLE'leri, gerçek TLE'lerden hesaplanan çarpışma/manevra/kapasite sonuçları) çekilmiştir — mock veri değildir. Eski (Aralık 2025) görüntüler `docs/Screenshots/` altında arşiv olarak kalmıştır.

### Operasyon Merkezi (Dashboard)
![Dashboard](docs/Screenshots_v2/01_dashboard.png "Operasyon Merkezi")
Katalogdaki toplam uydu sayısı, son taramada bulunan kritik risk sayısı ve tespit edilen gerçek manevra sayısını gösteren ana özet ekranı. Sağdaki "Hub Komutları" TLE güncelleme ve çarpışma taramasını tetikler.

### Dashboard — Sayfa Açıklama Kutusu
![Dashboard Açıklama](docs/Screenshots_v2/02_dashboard_aciklama.png "Dashboard açıklama kutusu")
Her sayfada bulunan katlanabilir "Bu sayfa ne anlatıyor?" kutusu — sayfadaki terimleri ve hesaplama mantığını teknik olarak açıklar.

### Uydu Veritabanı
![Uydu Veritabanı](docs/Screenshots_v2/03_uydu_veritabani.png "Uydu Veritabanı")
Celestrak'tan çekilen gerçek TLE kataloğu (300+ nesne) — yörünge parametreleri ve kaynak gruplarıyla listelenir.

### Uydu Arama
![Uydu Arama](docs/Screenshots_v2/04_uydu_arama_sonucu.png "Uydu arama sonucu")
İsme göre filtrelenmiş katalog araması (örnek: "ISS").

### Çarpışma Analizi — Riskler
![Çarpışma Analizi](docs/Screenshots_v2/05_carpisma_analizi_riskler.png "Çarpışma Analizi - Riskler")
SGP4 ile yayılan gerçek TLE çiftleri arasında hesaplanan en yakın yaklaşım (TCA) listesi. Risk yüzdesi, mesafeye dayalı basit bir gösterge olup gerçek bir çarpışma olasılığı (Pc) değildir.

### Çarpışma Analizi — Bilinen Sınırlama Uyarısı
![Çarpışma Analizi Açıklama](docs/Screenshots_v2/06_carpisma_analizi_aciklama_uyari.png "Bilinen sınırlama uyarısı")
Bu sayfanın açıklama kutusu, CSS modülleri arası epoch tutarsızlığı artefaktı gibi bilinen sınırlamaları doğrudan kullanıcıya bildirir (detay: `KNOWN_LIMITATIONS.md`).

### Kaçınma Manevrası — Hesaplama Ekranı
![Kaçınma Manevrası Modal](docs/Screenshots_v2/07_kacinma_manevrasi_modal_bos.png "Kaçınma manevrası modalı")
Bir risk satırındaki "araç" ikonuyla açılan, hedef güvenli mesafe girilen optimizasyon ekranı.

### Kaçınma Manevrası — Sonuç
![Kaçınma Manevrası Sonuç](docs/Screenshots_v2/08_kacinma_manevrasi_sonuc.png "Kaçınma manevrası sonucu")
`scipy.optimize` L-BFGS-B ile bulunan optimum ateşleme zamanı, gereken Delta-V ve yeni mesafe — gerçek sayısal optimizasyon çıktısı.

### Kenetlenme & Formasyon
![Kenetlenme](docs/Screenshots_v2/09_kenetlenme_formasyon.png "Kenetlenme ve Formasyon uçuşu")
Mesafe ve bağıl hız eşiklerine göre "kenetli/formasyon" (DOCKING) olarak sınıflandırılan gerçek nesne çiftleri (örn. CSS/ISS modülleri).

### Çarpışmayı Haritada İzleme
![Haritada İzleme](docs/Screenshots_v2/10_carpisma_haritada_izleme.png "Çarpışma olayının haritada gösterimi")
Bir yakınlaşma olayındaki iki nesnenin, TCA anındaki konumlarıyla haritada gösterimi.

### Yörünge Simülasyonu (Canlı Harita)
![Yörünge Simülasyonu](docs/Screenshots_v2/11_yorunge_simulasyonu.png "Yörünge Simülasyonu")
Seçilen bir uydunun gerçek SGP4 propagasyonuyla hesaplanan yörünge izi. "CANLI TAKİP" ile marker'ın 1 saniyelik aralıklarla hareket ettiğini gösterir.

### Manevra Tespiti
![Manevra Tespiti](docs/Screenshots_v2/12_manevra_tespiti.png "Manevra Tespiti")
Ardışık TLE setleri arasındaki BSTAR/yarı-major eksen/eksantriklik/inklinasyon farklarından tespit edilen gerçek manevra olayları, değişen parametreye göre sınıflandırılmış (İrtifa Değişimi, Düzlem Değişimi, Eksantriklik Değişimi, Kombine).

### SSA Zekası — Sınıflandırma ve Kümeleme
![SSA Zekası](docs/Screenshots_v2/13_ssa_zekasi.png "SSA Zekası")
Yörünge rejimi haritası (GMM ile soft kümeleme) ve Random Forest ile yapılan görev/nesne sınıflandırması — kalibre edilmiş güven skorlarıyla.

### SSA Zekası — Model Performans Raporu
![SSA Performans Raporu](docs/Screenshots_v2/14_ssa_performans_raporu.png "SSA Model Performans Raporu")
Eğitilmiş modelin confusion matrix'i, sınıf bazlı precision/recall/F1 metrikleri ve özellik önem düzeyleri (feature importance) — UCS Satellite Database üzerinde gerçek eğitim sonucu.

### Yer İstasyonu Kapasite Planlama — Sayfa Açıklaması
![Yer İstasyonu Açıklama](docs/Screenshots_v2/15_yer_istasyonu_planlama_aciklama.png "Yer İstasyonu Planlama açıklama kutusu")
AOS/LOS, kapasite kaybı ve "Kutup İstasyonu Darboğazı" ana bulgusunun bu sayfadaki açıklaması.

### Yer İstasyonu Kapasite Planlama — Genel Görünüm
![Yer İstasyonu Genel](docs/Screenshots_v2/16_yer_istasyonu_planlama_genel.png "Yer İstasyonu Planlama")
Aday istasyon haritası ve senaryo parametreleri (uydu sayısı, istasyon sayısı, süre).

### Yer İstasyonu Kapasite Planlama — Tekil Senaryo Sonucu
![Yer İstasyonu Senaryo Sonuç](docs/Screenshots_v2/17_yer_istasyonu_senaryo_sonuc.png "Tekil senaryo sonucu")
10 uydu / 2 istasyon senaryosu için gerçek SGP4 tabanlı geçiş hesaplamasıyla bulunan kapasite kaybı ve %50 azaltım için gereken ek istasyon sayısı (greedy en-iyi-istasyon araması).

### Yer İstasyonu Kapasite Planlama — Tüm Senaryolar (Izgara)
![Yer İstasyonu Grid Sonuç](docs/Screenshots_v2/19_yer_istasyonu_grid_sonuc.png "Senaryo ızgarası sonucu")
3/10/30/80 uydu × 1/2/3 istasyon ızgarasının tam koşusu — her satırda, hedefe ulaşmak için greedy aramayla seçilen istasyonların sırası (kutup istasyonları ayrı renkle işaretli) doğrudan görünür sütun olarak gösterilir.

### Bakım Etki Analizi
![Bakım Etki Analizi](docs/Screenshots_v2/21_bakim_etki_analizi.png "Bakım Etki Analizi")
Ankara istasyonu için 4 saatlik bakım senaryosu — 7 günlük ufukta gerçek SGP4 geçişleriyle hesaplanan en iyi (yeşil, "Sıfır Kayıp") ve en kötü (kırmızı) bakım zaman aralıkları, B*'tan türetilen uydu ağırlıklarıyla puanlanmış.
