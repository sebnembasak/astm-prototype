import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ingest.tle_fetcher import fetch_and_store
from backend.models.db import get_conn
from processing.propagator import tle_to_satrec
from processing.propagate_wrapper import propagate_satrec_single
from processing.pruner import prune_pairs
from processing.conjunction import compute_conjunction_for_pair
from datetime import datetime, timezone, timedelta

fetch_and_store()

conn = get_conn()
cur = conn.cursor()
cur.execute("SELECT id, sat_name, line1, line2 FROM raw_tles WHERE sat_name LIKE '%ISS%' OR sat_name LIKE '%ZARYA%' LIMIT 2")
rows = cur.fetchall()
if len(rows) < 2:
    print("En az 2 uydu bulunmalı, seçiminizi değiştirebilirsiniz")
    exit(1)

satrecs = []
states_map = {}
now = datetime.now(timezone.utc)
for row in rows:
    sat = tle_to_satrec(row["line1"], row["line2"])
    r = propagate_satrec_single(sat, now)
    r_f = propagate_satrec_single(sat, now + timedelta(seconds=1))
    v = (r_f - r) / 1.0
    satrecs.append((row["id"], sat))
    states_map[row["id"]] = (r, v)

pairs = prune_pairs({k: v[0] for k, v in states_map.items()}, radius_km=1000.0)
print("candidate pairs:", pairs)

for a,b in pairs:
    sat1 = next(x[1] for x in satrecs if x[0]==a)
    sat2 = next(x[1] for x in satrecs if x[0]==b)
    r1, v1 = states_map[a]
    r2, v2 = states_map[b]
    conj = compute_conjunction_for_pair(sat1, sat2, now, r1, v1, r2, v2, propagate_satrec_single, analytic_window_sec=3600.0)
    print("Conjunction:", conj)
