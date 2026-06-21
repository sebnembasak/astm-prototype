from pathlib import Path
import sqlite3

# Proje dizin yapısına göre veritabanı yolunu ayarla
DB_PATH = Path(__file__).resolve().parents[2] / "data" / "astm.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    curr = conn.cursor()

    # TLE Tablosu
    curr.execute("""
        CREATE TABLE IF NOT EXISTS raw_tles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            norad_id INTEGER,
            sat_name TEXT,
            line1 TEXT,
            line2 TEXT,
            epoch TEXT,
            source TEXT,
            fetched_at TEXT
        )
    """)
    # Migration: mevcut veritabanlarına norad_id sütunu ekle
    try:
        curr.execute("ALTER TABLE raw_tles ADD COLUMN norad_id INTEGER")
    except sqlite3.OperationalError:
        pass  # sütun zaten var
    # Partial index ON CONFLICT ile çalışmıyor; tam UNIQUE index gerekli.
    # SQLite NULL'ları distinct sayar, yani birden fazla NULL'a izin verir.
    curr.execute("DROP INDEX IF EXISTS idx_raw_tles_norad_id")
    curr.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_tles_norad_id
        ON raw_tles(norad_id)
    """)

    # Conjunction Alerts Tablosu
    # Varsayılan değer 'COLLISION'
    # Docking olayları için 'DOCKING' yazacağız
    curr.execute("""
        CREATE TABLE IF NOT EXISTS conjunction_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sat1_id INTEGER,
            sat2_id INTEGER,
            tca TEXT,
            miss_distance_km REAL,
            rel_velocity_km_s REAL,
            score REAL,
            event_type TEXT DEFAULT 'COLLISION', 
            created_at TEXT
        )
        """)

    curr.execute("""
        CREATE TABLE IF NOT EXISTS conjunction_alerts_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sat1_id INTEGER,
            sat2_id INTEGER,
            tca TEXT,
            miss_distance_km REAL,
            rel_velocity_km_s REAL,
            score REAL,
            event_type TEXT DEFAULT 'COLLISION',
            created_at TEXT,
            archived_at TEXT
        )
    """)

    # TLE Geçmişi: bir uydunun epoch'u değiştiğinde (yani yeni bir yörünge
    # tahmini geldiğinde) eski TLE buraya arşivlenir. Manevra tespiti (Faz 3)
    # için ardışık epoch'lar arasındaki orbital element farkına bakılacak.
    curr.execute("""
        CREATE TABLE IF NOT EXISTS tle_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            norad_id INTEGER,
            sat_name TEXT,
            line1 TEXT,
            line2 TEXT,
            epoch TEXT,
            source TEXT,
            fetched_at TEXT,
            archived_at TEXT
        )
    """)
    curr.execute("""
        CREATE INDEX IF NOT EXISTS idx_tle_history_norad_epoch
        ON tle_history(norad_id, epoch)
    """)

    # Manevra Tespiti (Faz 3): tle_history'deki ardışık epoch çiftleri arasında
    # SGP4 artık-hız (residual velocity) yöntemiyle tespit edilen manevralar.
    curr.execute("""
        CREATE TABLE IF NOT EXISTS maneuver_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            norad_id INTEGER,
            sat_name TEXT,
            epoch_before TEXT,
            epoch_after TEXT,
            dt_hours REAL,
            delta_semi_major_km REAL,
            delta_inclination_deg REAL,
            delta_eccentricity REAL,
            velocity_residual_m_s REAL,
            maneuver_type TEXT,
            confidence REAL,
            estimated_dv_m_s REAL,
            detected_at TEXT
        )
    """)
    curr.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_maneuver_events_unique
        ON maneuver_events(norad_id, epoch_before, epoch_after)
    """)

    curr.execute("""
        CREATE TABLE IF NOT EXISTS satellite_intelligence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sat_id INTEGER UNIQUE,
            predicted_category TEXT,
            predicted_country TEXT,
            confidence REAL,
            cluster_id INTEGER,
            is_anomaly INTEGER,
            decay_risk TEXT, 
            predicted_at TEXT,
            FOREIGN KEY (sat_id) REFERENCES raw_tles(id)
        )
    """)

    # Ground Station Scheduling & Capacity Planning (Faz 6)
    curr.execute("""
        CREATE TABLE IF NOT EXISTS ground_stations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            alt_km REAL DEFAULT 0.0,
            min_elevation_deg REAL DEFAULT 10.0,
            created_at TEXT
        )
    """)

    # Bir uydunun bir istasyon üzerinden hesaplanan geçiş penceresi (AOS/LOS).
    curr.execute("""
        CREATE TABLE IF NOT EXISTS pass_windows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sat_id INTEGER,
            station_id INTEGER,
            aos TEXT,
            los TEXT,
            max_elevation_deg REAL,
            duration_s REAL,
            computed_at TEXT,
            FOREIGN KEY (sat_id) REFERENCES raw_tles(id),
            FOREIGN KEY (station_id) REFERENCES ground_stations(id)
        )
    """)
    curr.execute("""
        CREATE INDEX IF NOT EXISTS idx_pass_windows_station_aos
        ON pass_windows(station_id, aos)
    """)

    # Bir senaryo koşusunun çizelgeleme çıktısı: hangi geçiş hangi istasyona
    # atandı (assigned=1) veya çakışmadan kaybedildi (assigned=0).
    curr.execute("""
        CREATE TABLE IF NOT EXISTS scheduling_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_label TEXT,
            sat_id INTEGER,
            station_name TEXT,
            aos TEXT,
            los TEXT,
            assigned INTEGER,
            created_at TEXT
        )
    """)
    curr.execute("""
        CREATE INDEX IF NOT EXISTS idx_scheduling_results_scenario
        ON scheduling_results(scenario_label)
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Veritabanı tabloları başarıyla oluşturuldu/güncellendi.")
