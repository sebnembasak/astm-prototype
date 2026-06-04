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

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Veritabanı tabloları başarıyla oluşturuldu/güncellendi.")
