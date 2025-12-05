import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ingest.tle_fetcher import parse_tle_block

def test_parse_sample_block():
    txt = "ISS (ZARYA)\n1 25544U 98067A   25324.12345678  .00001234  00000-0  12345-4 0  9991\n2 25544  51.6425  21.1234 0009223 325.1234 123.4567 15.50000001  12345\n"
    blocks = parse_tle_block(txt)
    assert len(blocks) == 1
    name, l1, l2 = blocks[0]
    assert "ISS" in name
    assert l1.startswith("1 ")
    assert l2.startswith("2 ")
