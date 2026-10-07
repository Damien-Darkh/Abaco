# -*- coding: utf-8 -*-
"""Window state and preview geometry (Phase 4). Run: python3 tests/test_ui.py   (no Revit needed)"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)

from abaco.records import Field, K_FAMILY, K_WIDTH
from abaco import pipeline as P
from abaco import ui_state as US
from abaco import preview as PV
from abaco.layout import build_layout
from test_pipeline import doors, settings, fs


def _state():
    rs = doors()
    return US.EditState(rs, settings(rs))


def _keys(st):
    return [f["key"] for f in st.settings["fields"]]


def test_field_rows_and_counts():
    st = _state()
    rows = st.field_rows()
    assert [r.key for r in rows] == _keys(st) and all(r.Include for r in rows)
    shown, avail = st.counts()
    assert shown == len(rows) and avail == len(st.rs.fields) and avail > shown


def test_move_swaps_neighbours_and_stops_at_the_ends():
    st = _state()
    k = _keys(st)
    assert st.move(k[1], -1) and _keys(st)[:2] == [k[1], k[0]]
    assert not st.move(k[1], -1)                           # already first
    assert not st.move(k[-1], 1)                           # already last


def test_include_toggle_changes_the_table():
    st = _state()
    n = len(P.build_table(st.rs, st.settings).table.columns)
    st.set_include(K_FAMILY, False)
    res = P.build_table(st.rs, st.settings)
    assert len(res.table.columns) == n - 1 and K_FAMILY not in [c.key for c in res.table.columns]


def test_add_field_and_suggestions():
    st = _state()
    fam = [f for f in st.settings["fields"] if f["key"] == K_FAMILY][0]
    st.settings["fields"].remove(fam)
    sug = st.suggestions(u"fam")
    assert [r.key for r in sug] == [K_FAMILY]
    assert st.add_field(K_FAMILY) and _keys(st)[-1] == K_FAMILY
    assert not st.add_field(K_FAMILY) and not st.add_field("NOPE")
    assert K_FAMILY not in [r.key for r in st.suggestions(u"")]


def test_duplicate_labels_stay_apart():
    rs = doors()
    for key, scope in ((u"T-1", "element"), (u"T-2", "type")):
        rs.add_field(Field(key, u"Remarks", scope, "text"))
    st = US.EditState(rs, settings(rs))
    labs = [r.Label for r in st.suggestions(u"remarks")]
    assert len(labs) == 2 and len(set(labs)) == 2 and all(u"Remarks" in l for l in labs)
    st.add_field(u"T-2")
    assert fs(st.settings, u"T-2")["heading"] == u"Remarks (type)"        # heading keeps the two apart


def test_sort_operations():
    st = _state()
    n = len(st.settings["sort"])
    st.sort_add()
    assert len(st.settings["sort"]) == n + 1
    new = st.settings["sort"][-1]["key"]
    assert new not in [s["key"] for s in st.settings["sort"][:-1]]
    st.sort_set(n, descending=True, gap=True)
    assert st.settings["sort"][n]["dir"] == "desc" and st.settings["sort"][n]["gap"] is True
    st.sort_set(n, label=st.label(K_WIDTH))
    assert st.settings["sort"][n]["key"] == K_WIDTH
    rows = st.sort_rows()
    assert rows[n].Index == n + 1 and rows[n].Descending and rows[n].Column == st.label(K_WIDTH)
    st.sort_remove(n)
    assert len(st.settings["sort"]) == n
    st.sort_clear()
    assert st.settings["sort"] == []


def _widths(st):
    tbl = P.build_table(st.rs, st.settings).table
    i = [c.key for c in tbl.columns].index(K_WIDTH)
    return [r.cells.get(K_WIDTH) for b in tbl.blocks for r in b if r.kind == "data" and r.cells.get(K_WIDTH) is not None]


def test_descending_sort_reverses_the_order():
    st = _state()
    st.settings["sort"] = [P.sort_setting(K_WIDTH)]
    up = _widths(st)
    assert len(up) > 1 and up == sorted(up)
    st.sort_set(0, descending=True)
    down = _widths(st)
    assert down == sorted(down, reverse=True) and up != down


def test_format_set_values_and_rows():
    st = _state()
    st.format_set(K_WIDTH, align="right", calc="total", widthMm=30.0, hiddenInRevit=True, showInExcel=False)
    v = st.format_values(K_WIDTH)
    assert v["align"] == "right" and v["calc"] == "total" and v["widthMm"] == 30.0 and v["hidden"] and not v["excel"]
    row = [r for r in st.format_rows() if r.key == K_WIDTH][0]
    assert (row.AlignChip, row.HiddenInRevit, row.NoExcel, row.HasCalc) == (u"R", True, True, True)
    st.format_set(K_WIDTH, heading=u"Larghezza", align="left", calc="none", hiddenInRevit=False, showInExcel=True)
    st.update_format_row(row)
    assert row.Label == u"Larghezza" and row.AlignChip == u"L" and not row.HiddenInRevit and not row.HasCalc


def test_heading_equal_to_label_is_not_stored():
    st = _state()
    st.format_set(K_FAMILY, heading=u"Famiglia")
    assert fs(st.settings, K_FAMILY)["heading"] == u"Famiglia"
    st.format_set(K_FAMILY, heading=u"Family")
    assert fs(st.settings, K_FAMILY)["heading"] is None
    st.format_set(K_FAMILY, heading=u"  ")
    assert fs(st.settings, K_FAMILY)["heading"] is None


def test_watched_properties_call_back_only_on_user_edits():
    seen = []
    row = US.FieldRow(u"k", u"Label", True, u"", lambda r, n: seen.append(n))
    assert row.Include is True and seen == []              # building the row is not an edit
    row.Include = False
    row.Include = False                                     # same value: no second call
    assert seen == ["Include"] and row.Include is False
    srow = US.SortRow(1, [u"a"], u"a", False, False, lambda r, n: seen.append(n))
    srow.Descending = True
    srow.GapRow = True
    assert seen[1:] == ["Descending", "GapRow"]


def test_excel_view_kinds_and_decimals():
    rs = doors()
    s = settings(rs)
    fs(s, K_WIDTH)["calc"] = "total"
    tbl = P.build_table(rs, s).excel
    heads, rows, kinds = PV.excel_view(tbl)
    assert len(heads) == len(tbl.columns) and len(rows) == len(kinds)
    assert kinds.count("blank") == len(tbl.blocks) - 1
    assert kinds.count("data") == tbl.n_data_rows()
    assert 1 <= kinds.count("total") <= len(tbl.blocks)
    wi = heads.index(u"Width (m)")
    shown = [r[wi] for r, k in zip(rows, kinds) if k == "data" and r[wi]]
    assert shown and all(re.match(r"^\d+\.\d{3}$", x) for x in shown)      # 3 decimals like the Excel number format
    tot = [r for r, k in zip(rows, kinds) if k == "total"][0]
    assert tot[0] == u"Total"                                # label placed in the first column without a calculation


def test_canvas_primitives_stack_pages_and_scale():
    rs = doors()
    lay = build_layout(P.build_table(rs, settings(rs)).revit, 2.5, 490)
    lines, texts, caps, w, h = PV.canvas_primitives(lay, 4.0)
    assert len(lines) == len(lay.pages[0].lines) and caps == []
    assert abs(w - lay.table_w * 4.0) < 1e-9 and h >= lay.pages[0].height * 4.0 - 1e-9
    assert all(ln[1] >= -1e-9 and ln[3] >= -1e-9 for ln in lines)          # y points down from 0
    small = build_layout(P.build_table(rs, settings(rs)).revit, 2.5, 20)     # tiny pages: several of them
    assert len(small.pages) > 1
    lines2, texts2, caps2, w2, h2 = PV.canvas_primitives(small, 4.0)
    assert len(caps2) == len(small.pages) and caps2[0][0] == u"Sheet 1 of %d" % len(small.pages)
    assert h2 > small.pages[0].height * 4.0
    items = PV.ruler_items(lay, 4.0)
    assert len(items) == lay.n_cols and abs(sum(w_ for _, w_ in items) - w) < 1e-6


def test_validation_helpers():
    assert US.parse_decimal(u"2,5") == 2.5 and US.parse_decimal(u" 3.25 ") == 3.25
    for bad in (u"", u"abc"):
        try:
            US.parse_decimal(bad)
            assert False
        except ValueError:
            pass
    assert US.check_table_name(u"Abaco Walls", True, True) == []
    assert len(US.check_table_name(u"x" * 32, True, True)) == 1
    assert US.check_table_name(u"x" * 32, True, False) == []              # the limit is Excel's
    assert US.check_table_name(u"Walls: A/B", False, True) != []
    assert US.check_table_name(u"Walls {A}", True, False) != []
    assert US.check_table_name(u"Walls {A}", False, True) == []           # braces are fine in Excel
    assert US.check_table_name(u"  ", True, True) != []
    assert US.check_excel_path(u"") != [] and US.check_excel_path(u"C:\\x\\a.xls") != []


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for n, f in tests:
        f()
        print("ok   " + n)
    print("%d tests passed" % len(tests))
