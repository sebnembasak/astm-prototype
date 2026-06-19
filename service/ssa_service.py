import pandas as pd
import numpy as np
import json
import joblib
from pathlib import Path
from datetime import datetime, timezone
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.mixture import GaussianMixture
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score, confusion_matrix, classification_report
from backend.models.db import get_conn
from processing.propagator import tle_to_satrec


class SSAService:
    """
    Uzay Durum Farkındalığı (SSA) Analiz Servisi
    Bu sınıf ham TLE verilerini kullanarak uyduların davranışlarını ve amaçlarını analiz eder.
    """

    def __init__(self):
        self.model_path = Path("data/ssa_model.joblib")
        self.data_path = Path("data/ucs_database.csv")
        self.metrics_path = Path("data/ssa_metrics.json")
        self.model = None
        self.cluster_model = None
        self.iso_forest = None
        self.lof = None
        self.label_encoder = LabelEncoder()  # Kategorik verileri sayısal verilere dönüştürür
        self.scaler = StandardScaler()  # Verileri standart normal dağılıma (0 ortalama, 1 sapma) çeker

        """
        Problem: Uzayda binlerce aktif/pasif nesne bulunmaktadır. Bu nesnelerin ham yörünge 
        parametrelerine (TLE) bakarak, hangi amaçla (Haberleşme, Gözlem vb.) kullanıldığını 
        tahmin etmek ve normal dışı (anomali) hareket edenleri saptamak temel problemimizdir.
        """

        # yörünge rejimi etiketleri
        self.REGIME_MAP = {
            0: "LEO - Düşük Yörünge (Yüksek Trafik)",
            1: "MEO - Orta Yörünge (Navigasyon)",
            2: "GEO - Yer Sabit (Haberleşme Kuşağı)",
            3: "HEO - Yüksek Eliptik (Stratejik)",
            4: "VLEO - Çok Alçak Yörünge"
        }

    def train_model(self):
        """
        Kaynak: Union of Concerned Scientists (UCS) Uydu Veri Seti.
        Bu veri seti Dünya yörüngesindeki yaklaşık 7.500 aktif uyduya ait teknik (kütle, güç, fırlatma tarihi),
        yörünge (apoj, perij, eğim, yörünge türü) ve operasyonel (ülke, operatör, kullanım amacı) bilgileri içeren,
        uzay varlıklarının dağılımı ve kullanım alanlarının analizine uygun kapsamlı bir veri setidir.
        https://www.kaggle.com/datasets/mexwell/ucs-satellite-database/data
        """
        if not self.data_path.exists():
            return "Hata: Veri seti bulunamadı."

        try:
            # Ön İşleme
            # Ham verideki sayısal hataları, noktalama yanlışlarını ve eksik değerleri temizliyoruz.
            df = pd.read_csv(self.data_path, sep=';', on_bad_lines='skip', low_memory=False, encoding='latin-1')
            df.columns = [c.strip() for c in df.columns]

            # Sütun isimlerini daha yönetilebilir hale getirme (Mapping)
            mapping = {
                'Purpose': 'Purpose',
                'Inclination (degrees)': 'Inclination',
                'Eccentricity': 'Eccentricity',
                'Period (minutes)': 'Period_minutes',
                'Perigee (km)': 'Perigee',
                'Apogee (km)': 'Apogee'
            }
            df = df.rename(columns=mapping)

            # Özellik Seçimi, en açıklayıcı 5 fiziksel parametre
            # Uydu amacını belirlemede en etkili fiziksel parametreler seçilmiştir:
            # Eğim (Inclination), Basıklık (Eccentricity), Periyot ve İrtifa değerleri.
            features = ['Inclination', 'Eccentricity', 'Period_minutes', 'Perigee', 'Apogee']

            # UCS verisi Avrupa ondalık formatında ('96,08' = 96.08). Virgülü SİLMEK
            # (eski .replace(',', '')) değeri 9608'e bozar — burada nokta ile değiştirip
            # gerçek ondalık değeri koruyoruz.
            for col in ['Inclination', 'Eccentricity', 'Period_minutes']:
                df[col] = df[col].astype(str).str.replace(',', '.').str.replace('"', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')

            df = df[['Purpose', 'Inclination', 'Eccentricity', 'Period_minutes']].dropna()

            # Fiziksel olarak imkansız periyotları ele: Dünya yüzeyinde dahi bir yörüngenin
            # periyodu ~84.4 dakikadan kısa olamaz (çevresel hız sınırı). Bunun altındaki
            # satırlar UCS'deki veri girişi hatalarıdır.
            df = df[df['Period_minutes'] > 84.4]

            # Kapalı (eliptik) bir yörüngede dış merkezlik [0, 1) aralığında olmalıdır;
            # 1'in üzeri açık/hiperbolik kaçış yörüngesi demektir ve bir "uydu" için
            # imkansızdır. UCS verisinde bazı satırlarda üs işareti ters yazılmış
            # (ör. '5,11E+02' = 511 — gerçekte muhtemelen '5.11E-02' = 0.0511 olmalıydı),
            # bu satırlar Kepler türetimini milyonlarca km'lik aşırı uçlarla kirletiyor.
            df = df[df['Eccentricity'] < 1]

            # Perigee/Apogee'yi CSV'den okumak yerine Period + Eccentricity'den Kepler'in
            # 3. Kanunu ile türetiyoruz. Sebep: CSV'deki "Perigee (km)"/"Apogee (km)" sütunları
            # belirsiz biçimlendirilmiş — büyük değerler '.' karakterini binlik ayraç olarak
            # kullanıyor (ör. GEO için '35.778' aslında 35.778 km değil 35.778 km'dir, yani
            # 35778 km demektir) ama pandas bunu ondalık nokta sanıp ~1000x küçük okuyor.
            # Kepler ile türetmek hem bu belirsizliği tamamen baypas eder hem de canlı TLE
            # analizindeki (analyze_all_satellites) hesaplama yöntemiyle birebir tutarlı hale
            # getirerek eğitim/çıkarım dağılım uyuşmazlığını giderir.
            mu, Re = 398600.4418, 6378.137
            semi_major = (mu * (df['Period_minutes'] * 60 / (2 * np.pi)) ** 2) ** (1 / 3)
            df['Perigee'] = semi_major * (1 - df['Eccentricity']) - Re
            df['Apogee'] = semi_major * (1 + df['Eccentricity']) - Re

            df = df.dropna(subset=features)

            # Eğitim kararlılığı için sadece 1 örneği olan nadir sınıfları çıkarıyoruz
            df = df[df.groupby('Purpose')['Purpose'].transform('count') > 1]

            X = df[features]  # Girdi özellikleri
            y = self.label_encoder.fit_transform(df['Purpose'].astype(str))  # Hedef değişken

            # Random Forest algoritması kullanılmıştır - %80 Eğitim, %20 Test
            # Bu problemde uyduların kullanım amaçları (Kategorik hedef) ile yörünge parametreleri (Sayısal girdiler) arasındaki
            # ilişki doğrusal olmayabilir. Örneğin casus uydular ile meteoroloji uyduları benzer irtifalarda (LEO) olabilir
            # ancak eğimleri (Inclination) farklıdır. Random Forest, bu karmaşık karar ağaçlarını başarıyla modeller.
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
            self.model = RandomForestClassifier(n_estimators=200, class_weight='balanced', random_state=42)
            self.model.fit(X_train, y_train)

            # Performans Metrikleri
            y_pred = self.model.predict(X_test)
            y_prob = self.model.predict_proba(X_test)

            try:
                # Çok sınıflı ROC-AUC skoru. `labels` zorunlu: 21 sınıftan bazılarının
                # (ör. 2 örnekli "Mission Extension Technology") stratified split sonrası
                # y_test'te hiç temsilcisi kalmayabiliyor; labels olmadan sklearn y_true'daki
                # benzersiz sınıf sayısını y_score sütun sayısıyla eşleşmeyince ValueError atıyor.
                roc_auc = roc_auc_score(y_test, y_prob, multi_class='ovr', average='weighted',
                                        labels=np.arange(len(self.label_encoder.classes_)))
            except Exception:
                roc_auc = 0.0

            metrics = {
                "accuracy": accuracy_score(y_test, y_pred),  # Genel doğruluk oranı
                "f1_score": f1_score(y_test, y_pred, average='weighted'),  # Dengesiz sınıflar için hassasiyet metriği
                "roc_auc": roc_auc,
                "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
                "classes": self.label_encoder.classes_.tolist(),
                "feature_importance": dict(zip(features, self.model.feature_importances_.tolist())),
                # Hangi özellik daha önemli?
                "classification_report": classification_report(y_test, y_pred, output_dict=True),  # Detaylı rapor
                "sample_size": len(df),
                "timestamp": datetime.now().isoformat()
            }

            # Metrikleri JSON dosyasına kaydet
            with open(self.metrics_path, "w") as f:
                json.dump(metrics, f)

            # Kümeleme (Gaussian Mixture Model) ve Anomali Tespiti (Isolation Forest + LOF)
            # Veriyi ölçeklendirip uyduları gruplandırıyoruz ve normal dışı olanları yakalıyoruz.
            # KMeans'in sert (hard) küme sınırları yerine GMM her uyduya kümeler üzerinde
            # olasılıksal bir dağılım atar — rejim sınırındaki uydular için daha gerçekçi.
            cluster_model = GaussianMixture(n_components=5, random_state=42).fit(self.scaler.fit_transform(X))
            iso_forest = IsolationForest(contamination=0.03, random_state=42).fit(self.scaler.transform(X))
            # Isolation Forest global/eksen-hizalı bölünmelerle çalışır, yoğun bir kümenin
            # İÇİNDEKİ lokal anormallikleri (komşularına göre tutarsız uydular) gözden
            # kaçırabilir. LOF (yoğunluk tabanlı) bunu tamamlıyor. novelty=True, eğitimden
            # sonra yeni (canlı TLE) verilerde .predict() çağrısına izin verir.
            lof = LocalOutlierFactor(n_neighbors=20, contamination=0.03, novelty=True).fit(
                self.scaler.transform(X))

            # Modelleri disk üzerine kaydediyoruz
            joblib.dump((self.model, self.label_encoder, self.scaler, cluster_model, iso_forest, lof),
                        self.model_path)
            return f"Model Başarıyla Eğitildi. Doğruluk: %{metrics['accuracy'] * 100:.1f}"

        except Exception as e:
            return f"Eğitim Hatası: {str(e)}"

    def analyze_all_satellites(self):
        """
        Eğitilmiş modelleri kullanarak canlı TLE verilerini analiz etme.
        """
        if self.model is None or self.cluster_model is None or self.iso_forest is None or self.lof is None:
            if self.model_path.exists():
                try:
                    loaded_data = joblib.load(self.model_path)
                    self.model, self.label_encoder, self.scaler, self.cluster_model, self.iso_forest, self.lof = loaded_data
                    print(">>> Modeller diskten başarıyla yüklendi.")
                except Exception as e:
                    print(f">>> Modeller yüklenirken hata: {e}")
                    return 0
            else:
                print(">>> HATA: Model dosyası bulunamadı! Lütfen önce /ssa/train yapın.")
                return 0

        if self.model is None:
            return 0

        # Ülke lookup tablosu oluştur
        ucs_df = pd.read_csv(self.data_path, sep=';', on_bad_lines='skip', low_memory=False, encoding='latin-1')
        ucs_df.columns = [c.strip() for c in ucs_df.columns]

        # NORAD sütununu sayısal yap ve boşlukları sil
        ucs_df['NORAD Number'] = pd.to_numeric(ucs_df['NORAD Number'], errors='coerce')
        country_lookup = ucs_df.dropna(subset=['NORAD Number']).set_index('NORAD Number')[
            'Country of Operator/Owner'].to_dict()

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, sat_name, line1, line2 FROM raw_tles")
        rows = cur.fetchall()

        count = 0
        for sid, name, line1, line2 in rows:
            try:
                if not line2 or len(line2) < 69:
                    continue
                if not line2.startswith("2 "):
                    continue

                # Fiziksel Parametreler
                incl = float(line2[8:16])
                ecc = float("0." + line2[26:33].strip())
                mm = float(line2[52:63])  # Mean Motion: günlük tur sayısı
                semi_major = (398600.44 / ((mm * 2 * np.pi / 86400) ** 2)) ** (1 / 3)
                alt = semi_major - 6378.137  # ortalama irtifa (decay risk için)
                perigee = semi_major * (1 - ecc) - 6378.137
                apogee = semi_major * (1 + ecc) - 6378.137
                bstar = tle_to_satrec(line1, line2).bstar

                # AI Tahminleri — model [Inclination, Eccentricity, Period_min, Perigee, Apogee] ile eğitildi
                input_raw = np.array([[incl, ecc, 1440 / mm, perigee, apogee]])
                scaled = self.scaler.transform(input_raw)

                cat = self.label_encoder.inverse_transform(self.model.predict(input_raw))[0]
                conf = np.max(self.model.predict_proba(input_raw))
                cluster_id = int(self.cluster_model.predict(scaled)[0])
                # İki yöntemden biri anomali derse işaretliyoruz (OR): Isolation Forest
                # global aykırılıkları, LOF ise kümeler içindeki lokal aykırılıkları
                # yakalıyor — kaçırılan gerçek bir anomali, fazladan bir uyarıdan daha
                # maliyetli olduğu için kapsamı genişletmeyi tercih ediyoruz.
                is_anomaly_if = self.iso_forest.predict(scaled)[0] == -1
                is_anomaly_lof = self.lof.predict(scaled)[0] == -1
                is_anomaly = 1 if (is_anomaly_if or is_anomaly_lof) else 0

                # YÖRÜNGE SÖNÜMLENME RİSKİ (Decay Risk)
                # Alçak irtifa + Yüksek BSTAR = Kritik Risk
                decay_risk = "DÜŞÜK"
                if alt < 350 and bstar > 0.0005:  # Kritik irtifa sınırı
                    decay_risk = "YÜKSEK"
                elif alt < 400:
                    decay_risk = "ORTA"

                # ÜLKE BİLGİSİ (Lookup)
                # TLE'deki NORAD ID'yi yakala (Line 2: 3-7 karakterler)
                # TLE'den gelen ID'yi int'e çevir
                norad_id = int(line2[2:7].strip())
                country = country_lookup.get(norad_id, "Bilinmiyor")

                cur.execute("""
                    UPDATE satellite_intelligence 
                    SET predicted_category=?, confidence=?, cluster_id=?, is_anomaly=?, 
                        predicted_country=?, decay_risk=?, predicted_at=?
                    WHERE sat_id=?
                """, (cat, float(conf), cluster_id, is_anomaly, country, decay_risk,
                      datetime.now(timezone.utc).isoformat(), sid))

                if cur.rowcount == 0:
                    cur.execute("""
                        INSERT INTO satellite_intelligence 
                        (sat_id, predicted_category, confidence, cluster_id, is_anomaly, predicted_country, decay_risk, predicted_at)
                        VALUES (?,?,?,?,?,?,?,?)
                    """, (sid, cat, float(conf), cluster_id, is_anomaly, country, decay_risk,
                          datetime.now(timezone.utc).isoformat()))

                count += 1
            except Exception as e:
                print(f"[SSA ERROR] {e}")
                continue

        conn.commit()
        conn.close()
        return count

    def get_metrics(self):
        if self.metrics_path.exists():
            with open(self.metrics_path, "r") as f: return json.load(f)
        return None

    def get_regime_heatmap_data(self):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT r.line2, si.cluster_id
            FROM raw_tles r
            LEFT JOIN satellite_intelligence si ON si.sat_id = r.id
        """)
        data = []
        for line2, cluster_id in cur.fetchall():
            try:
                incl = float(line2[8:16])
                mm = float(line2[52:63])
                alt = ((398600.44 / ((mm * 2 * np.pi / 86400) ** 2)) ** (1 / 3)) - 6378.137
                if 200 < alt < 40000:
                    data.append({"x": round(incl, 1), "y": round(alt, -1), "cluster_id": cluster_id})
            except:
                continue
        conn.close()
        return data


ssa_service = SSAService()
