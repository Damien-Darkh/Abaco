# -*- coding: utf-8 -*-
"""Saved settings (Phase 9). Run: python3 tests/test_settings_store.py   (no Revit needed)"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)

from abaco import pipeline as P
from abaco import settings_store as SS
from abaco import appearance as AP
from abaco import filters
from abaco.records import K_WIDTH, K_TYPE_MARK
from test_pipeline import doors, settings, fs

CAT = u"OST_Doors"
OUT = {"tableName": u"Abaco Doors", "excelPath": u"C:\\x\\a.xlsx", "titleBlock": u"TB : A1",
       "prefix": u"AM", "pageHeight": u"490"}
DEF_OUT = {"tableName": u"default", "excelPath": u"d.xlsx", "titleBlock": None,
           "prefix": u"AM", "pageHeight": u"490"}


def tmp_file(text=None):
    path = os.path.join(tempfile.mkdtemp(), "tables.json")
    if text is not None:
        with open(path, "w") as f:
            f.write(text)
    return path


def fixture():
    rs = doors()
    return rs, settings(rs)


def known(rs):
    return set(f.key for f in rs.fields)


# ----------------------------------------------------------------------------- paths and keys
def test_store_key_and_default_paths():
    assert SS.store_key(CAT, "takeoff") == u"OST_Doors|takeoff"
    assert SS.default_path(u"C:\\A", pyrevit=True).endswith(os.path.join("pyRevit", "Abaco", "tables.json"))
    assert SS.default_path(u"C:\\A", pyrevit=False).endswith(os.path.join("Abaco", "tables.json"))
    assert "2025" not in SS.default_path(u"C:\\A", pyrevit=False)       # never per Revit year


# ------------------------------------------------------------------------------------- file I/O
def test_missing_file_is_empty_and_silent():
    store, msg = SS.read_file(os.path.join(tempfile.mkdtemp(), "none.json"))
    assert store["saved"] == {} and msg == u""


def test_round_trip_restores_everything():
    rs, s = fixture()
    s["title"] = u"Doors check"
    fs(s, K_WIDTH)["align"] = "right"
    s["levels"] = [P.sort_setting(K_TYPE_MARK, "desc", gap=True)]
    s["rowNumbers"] = {"on": True, "heading": u"#"}
    s["custom"] = [{"key": u"calc:1", "name": u"Door Area", "formula": u"{@WIDTH} * {@HEIGHT}"}]
    s["filter"] = {"match": "any", "conditions": [{"key": K_WIDTH, "op": "gt", "value": u"0.5"}]}
    path = tmp_file()

    store = SS.empty_store()
    SS.put_saved(store, CAT, "schedule", s, OUT)
    SS.write_file(path, store)

    store2, msg = SS.read_file(path)
    assert msg == u""
    defaults = P.default_settings(rs, "schedule", u"", custom=[])
    got, out, notes = SS.restore(SS.get_saved(store2, CAT, "schedule"), defaults, DEF_OUT, known(rs))

    assert got["title"] == u"Doors check"
    assert got["fields"] == s["fields"]
    assert got["levels"] == s["levels"]
    assert got["custom"] == s["custom"]
    assert got["rowNumbers"] == s["rowNumbers"]
    assert got["filter"] == filters.normalize_settings(s["filter"])
    assert got["appearance"] == s["appearance"]
    assert out == OUT and notes == []


def test_corrupt_file_is_moved_aside():
    path = tmp_file("{not json")
    store, msg = SS.read_file(path)
    assert store["saved"] == {} and u"could not be read" in msg
    assert os.path.exists(path + SS.ASIDE_SUFFIX) and not os.path.exists(path)


def test_unexpected_layout_is_moved_aside():
    path = tmp_file("[1, 2]")
    store, msg = SS.read_file(path)
    assert store["saved"] == {} and u"unexpected layout" in msg
    assert os.path.exists(path + SS.ASIDE_SUFFIX)


def test_newer_version_blocks_saving_and_keeps_the_file():
    text = u'{"v": 2, "saved": {}}'
    path = tmp_file(text)
    store, msg = SS.read_file(path)
    assert store.get("blocked") is True and u"newer version" in msg
    try:
        SS.write_file(path, store)
        assert False, "saving should be refused"
    except IOError:
        pass
    with open(path) as f:
        assert '"v": 2' in f.read()


def test_write_leaves_no_temporary_file():
    path = tmp_file()
    SS.write_file(path, SS.empty_store())
    assert os.path.exists(path) and not os.path.exists(path + ".tmp")


# ---------------------------------------------------------------------------------- restore
def test_no_saved_entry_gives_defaults():
    rs, _ = fixture()
    defaults = P.default_settings(rs, "schedule", u"")
    got, out, notes = SS.restore(None, defaults, DEF_OUT, known(rs))
    assert got == defaults and out == DEF_OUT and notes == []


def test_bad_values_fall_back_to_defaults():
    rs, _ = fixture()
    defaults = P.default_settings(rs, "schedule", u"")
    saved = {"settings": {"fields": [
                {"key": K_WIDTH, "align": "sideways", "calc": "summary", "decimals": 9,
                 "widthMm": -3, "include": "yes", "heading": 5},
                {"no_key": 1}, "junk"]},
             "output": {"titleBlock": 5}}
    got, out, notes = SS.restore(saved, defaults, DEF_OUT, known(rs))
    assert len(got["fields"]) == 1
    w = got["fields"][0]
    assert (w["align"], w["calc"], w["decimals"], w["widthMm"], w["include"], w["heading"]) == \
           ("left", "none", None, None, True, None)
    assert any(u"2 saved field entries" in n for n in notes)
    assert out["titleBlock"] is None


def test_missing_field_is_kept_and_reported():
    rs, s = fixture()
    s["fields"].append(P.field_setting(u"GONE", heading=u"Old"))
    store = SS.empty_store()
    SS.put_saved(store, CAT, "schedule", s, OUT)
    defaults = P.default_settings(rs, "schedule", u"")
    got, _, notes = SS.restore(SS.get_saved(store, CAT, "schedule"), defaults, DEF_OUT, known(rs))
    assert u"GONE" in [f["key"] for f in got["fields"]]
    assert any(u"not in this project" in n and P.MARK_NOT_IN_PROJECT in n for n in notes)


def test_defaults_keep_custom_and_turn_row_numbers_off():
    rs, _ = fixture()
    custom = [{"key": u"calc:1", "name": u"Door Area", "formula": u"{@WIDTH}"}]
    d = P.default_settings(rs, "schedule", u"", custom=custom)
    assert d["custom"] == custom and d["rowNumbers"]["on"] is False


def test_saved_custom_survives_restore():
    rs, s = fixture()
    s["custom"] = [{"key": u"calc:1", "name": u"Door Area", "formula": u"{@WIDTH}"}]
    store = SS.empty_store()
    SS.put_saved(store, CAT, "schedule", s, OUT)
    got, _, _ = SS.restore(SS.get_saved(store, CAT, "schedule"),
                           P.default_settings(rs, "schedule", u""), DEF_OUT, known(rs))
    assert got["custom"] == s["custom"]


# ----------------------------------------------------------------------- missing-field marker
def test_missing_field_shows_marker_in_table():
    rs, s = fixture()
    s["fields"].append(P.field_setting(u"GONE", heading=u"Old"))
    res = P.build_table(rs, s)
    m = res.excel.to_matrix()
    assert m[1][-1] == u"Old"
    data = [r for r in m[2:] if any(r)]
    assert data and all(r[-1] == P.MARK_NOT_IN_PROJECT for r in data)
    assert any(u"GONE" in w or u"Old" in w for w in res.warnings)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for n, f in tests:
        f()
        print("ok   " + n)
    print("%d tests passed" % len(tests))