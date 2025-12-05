import sqlite3
from typing import List, Optional, Dict, Any
from backend.models.db import get_conn
from ingest.tle_fetcher import fetch_and_store
from processing.propagator import tle_to_satrec


class TleService:

    def update_tles_from_source(self) -> int:
        """Celestrak veya tanımlı kaynaktan TLE verilerini çeker ve DB'yi günceller."""
        count = fetch_and_store()
        return count

    def get_all_satellites(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Kayıtlı uyduların listesini döner."""
        conn = get_conn()
        cur = conn.cursor()

        query = "SELECT id, sat_name, epoch, source, fetched_at, line1, line2 FROM raw_tles ORDER BY sat_name LIMIT ?"

        cur.execute(query, (limit,))
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_total_count(self) -> int:
        """Veritabanındaki toplam uydu sayısını döner."""
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM raw_tles")
            res = cur.fetchone()
            return res[0] if res else 0
        except Exception:
            return 0
        finally:
            conn.close()

    def search_satellites(self, query: str) -> List[Dict[str, Any]]:
        """İsme göre uydu arar"""
        conn = get_conn()
        cur = conn.cursor()

        sql = """
            SELECT id, sat_name, line1, line2, epoch, source 
            FROM raw_tles 
            WHERE sat_name LIKE ? 
            LIMIT 50
        """

        cur.execute(sql, (f"%{query}%",))
        rows = cur.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_satellite_by_id(self, sat_id: int) -> Optional[Dict[str, Any]]:
        """ID'ye göre tek bir uydu verisini döner."""
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM raw_tles WHERE id = ?", (sat_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        return None

    def get_satrec_by_id(self, sat_id: int):
        """Hesaplamalar için doğrudan sgp4 Satrec nesnesi döner."""
        sat_data = self.get_satellite_by_id(sat_id)
        if not sat_data:
            return None
        return tle_to_satrec(sat_data["line1"], sat_data["line2"])


# Singleton instance
tle_service = TleService()
