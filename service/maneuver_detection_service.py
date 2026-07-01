from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from backend.models.db import get_conn
from service.tle_service import tle_service
from processing.maneuver_detection import detect_maneuver


class ManeuverDetectionService:

    def detect_for_satellite(self, sat_id: int) -> List[Dict[str, Any]]:
        """
        Bir uydunun tle_history zaman serisindeki ardışık epoch çiftlerini
        tarar, manevra olarak işaretlenenleri (is_maneuver=True) dict olarak
        döner.
        """
        sat = tle_service.get_satellite_by_id(sat_id)
        if not sat:
            return []

        history = tle_service.get_tle_history(sat_id)
        results = []
        for tle_before, tle_after in zip(history, history[1:]):
            detection = detect_maneuver(tle_before, tle_after)
            if detection is None or not detection.is_maneuver:
                continue

            event = vars(detection).copy()
            event["norad_id"] = sat["norad_id"]
            event["sat_name"] = sat["sat_name"]
            results.append(event)

        return results

    def detect_all_satellites(self) -> int:
        """
        tle_history'de en az bir arşiv kaydı olan tüm uyduları tarar,
        tespit edilen manevraları maneuver_events tablosuna ekler.
        UNIQUE index sayesinde aynı çift tekrar taramada eklenmez.
        Eklenen yeni satır sayısını döner.
        """
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT norad_id FROM tle_history")
        norad_ids = [row["norad_id"] for row in cur.fetchall()]

        new_count = 0
        now = datetime.now(timezone.utc).isoformat()

        for norad_id in norad_ids:
            cur.execute("SELECT id FROM raw_tles WHERE norad_id = ?", (norad_id,))
            row = cur.fetchone()
            if not row:
                continue

            for event in self.detect_for_satellite(row["id"]):
                cur.execute("""
                    INSERT OR IGNORE INTO maneuver_events
                        (norad_id, sat_name, epoch_before, epoch_after, dt_hours,
                         delta_semi_major_km, delta_inclination_deg, delta_eccentricity,
                         velocity_residual_m_s, maneuver_type, confidence, estimated_dv_m_s,
                         detected_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event["norad_id"], event["sat_name"], event["epoch_before"], event["epoch_after"],
                    event["dt_hours"], event["delta_semi_major_km"], event["delta_inclination_deg"],
                    event["delta_eccentricity"], event["velocity_residual_m_s"], event["maneuver_type"],
                    event["confidence"], event["estimated_dv_m_s"], now
                ))
                if cur.rowcount > 0:
                    new_count += 1

        conn.commit()
        conn.close()
        return new_count

    def get_maneuver_events(self, sat_id: Optional[int] = None, limit: int = 50, page: int = 1) -> Dict[str, Any]:
        """maneuver_events tablosundan sayfalı döner; opsiyonel norad_id filtresi."""
        import math
        offset = (page - 1) * limit
        conn = get_conn()
        cur = conn.cursor()

        if sat_id is not None:
            sat = tle_service.get_satellite_by_id(sat_id)
            norad_id = sat["norad_id"] if sat else None
            cur.execute("SELECT COUNT(*) FROM maneuver_events WHERE norad_id = ?", (norad_id,))
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT * FROM maneuver_events WHERE norad_id = ? ORDER BY epoch_after DESC LIMIT ? OFFSET ?",
                (norad_id, limit, offset),
            )
        else:
            cur.execute("SELECT COUNT(*) FROM maneuver_events")
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT * FROM maneuver_events ORDER BY epoch_after DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )

        items = [dict(row) for row in cur.fetchall()]
        conn.close()
        return {"items": items, "total": total, "page": page, "limit": limit, "pages": math.ceil(total / limit) if limit else 1}


# Singleton instance
maneuver_detection_service = ManeuverDetectionService()
