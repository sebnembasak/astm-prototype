import sqlite3
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from backend.models.db import get_conn
from service.tle_service import tle_service
from processing.propagator import tle_to_satrec
from processing.propagate_wrapper import propagate_satrec_single
from processing.pruner import prune_pairs
from processing.conjunction import compute_conjunction_for_pair


class ConjunctionService:
    """
    Bu servis, tüm Çarpışma Analizi (Conjunction Assessment) sürecini yönetir.
    Veriyi alır, işler, filtreler ve sonucu veritabanına yazar.
    """

    def run_conjunction_screening(self, analysis_start_time: datetime = None, duration_hours: int = 2) -> Dict[
        str, int]:
        """
        Ana Tarama Fonksiyonu (Screening Loop).
            1. Aktif uyduları çeker.
            2. KD-Tree ile aday çiftleri bulur (Broad Phase).
            3. SGP4 ve Optimizasyon ile detaylı analiz yapar (Narrow Phase).
            4. Riskli durumları veritabanına kaydeder.
        """

        if analysis_start_time is None:
            # analiz başlangıç zamanı belirtilmemişse şu anı al utc
            analysis_start_time = datetime.now(timezone.utc)

        # Aktif uyduları getir
        satellites = tle_service.get_all_satellites(limit=5000)
        if len(satellites) < 2:
            return {"status": "Yeterli uydu yok", "processed_pairs": 0, "alerts_saved": 0}

        satrecs = {}  # SGP4 nesnelerini tutacak
        states_map = {}  # uyduların t0 anındaki konum/hız verilerini tutacak

        # Başlangıç Durumlarının Hesaplanması
        # KD-Tree kurabilmek için tüm uyduların t0 anındaki konumlarını bilmemiz gerekir
        for sat in satellites:
            sid = sat["id"]
            try:
                st = tle_to_satrec(sat["line1"], sat["line2"])
                satrecs[sid] = st
                r = propagate_satrec_single(st, analysis_start_time)
                r_f = propagate_satrec_single(st, analysis_start_time + timedelta(seconds=1))
                v = (r_f - r) / 1.0
                states_map[sid] = (r, v)
            except Exception:
                continue

        if len(states_map) < 2:
            return {"status": "Yetersiz sayıda veri", "processed_pairs": 0, "alerts_saved": 0}

        # Budama - Pruning Aşaması - Broad Phase Detection
        # KD-Tree kullanılacak
        ANALYTIC_WINDOW = 7200.0  # 2 saatlik bir pencereye bakacağız
        RADIUS_KM = 300.0  # Sadece birbirine 300km yakın olanlar incelenecek
        COLLISION_SAVE_THRESHOLD_KM = 150.0  # 150 km den uzaksa veritabanına kaydedilmeyecek

        # sadece konum verilerini (r) alarak KD-Tree ye veriyoruz
        positions_map = {k: v[0] for k, v in states_map.items()}

        # prune_pairs fonksiyonu bize sadece riskli olabilecek çiftleri (id1, id2) döner
        # Örn: 5000 uydu için 12.5 milyon çift yerine sadece 500 çift döner.
        candidate_pairs = prune_pairs(positions_map, radius_km=RADIUS_KM)

        conn = get_conn()
        cur = conn.cursor()

        # Demo amaçlı her taramada eski alarmları temizliyoruz
        # Gerçek bir uygulamada burası 'archive' tablosuna taşınmalıdır
        cur.execute("DELETE FROM conjunction_alerts")
        conn.commit()
        saved_count = 0

        # Aday çiftler üzerinde detaylı analiz, Narrow Phase
        # sadece filtrelenmiş aday çiftler üzerinde SGP4 ve Optimizasyon çalıştırılacak
        for id1, id2 in candidate_pairs:
            if id1 not in satrecs or id2 not in satrecs:
                continue

            sat1 = satrecs[id1]
            sat2 = satrecs[id2]
            r1, v1 = states_map[id1]
            r2, v2 = states_map[id2]

            try:
                # Analitik Tahmin -> SGP4 Refinement -> Docking Kontrolü
                conj = compute_conjunction_for_pair(
                    sat1, sat2,
                    analysis_start_time,
                    r1, v1, r2, v2,
                    propagate_satrec_single,
                    analytic_window_sec=ANALYTIC_WINDOW
                )
            except Exception as e:
                print(f"Error computing pair {id1}-{id2}: {e}")
                continue

            if conj is None:
                continue

            # Sonuçların Kaydedilmesi (Persistence)
            should_save = False
            # DOCKING: Kenetlenme manevralarını kaydet (arayüzde ayrı bölümü açıldığı için)
            if conj.event_type == "DOCKING":
                should_save = True
            elif conj.event_type == "COLLISION":
                # Score > 0 demek belirli bir risk var demek
                # Ayrıca mesafe eşiğinin (150 km) altında olmalı
                if conj.score > 0 and conj.miss_distance_km < COLLISION_SAVE_THRESHOLD_KM:
                    should_save = True

            if should_save:
                cur.execute("""
                    INSERT INTO conjunction_alerts 
                    (sat1_id, sat2_id, tca, miss_distance_km, rel_velocity_km_s, score, event_type, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    id1, id2,
                    conj.tca.isoformat(),
                    conj.miss_distance_km,
                    conj.rel_velocity_km_s,
                    conj.score,
                    conj.event_type,
                    datetime.now(timezone.utc).isoformat()
                ))
                saved_count += 1

        conn.commit()
        conn.close()

        # APIye dönülecek özet rapor
        return {"processed_pairs": len(candidate_pairs), "alerts_saved": saved_count}

    def get_alerts(self, limit: int = 20, event_type: str = "COLLISION") -> List[Dict[str, Any]]:
        """
        Veritabanından alarmları çeker.
        SQL JOIN kullanarak Satellite tablosundan uydu isimlerini de getirir.
        """
        conn = get_conn()
        cur = conn.cursor()
        query = """
            SELECT 
                a.id, a.sat1_id, a.sat2_id, a.tca, a.miss_distance_km, a.rel_velocity_km_s, a.score, a.event_type, a.created_at,
                s1.sat_name as sat1_name, s2.sat_name as sat2_name
            FROM conjunction_alerts a
            JOIN raw_tles s1 ON a.sat1_id = s1.id
            JOIN raw_tles s2 ON a.sat2_id = s2.id
            WHERE a.event_type = ? 
            ORDER BY a.score DESC, a.tca ASC
            LIMIT ?
        """
        cur.execute(query, (event_type, limit))
        rows = cur.fetchall()
        conn.close()
        # Row objelerini dictionarye çevirerek JSON uyumlu hale getir
        return [dict(row) for row in rows]


# Singleton instance (Servis tek bir örnek olarak başlatılır)
conjunction_service = ConjunctionService()
