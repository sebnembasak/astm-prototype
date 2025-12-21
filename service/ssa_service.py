import pandas as pd
import numpy as np
import json
import joblib
from pathlib import Path
from datetime import datetime, timezone
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.cluster import KMeans
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score, confusion_matrix, classification_report
from backend.models.db import get_conn


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
        self.kmeans = None
        self.iso_forest = None
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

    def parse_bstar(self, line1):
        """
        TLE Line 1 içindeki B* (BSTAR) sürüklenme katsayısını ayrıştırır.
        Bu değer uydunun atmosferik dirençten ne kadar etkilendiğini gösterir.
        """
        try:
            # Boşlukları temizle ve formatı düzelt (Örn: " 12345-3" -> "0.12345e-3")
            bstar_str = line1[53:61].strip()
            if not bstar_str: return 0.0

            # Eğer sonda işaret varsa (-3, +2 gibi) onu ayır
            sign_pos = -2
            mantissa = bstar_str[:sign_pos].strip()
            exponent = bstar_str[sign_pos:].strip()

            val = f"0.{mantissa}e{exponent}"
            return float(val)
        except:
            return 0.0

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


            for col in features:
                # Veri setindeki virgülleri noktaya çevirip sayısal tipe dönüştürme
                df[col] = df[col].astype(str).str.replace(',', '').str.replace('"', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')

            # Eksik verileri (NaN) temizle ve hedef değişkeni etiketle
            df = df[['Purpose'] + features].dropna()

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
                # Çok sınıflı ROC-AUC skoru
                roc_auc = roc_auc_score(y_test, y_prob, multi_class='ovr', average='weighted')
            except:
                roc_auc = 0.0

            metrics = {
                "accuracy": accuracy_score(y_test, y_pred),  # Genel doğruluk oranı
                "f1_score": f1_score(y_test, y_pred, average='weighted'),  # Dengesiz sınıflar için hassasiyet metriği
                "roc_auc": roc_auc,
                "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
                "classes": self.label_encoder.classes_.tolist(),
                "feature_importance": dict(zip(features, self.model.feature_importances_.tolist())),  # Hangi özellik daha önemli?
                "classification_report": classification_report(y_test, y_pred, output_dict=True),  # Detaylı rapor
                "sample_size": len(df),
                "timestamp": datetime.now().isoformat()
            }

            # Metrikleri JSON dosyasına kaydet
            with open(self.metrics_path, "w") as f:
                json.dump(metrics, f)

            # Kümeleme (K-Means) ve Anomali Tespiti (Isolation Forest)
            # Veriyi ölçeklendirip uyduları gruplandırıyoruz ve normal dışı olanları yakalıyoruz.
            kmeans = KMeans(n_clusters=5, random_state=42).fit(self.scaler.fit_transform(X))
            iso_forest = IsolationForest(contamination=0.03, random_state=42).fit(self.scaler.transform(X))

            # Modelleri disk üzerine kaydediyoruz
            joblib.dump((self.model, self.label_encoder, self.scaler, kmeans, iso_forest), self.model_path)
            return f"Model Başarıyla Eğitildi. Doğruluk: %{metrics['accuracy'] * 100:.1f}"

        except Exception as e:
            return f"Eğitim Hatası: {str(e)}"

    def analyze_all_satellites(self):
        """
        Eğitilmiş modelleri kullanarak canlı TLE verilerini analiz etme.
        """
        if self.model is None or self.kmeans is None or self.iso_forest is None:
            if self.model_path.exists():
                try:
                    loaded_data = joblib.load(self.model_path)
                    self.model, self.label_encoder, self.scaler, self.kmeans, self.iso_forest = loaded_data
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
                mm = float(line2[52:63])  # Mean Motion uydunun bir günde dünya etrafında kaç tur attığıdır
                alt = ((398600.44 / ((mm * 2 * np.pi / 86400) ** 2)) ** (1 / 3)) - 6378.137
                bstar = self.parse_bstar(line1)

                # AI Tahminleri
                input_raw = np.array([[incl, ecc, 1440 / mm, alt, alt]])
                scaled = self.scaler.transform(input_raw)

                cat = self.label_encoder.inverse_transform(self.model.predict(input_raw))[0]
                conf = np.max(self.model.predict_proba(input_raw))
                cluster_id = int(self.kmeans.predict(scaled)[0])
                is_anomaly = 1 if self.iso_forest.predict(scaled)[0] == -1 else 0

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
        cur.execute("SELECT line2 FROM raw_tles")
        data = []
        for row in cur.fetchall():
            try:
                line2 = row[0]
                incl = float(line2[8:16])
                mm = float(line2[52:63])
                alt = ((398600.44 / ((mm * 2 * np.pi / 86400) ** 2)) ** (1 / 3)) - 6378.137
                if 200 < alt < 40000:
                    data.append({"x": round(incl, 1), "y": round(alt, -1)})
            except:
                continue
        conn.close()
        return data


ssa_service = SSAService()
