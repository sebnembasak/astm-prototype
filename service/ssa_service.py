import pandas as pd
import numpy as np
import json
import joblib
from pathlib import Path
from datetime import datetime, timezone
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.mixture import GaussianMixture
from sklearn.neighbors import LocalOutlierFactor
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score, confusion_matrix, classification_report
from backend.models.db import get_conn
from processing.propagator import tle_to_satrec


class SSAService:
    """
    Uzay Durum Farkındalığı (SSA) Analiz Servisi
    Ham TLE verilerini kullanarak uyduların davranışlarını ve amaçlarını analiz eder.
    """

    def __init__(self):
        self.model_path = Path("data/ssa_model.joblib")
        self.data_path = Path("data/ucs_database.csv")
        self.metrics_path = Path("data/ssa_metrics.json")
        self.model = None
        self.cluster_model = None
        self.iso_forest = None
        self.lof = None
        self.label_encoder = LabelEncoder()
        self.scaler = StandardScaler()

        self.REGIME_STYLES = {
            "VLEO": {"name": "VLEO - Çok Alçak Yörünge", "color": "#ff0055", "icon": "fa-meteor"},
            "LEO": {"name": "LEO - Alçak Yörünge", "color": "#00f3ff", "icon": "fa-layer-group"},
            "MEO": {"name": "MEO - Orta Yörünge (Navigasyon)", "color": "#ffae00", "icon": "fa-satellite-dish"},
            "GEO": {"name": "GEO - Yer Sabit (Haberleşme Kuşağı)", "color": "#bc13fe", "icon": "fa-broadcast-tower"},
            "HEO": {"name": "HEO - Yüksek Eliptik (Stratejik)", "color": "#0aff60", "icon": "fa-shield-alt"},
        }

        self.REGIME_ANCHORS = {
            "VLEO": (350, 0.001),
            "LEO": (700, 0.001),
            "MEO": (20200, 0.01),
            "GEO": (35786, 0.0005),
            "HEO": (26000, 0.72),
        }
        self.regime_map = {}

    def _build_regime_map(self, cluster_model):
        """
        Küme merkezlerini fiziksel rejimlere bijektif (1-1) atar.
        Özellik sırası train_model() ile aynı: [Inclination, Eccentricity, Period_minutes, Perigee, Apogee]
        """
        from scipy.optimize import linear_sum_assignment

        centers = self.scaler.inverse_transform(cluster_model.means_)
        regime_keys = list(self.REGIME_STYLES.keys())
        n_clusters = len(centers)

        cost = np.zeros((n_clusters, len(regime_keys)))
        for i, center in enumerate(centers):
            _, ecc_c, _, perigee_c, apogee_c = center
            alt_c = max((perigee_c + apogee_c) / 2, 1.0)
            for j, key in enumerate(regime_keys):
                alt_a, ecc_a = self.REGIME_ANCHORS[key]
                d_alt = np.log10(alt_c) - np.log10(max(alt_a, 1.0))
                # HEO'nun irtifası MEO ile örtüşebilir (Molniya apojesi ~40.000 km ama
                # perijesi ~500 km, ortalama ~20.000 km), ayrımı sağlayan yüksek
                # eksantriklik (>0.7). Ağırlığı artırmak HEO-MEO karışıklığını giderir.
                d_ecc = (ecc_c - ecc_a) * 5
                cost[i, j] = d_alt ** 2 + d_ecc ** 2

        row_idx, col_idx = linear_sum_assignment(cost)
        regime_map = {}
        for cid, ridx in zip(row_idx, col_idx):
            style = self.REGIME_STYLES[regime_keys[ridx]]
            regime_map[int(cid)] = dict(style)
        return regime_map

    def _preprocess(self, df):
        """
        Ham UCS CSV'den temiz özellik matrisi üretir.
        train_model() ve harici kullanım için ortak ön işleme adımları.
        """
        mapping = {
            'Purpose': 'Purpose',
            'Inclination (degrees)': 'Inclination',
            'Eccentricity': 'Eccentricity',
            'Period (minutes)': 'Period_minutes',
            'Perigee (km)': 'Perigee',
            'Apogee (km)': 'Apogee'
        }
        df = df.rename(columns=mapping)

        for col in ['Inclination', 'Eccentricity', 'Period_minutes']:
            df[col] = (df[col].astype(str)
                       .str.replace(',', '.', regex=False)
                       .str.replace('"', '', regex=False))
            df[col] = pd.to_numeric(df[col], errors='coerce')

        df = df[['Purpose', 'Inclination', 'Eccentricity', 'Period_minutes']].dropna()
        df = df[df['Period_minutes'] > 84.4]
        df = df[df['Eccentricity'] < 1]

        mu, Re = 398600.4418, 6378.137
        semi_major = (mu * (df['Period_minutes'] * 60 / (2 * np.pi)) ** 2) ** (1 / 3)
        df['Perigee'] = semi_major * (1 - df['Eccentricity']) - Re
        df['Apogee'] = semi_major * (1 + df['Eccentricity']) - Re

        features = ['Inclination', 'Eccentricity', 'Period_minutes', 'Perigee', 'Apogee']
        df = df.dropna(subset=features)
        return df, features

    def _compute_class_weights(self, y, label_encoder):
        counts = np.bincount(y)
        weights = 1.0 / np.sqrt(np.maximum(counts, 1))
        weights = weights / weights.sum() * len(weights)  # normalize et
        return {i: w for i, w in enumerate(weights)}

    def _consolidate_rare_purposes(self, df, min_samples=10):
        counts = df['Purpose'].value_counts()
        rare = counts[counts < min_samples].index
        df = df.copy()
        df['Purpose'] = df['Purpose'].apply(lambda p: 'Other' if p in rare else p)
        return df

    def train_model(self):
        """
        UCS veri setinden Random Forest + GMM + anomali tespiti modellerini eğitir.
        Kaynak: https://www.kaggle.com/datasets/mexwell/ucs-satellite-database/data
        """
        if not self.data_path.exists():
            return "Hata: Veri seti bulunamadı."

        try:
            df_raw = pd.read_csv(
                self.data_path, sep=';', on_bad_lines='skip',
                low_memory=False, encoding='latin-1'
            )
            df_raw.columns = [c.strip() for c in df_raw.columns]

            df, features = self._preprocess(df_raw)

            # Nadir sınıfları birleştir (≥10 örnek yok → 'Other')
            df = self._consolidate_rare_purposes(df, min_samples=10)

            # 1 örnekli sınıfları çıkar (kalibrasyon için minimum 2 gerekli)
            df = df[df.groupby('Purpose')['Purpose'].transform('count') > 1]

            X = df[features]
            y = self.label_encoder.fit_transform(df['Purpose'].astype(str))

            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42, stratify=y
            )

            class_weights = self._compute_class_weights(y_train, self.label_encoder)

            best_model = RandomForestClassifier(
                n_estimators=300,  # Daha fazla ağaç → daha kararlı tahmin
                class_weight=class_weights,  # Kök-ters ağırlık (dominant sınıf baskısı)
                max_features='sqrt',  # Her ağaçta rastgele özellik alt kümesi
                min_samples_leaf=3,  # Çok nadir sınıflara aşırı uydurma önler
                random_state=42
            )
            best_model.fit(X_train, y_train)

            def _roc_auc(y_prob_):
                try:
                    return roc_auc_score(
                        y_test, y_prob_, multi_class='ovr', average='weighted',
                        labels=np.arange(len(self.label_encoder.classes_))
                    )
                except Exception:
                    return 0.0

            # Kalibrasyon
            train_class_counts = np.bincount(y_train)
            min_train_count = int(train_class_counts[train_class_counts > 0].min())
            calibration_applied = False
            self.model = best_model

            if min_train_count >= 2:
                cv_folds = min(3, min_train_count)
                try:
                    calibrated = CalibratedClassifierCV(best_model, method='sigmoid', cv=cv_folds)
                    calibrated.fit(X_train, y_train)
                    self.model = calibrated
                    calibration_applied = True
                except Exception as e:
                    print(f">>> Kalibrasyon uygulanamadı, ham model kullanılıyor: {e}")

            y_pred = self.model.predict(X_test)
            y_prob = self.model.predict_proba(X_test)

            metrics = {
                "accuracy": accuracy_score(y_test, y_pred),
                "f1_score": f1_score(y_test, y_pred, average='weighted'),
                "roc_auc": _roc_auc(y_prob),
                "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
                "classes": self.label_encoder.classes_.tolist(),
                "feature_importance": dict(zip(features, best_model.feature_importances_.tolist())),
                "classification_report": classification_report(y_test, y_pred, output_dict=True),
                "sample_size": len(df),
                "calibration_applied": calibration_applied,
                "timestamp": datetime.now().isoformat()
            }

            with open(self.metrics_path, "w") as f:
                json.dump(metrics, f)

            # Kümeleme ve Anomali Tespiti
            X_scaled = self.scaler.fit_transform(X)
            cluster_model = GaussianMixture(
                n_components=5,
                covariance_type='diag',
                n_init=5,  # 5 farklı başlangıçla en iyisini seç
                random_state=42
            ).fit(X_scaled)

            iso_forest = IsolationForest(contamination=0.03, random_state=42).fit(X_scaled)
            lof = LocalOutlierFactor(
                n_neighbors=20, contamination=0.03, novelty=True
            ).fit(X_scaled)

            self.regime_map = self._build_regime_map(cluster_model)
            self.cluster_model = cluster_model
            self.iso_forest = iso_forest
            self.lof = lof

            joblib.dump(
                (self.model, self.label_encoder, self.scaler,
                 cluster_model, iso_forest, lof, self.regime_map),
                self.model_path
            )

            acc = metrics['accuracy'] * 100
            classes_str = ", ".join(self.label_encoder.classes_.tolist())
            return (f"Model Başarıyla Eğitildi. Doğruluk: %{acc:.1f} | "
                    f"Sınıflar: {classes_str}")

        except Exception as e:
            return f"Eğitim Hatası: {str(e)}"

    def ensure_models_loaded(self):
        """Modeller bellekte yoksa diskten yükler."""
        if (self.model is not None and self.cluster_model is not None
                and self.iso_forest is not None and self.lof is not None):
            return True
        if not self.model_path.exists():
            print(">>> HATA: Model dosyası bulunamadı! Lütfen önce /ssa/train yapın.")
            return False
        try:
            loaded_data = joblib.load(self.model_path)
            if len(loaded_data) == 7:
                (self.model, self.label_encoder, self.scaler, self.cluster_model,
                 self.iso_forest, self.lof, self.regime_map) = loaded_data
            else:
                (self.model, self.label_encoder, self.scaler,
                 self.cluster_model, self.iso_forest, self.lof) = loaded_data
                self.regime_map = self._build_regime_map(self.cluster_model)
            print(">>> Modeller diskten başarıyla yüklendi.")
            return True
        except Exception as e:
            print(f">>> Modeller yüklenirken hata: {e}")
            return False

    def analyze_all_satellites(self):
        """Eğitilmiş modelleri kullanarak canlı TLE verilerini analiz eder."""
        if not self.ensure_models_loaded():
            return 0

        ucs_df = pd.read_csv(
            self.data_path, sep=';', on_bad_lines='skip',
            low_memory=False, encoding='latin-1'
        )
        ucs_df.columns = [c.strip() for c in ucs_df.columns]
        ucs_df['NORAD Number'] = pd.to_numeric(ucs_df['NORAD Number'], errors='coerce')
        country_lookup = (ucs_df.dropna(subset=['NORAD Number'])
                          .set_index('NORAD Number')['Country of Operator/Owner']
                          .to_dict())

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

                incl = float(line2[8:16])
                ecc = float("0." + line2[26:33].strip())
                mm = float(line2[52:63])  # mean motion (devir/gün)

                period_min = 1440.0 / mm
                semi_major = (398600.44 / ((mm * 2 * np.pi / 86400) ** 2)) ** (1 / 3)
                perigee = semi_major * (1 - ecc) - 6378.137
                apogee = semi_major * (1 + ecc) - 6378.137
                alt = (perigee + apogee) / 2
                bstar = tle_to_satrec(line1, line2).bstar

                input_raw = np.array([[incl, ecc, period_min, perigee, apogee]])
                scaled = self.scaler.transform(input_raw)

                cat = self.label_encoder.inverse_transform(self.model.predict(input_raw))[0]
                conf = float(np.max(self.model.predict_proba(input_raw)))
                cluster_id = int(self.cluster_model.predict(scaled)[0])

                is_anomaly_if = self.iso_forest.predict(scaled)[0] == -1
                is_anomaly_lof = self.lof.predict(scaled)[0] == -1
                is_anomaly = 1 if (is_anomaly_if or is_anomaly_lof) else 0

                # Sönümlenme riski
                if alt < 350 and bstar > 0.0005:
                    decay_risk = "YÜKSEK"
                elif alt < 400:
                    decay_risk = "ORTA"
                else:
                    decay_risk = "DÜŞÜK"

                norad_id = int(line2[2:7].strip())
                country = country_lookup.get(norad_id, "Bilinmiyor")

                cur.execute("""
                    UPDATE satellite_intelligence
                    SET predicted_category=?, confidence=?, cluster_id=?, is_anomaly=?,
                        predicted_country=?, decay_risk=?, predicted_at=?
                    WHERE sat_id=?
                """, (cat, conf, cluster_id, is_anomaly, country, decay_risk,
                      datetime.now(timezone.utc).isoformat(), sid))

                if cur.rowcount == 0:
                    cur.execute("""
                        INSERT INTO satellite_intelligence
                        (sat_id, predicted_category, confidence, cluster_id, is_anomaly,
                         predicted_country, decay_risk, predicted_at)
                        VALUES (?,?,?,?,?,?,?,?)
                    """, (sid, cat, conf, cluster_id, is_anomaly, country, decay_risk,
                          datetime.now(timezone.utc).isoformat()))

                count += 1
            except Exception as e:
                print(f"[SSA ERROR] {sid} {name}: {e}")
                continue

        conn.commit()
        conn.close()
        return count

    def get_metrics(self):
        if self.metrics_path.exists():
            with open(self.metrics_path, "r") as f:
                return json.load(f)
        return None

    def get_pending_classification_count(self):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM raw_tles WHERE id NOT IN (SELECT sat_id FROM satellite_intelligence)")
        pending = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM raw_tles")
        total = cur.fetchone()[0]
        conn.close()
        return {"pending": pending, "total": total}

    def get_regime_heatmap_data(self):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT r.line2, si.cluster_id
            FROM raw_tles r
            INNER JOIN satellite_intelligence si ON si.sat_id = r.id
        """)
        data = []
        for line2, cluster_id in cur.fetchall():
            try:
                incl = float(line2[8:16])
                mm = float(line2[52:63])
                alt = ((398600.44 / ((mm * 2 * np.pi / 86400) ** 2)) ** (1 / 3)) - 6378.137
                if 200 < alt < 42000:
                    data.append({
                        "x": round(incl, 1),
                        "y": round(alt, -1),
                        "cluster_id": cluster_id
                    })
            except Exception:
                continue
        conn.close()
        return data


ssa_service = SSAService()
