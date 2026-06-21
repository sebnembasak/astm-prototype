import sqlite3
from typing import List, Optional, Dict, Any, Tuple
from backend.models.db import get_conn
from ingest.tle_fetcher import fetch_and_store
from processing.propagator import tle_to_satrec, orbit_params_from_tle
from ground_scheduling_config import (
    REFERENCE_ORBIT_ALTITUDE_KM,
    REFERENCE_ORBIT_INCLINATION_DEG,
    ORBIT_FILTER_INCLINATION_RANGE_DEG,
    ORBIT_FILTER_ALTITUDE_RANGE_KM,
)


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

    def get_satellites_by_orbit_profile(
            self,
            limit: int = 100,
            inclination_range_deg: Tuple[float, float] = ORBIT_FILTER_INCLINATION_RANGE_DEG,
            altitude_range_km: Tuple[float, float] = ORBIT_FILTER_ALTITUDE_RANGE_KM,
            target_altitude_km: float = REFERENCE_ORBIT_ALTITUDE_KM,
            target_inclination_deg: float = REFERENCE_ORBIT_INCLINATION_DEG,
    ) -> List[Dict[str, Any]]:
        """
        DB'deki tüm TLE kataloğundan, verilen inklinasyon/irtifa bandına
        (varsayılan: 525km/97.5° SSO referans profiline yakın LEO polar/SSO
        bandı) düşen GERÇEK nesneleri döner; alakasız debris/ISS gibi farklı
        yörünge ailelerini eler. Bant içindekiler, hedef profile (irtifa +
        inklinasyon, normalize edilmiş öklid uzaklığı) en yakın olandan en
        uzağa sıralanır, böylece N istendiğinde en temsili N nesne seçilir
        (alfabetik/rastgele değil).
        """
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, sat_name, epoch, source, fetched_at, line1, line2 FROM raw_tles")
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()

        inc_min, inc_max = inclination_range_deg
        alt_min, alt_max = altitude_range_km

        candidates = []
        for row in rows:
            try:
                inc_deg, alt_km = orbit_params_from_tle(row["line1"], row["line2"])
            except Exception:
                continue
            if not (inc_min <= inc_deg <= inc_max and alt_min <= alt_km <= alt_max):
                continue
            distance = (
                ((alt_km - target_altitude_km) / (alt_max - alt_min)) ** 2
                + ((inc_deg - target_inclination_deg) / (inc_max - inc_min)) ** 2
            )
            row["inclination_deg"] = inc_deg
            row["altitude_km"] = alt_km
            candidates.append((distance, row))

        candidates.sort(key=lambda pair: pair[0])
        return [row for _, row in candidates[:limit]]

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

    def get_tle_history(self, sat_id: int) -> List[Dict[str, Any]]:
        """
        Bir uydunun arşivlenmiş geçmiş TLE'lerini + güncel TLE'sini epoch'a göre
        artan sırada döner. Manevra tespiti (Faz 3) bu zaman serisini ardışık
        epoch'lar arasındaki orbital element farkını incelemek için kullanacak.
        """
        sat = self.get_satellite_by_id(sat_id)
        if not sat:
            return []

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT norad_id, sat_name, line1, line2, epoch, source, fetched_at, archived_at
            FROM tle_history
            WHERE norad_id = ?
            ORDER BY epoch ASC
        """, (sat["norad_id"],))
        history = [dict(row) for row in cur.fetchall()]
        conn.close()

        # Güncel TLE'yi de zaman serisinin son elemanı olarak ekle
        history.append({
            "norad_id": sat["norad_id"],
            "sat_name": sat["sat_name"],
            "line1": sat["line1"],
            "line2": sat["line2"],
            "epoch": sat["epoch"],
            "source": sat["source"],
            "fetched_at": sat["fetched_at"],
            "archived_at": None,
        })
        return history

    def get_satrec_by_id(self, sat_id: int):
        """Hesaplamalar için doğrudan sgp4 Satrec nesnesi döner."""
        sat_data = self.get_satellite_by_id(sat_id)
        if not sat_data:
            return None
        return tle_to_satrec(sat_data["line1"], sat_data["line2"])


# Singleton instance
tle_service = TleService()
