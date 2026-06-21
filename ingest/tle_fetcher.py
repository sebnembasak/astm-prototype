import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime, timedelta
from typing import List, Tuple
import httpx
from backend.models.db import get_conn, init_db

# URL yapısı: gp.php?GROUP=<istenen grup>&FORMAT=tle
CELESTRAK_GROUPS = {
    "stations": "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle",
    "visual":   "https://celestrak.org/NORAD/elements/gp.php?GROUP=visual&FORMAT=tle",
    "debris":   "https://celestrak.org/NORAD/elements/gp.php?GROUP=debris&FORMAT=tle",
    # "resource" (Landsat/Sentinel/SCD tipi yer gözlem uyduları) ağırlıklı
    # olarak güneş-senkron (SSO) polar yörüngede; ground-scheduling senaryo
    # motorunun Hello Space'in 525km SSO profiline yakın gerçek nesne araması
    # için ana havuz budur (bkz. service/tle_service.get_satellites_by_orbit_profile).
    "resource":  "https://celestrak.org/NORAD/elements/gp.php?GROUP=resource&FORMAT=tle",
}


def fetch_tle_text(url: str) -> str:
    # Belli bir istek sayısından sonra (timeout'a rağmen) hata verdiğinden geçici olarak eklenmiştir
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 (ASTM-Prototype-Project/1.0)',
    }
    resp = httpx.get(url, headers=headers, timeout=20.0)
    resp.raise_for_status()
    return resp.text


def parse_tle_block(text: str) -> List[Tuple[str, str, str]]:
    """
    Her bir blok 3 satırdan oluşuyor: isim, satır1, satır2 şeklinde.
    Bu bloklar ayrıştırılarak işlenebilir hale getirilir.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
    blocks = []
    i = 0
    while i + 2 < len(lines):
        name = lines[i]
        line1 = lines[i + 1]
        line2 = lines[i + 2]
        blocks.append((name, line1, line2))
        i += 3
    return blocks


def parse_epoch(line1: str) -> str:
    try:
        epoch_str = line1[18:32].strip()
        yy = int(epoch_str[:2])
        year = 2000 + yy if yy < 57 else 1900 + yy
        day_frac = float(epoch_str[2:])
        dt = datetime(year, 1, 1) + timedelta(days=day_frac - 1)
        return dt.isoformat()
    except Exception:
        return ""


def save_tles(blocks: List[Tuple[str, str, str]], source: str = "celestrak"):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    for name, line1, line2 in blocks:
        norad_id = int(line1[2:7])
        epoch = parse_epoch(line1)

        # Mevcut kayıt farklı bir epoch'a sahipse (= gerçekten yeni bir yörünge
        # tahmini geldi), üzerine yazmadan önce eski hâlini geçmişe arşivle.
        # Aynı epoch tekrar geldiyse (refresh ama yeni veri yok) arşivlemiyoruz,
        # yoksa tle_history anlamsız tekrar kayıtlarla şişer.
        cur.execute("SELECT sat_name, line1, line2, epoch, source, fetched_at FROM raw_tles WHERE norad_id = ?", (norad_id,))
        existing = cur.fetchone()
        if existing and existing["epoch"] != epoch:
            cur.execute("""
                INSERT INTO tle_history (norad_id, sat_name, line1, line2, epoch, source, fetched_at, archived_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (norad_id, existing["sat_name"], existing["line1"], existing["line2"],
                  existing["epoch"], existing["source"], existing["fetched_at"], now))

        cur.execute("""
            INSERT INTO raw_tles (norad_id, sat_name, line1, line2, epoch, source, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(norad_id) DO UPDATE SET
                sat_name=excluded.sat_name,
                line1=excluded.line1,
                line2=excluded.line2,
                epoch=excluded.epoch,
                fetched_at=excluded.fetched_at
        """, (norad_id, name, line1, line2, epoch, source, now))
    conn.commit()
    conn.close()


def fetch_and_store(url: str = None) -> int:
    """url verilirse sadece o kaynaktan, verilmezse tüm gruplardan (stations+active+debris) çeker."""
    init_db()
    items = [("celestrak", url)] if url else [(name, u) for name, u in CELESTRAK_GROUPS.items()]
    total = 0
    for group_name, u in items:
        try:
            text = fetch_tle_text(u)
            blocks = parse_tle_block(text)
            save_tles(blocks, source=group_name)
            total += len(blocks)
        except Exception as e:
            print(f"Grup alınamadı ({u}): {e}")
    return total


if __name__ == "__main__":
    n = fetch_and_store()
    print(f"{n} adet TLE verisi kaydedildi.")
