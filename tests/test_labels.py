import unicodedata

import pytest

from facesort import labels
from facesort.errors import LabelError
from facesort.export import FaceInfo, LabelInfo
from tests.factories import World


def test_case_insensitive_key():
    assert labels.name_key("Ông A") == labels.name_key("ông a")


def test_nfc_nfd_same():
    nfd = unicodedata.normalize("NFD", "Ông A")
    assert nfd != "Ông A"
    assert labels.name_key(nfd) == labels.name_key("Ông A")
    assert labels.normalize(nfd) == "Ông A"


def test_whitespace_collapse():
    assert labels.normalize("  Ông   A \t") == "Ông A"


def test_forbidden_chars():
    assert labels.folder_name_for("Cô Lan / Chú Tư") == "Cô Lan _ Chú Tư"
    assert labels.folder_name_for('a<b>c:d"e|f?g*h\\i') == "a_b_c_d_e_f_g_h_i"


@pytest.mark.parametrize("n", ["CON", "con", "PRN", "NUL", "COM1", "lpt9", "AUX"])
def test_reserved(n):
    assert labels.folder_name_for(n).endswith("_")


def test_trailing_dot_and_space():
    assert labels.folder_name_for("Bà B...") == "Bà B"
    assert labels.folder_name_for("CON.") == "CON_"


@pytest.mark.parametrize("n", ["", "   ", "...", "_Khac", "_KHAC"])
def test_rejected(n):
    with pytest.raises(LabelError):
        labels.validate(n, "_Khac")


def test_get_or_create_dedup(tmp_path):
    w = World(tmp_path)
    a = w.label("Ông A")
    assert w.label("ông a") == a
    assert w.label("Ông  A") == a
    assert w.conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 1


def test_folder_collision_resolved(tmp_path):
    w = World(tmp_path)
    w.label("a:b")
    w.label("a/b")
    folders = [r[0] for r in w.conn.execute("SELECT folder_name FROM labels ORDER BY id")]
    assert folders == ["a_b", "a_b (2)"]


def test_rename_and_merge(tmp_path):
    w = World(tmp_path)
    a, b = w.label("Ông A"), w.label("Bà B")
    c = w.cluster("Bà B")
    assert labels.rename_label(w.conn, b, "Cô C", "_Khac") == b
    assert w.conn.execute("SELECT name FROM labels WHERE id=?", (b,)).fetchone()[0] == "Cô C"
    assert labels.rename_label(w.conn, b, "ông a", "_Khac") == a
    assert w.conn.execute("SELECT label_id FROM clusters WHERE id=?", (c,)).fetchone()[0] == a
    assert w.conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 1


def test_effective_label_rules():
    el = labels.effective_label_id
    assert el(False, None, False, 5) == 5
    assert el(False, 7, False, 5) == 7  # R5: gán tay thắng cụm
    assert el(True, 7, False, 5) is None  # R2
    assert el(False, 7, True, 5) is None
    assert el(False, None, None, None) is None


def test_faceinfo_unused_import_guard():
    assert FaceInfo(True, LabelInfo(1, "a", "a")).quality_ok
