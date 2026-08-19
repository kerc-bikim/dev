from app.services.earthworm_d import parse_earthworm_d, upsert_ring
from app.services.seed import SAFE_NAME
from app.services.startstop_file import parse_startstop, serialize_startstop, set_process_enabled
from app.services.status_parser import parse_status


SAMPLE = """
#
# header
#
Ring   STATUS_RING  128
Ring   WAVE_RING    1024

nMessageQueue  100
KillDelay      10

Process          "statmgr statmgr.d"
 Class/Priority    OTHER 0

# Process          "pick_ew pick_ew.d"
#  Class/Priority    OTHER 0
"""


def test_parse_toggle_roundtrip():
    doc = parse_startstop(SAMPLE)
    assert doc.rings[0][0] == "STATUS_RING"
    assert doc.process_named("statmgr").enabled is True
    assert doc.process_named("pick_ew").enabled is False
    set_process_enabled(doc, "pick_ew", True)
    text = serialize_startstop(doc)
    again = parse_startstop(text)
    assert again.process_named("pick_ew").enabled is True
    assert again.process_named("statmgr").enabled is True
    assert again.rings[0][0] == "STATUS_RING"


def test_earthworm_d_upsert():
    doc = parse_earthworm_d("Ring   WAVE_RING        1000\nModule   MOD_STATMGR        10\n")
    upsert_ring(doc, "STATUS_RING", 1040)
    names = [n for n, _k, _on in doc.rings()]
    assert "STATUS_RING" in names
    assert "WAVE_RING" in names


def test_safe_name():
    assert SAFE_NAME.match("pick_ew")
    assert not SAFE_NAME.match("../x")
    assert not SAFE_NAME.match("FLAG RING")


def test_status_parser():
    text = """
                    EARTHWORM SYSTEM STATUS
        Hostname-OS: testhost-Linux    Version: v8.0-web-stub
           Disk space: 18200000 KB available
           Ring  1 name/key/size:  STATUS_RING / 1040 / 128 kb
  Process Name      Process ID   Status     Class/Priority  Argument
  startstop           1001       Alive      OTHER 0
  statmgr             1002       Alive      OTHER 0         statmgr.d
"""
    snap = parse_status(text)
    assert snap.disk_kb == 18200000
    assert snap.rings[0]["name"] == "STATUS_RING"
    assert snap.rows[0].name == "startstop"
    assert snap.rows[1].pid == 1002
