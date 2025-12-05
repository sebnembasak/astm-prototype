import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ingest.tle_fetcher import fetch_and_store
from backend.models.db import get_conn
from processing.propagator import tle_to_satrec, propagate_satrec
from datetime import datetime, timedelta, timezone

# TLE verilerini al
fetch_and_store()

# ISS TLE verisi üzerine bir örnek yapalım ('ISS' or 'ZARYA')
conn = get_conn()
cur = conn.cursor()
cur.execute(
    "SELECT id, sat_name, line1, line2 FROM raw_tles WHERE sat_name LIKE '%ISS%' OR sat_name LIKE '%ZARYA%' LIMIT 1")
row = cur.fetchone()
if row is None:
    print("ISS TLE'ler içerisinde bulunamadı")
    exit(1)
line1 = row["line1"]
line2 = row["line2"]

sat = tle_to_satrec(line1, line2)
now = datetime.now(timezone.utc)
times = [now + timedelta(seconds=i * 60) for i in range(0, 6)]  # 6 dakika, 1 dakikalık ritim
states = propagate_satrec(sat, times)
for st in states:
    print(st["time"].isoformat(), "r_km:", st["r_km"])
