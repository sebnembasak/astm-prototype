import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime
from typing import List, Tuple
import httpx
from backend.models.db import get_conn, init_db

# URL yapısı: gp.php?GROUP=<istenen grup>&FORMAT=tle
CELESTRAK_STATIONS = "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle"


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


def save_tles(blocks: List[Tuple[str, str, str]], source: str = "celestrak"):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    for name, line1, line2 in blocks:
        # Todo: ilerleyen sürümlerde bu gibi yerler enjeksiyon için daha güvenilir hale getirilecek
        cur.execute(
            "INSERT INTO raw_tles (sat_name, line1, line2, epoch, source, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name, line1, line2, "", source, now))
    conn.commit()
    conn.close()


def fetch_and_store(url: str = CELESTRAK_STATIONS):
    init_db()
    text = fetch_tle_text(url)
    blocks = parse_tle_block(text)
    save_tles(blocks)
    return len(blocks)


if __name__ == "__main__":
    n = fetch_and_store()
    print(f"{n} adet TLE verisi kaydedildi.")
