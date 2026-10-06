# -*- coding: utf-8 -*-
"""Run with:  python3 tests/test_pipeline.py   (no Revit needed)

Fixtures are tiny hand-built projects; the expected tables are what the v1 builder produces for them
(checked by hand against table_builder.py), so default settings must reproduce them row for row.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

from abaco.records import (Field, Layer, TypeRecord, ElementRecord, RecordSet, core_fields,
                           K_TYPE_MARK, K_TYPE_NAME, K_FAMILY, K_LEVEL, K_WIDTH, K_HEIGHT, K_LENGTH, K_AREA,
                           K_ELEMENT_ID, K_COUNT, K_LAYER_THICKNESS, K_LAYER_AREA, K_LAYER_MATERIAL)
from abaco import pipeline as P

M2 = u"m\u00b2"
COMMENTS = "ALL_MODEL_INSTANCE_COMMENTS"


def _el(rs, eid, tid, level, ma=None, **vals):
    v = {K_LEVEL: level}
    v.update(vals)
    rs.add_element(ElementRecord(eid, tid, v, ma or {}))


def walls():
    rs = RecordSet(-2000011, u"Walls")
    for f in core_fields(True):
        rs.add_field(f)
    rs.add_type(TypeRecord(100, {K_TYPE_MARK: u"A1", K_TYPE_NAME: u"Brick"}, [
        Layer(1, 10, u"Brick", 0.2, u"Structure"),
        Layer(2, None, u"None / Air", 0.05, u"Insulation"),
        Layer(3, 11, u"Plaster", 0.02, u"Finish")]))
    rs.add_type(TypeRecord(200, {K_TYPE_MARK: u"A2", K_TYPE_NAME: u"Plaster"},
                           [Layer(1, 11, u"Plaster", 0.1, u"Structure")]))
    rs.add_type(TypeRecord(300, {K_TYPE_MARK: u"S1", K_TYPE_NAME: u"Stacked"}, None))
    rs.add_type(TypeRecord(400, {K_TYPE_MARK: u"C1", K_TYPE_NAME: u"CW1"}, None, True))
    rs.add_type(TypeRecord(500, {K_TYPE_MARK: u"C2", K_TYPE_NAME: u"CW2"}, None, True))
    _el(rs, 1, 100, u"L0", {10: 10.0, 11: 5.0}, **{K_AREA: 20.0})
    _el(rs, 2, 100, u"L0", {10: 6.0, 11: 3.0}, **{K_AREA: 12.0})
    _el(rs, 3, 100, u"L1", {10: 4.0, 11: 2.0}, **{K_AREA: 8.0})
    _el(rs, 4, 200, u"L0", {11: 7.0}, **{K_AREA: 14.0})
    _el(rs, 5, 300, u"L0", None, **{K_HEIGHT: 3.0, K_AREA: 5.0})
    _el(rs, 6, 400, u"L0", None, **{K_HEIGHT: 3.0, K_LENGTH: 2.0, K_AREA: 6.0})
    _el(rs, 7, 400, u"L0", None, **{K_HEIGHT: 3.0, K_LENGTH: 3.0, K_AREA: 9.0})
    _el(rs, 8, 400, u"L0", None, **{K_HEIGHT: 4.0, K_LENGTH: 1.0, K_AREA: 4.0})
    _el(rs, 9, 500, u"L1", None, **{K_HEIGHT: 3.0, K_LENGTH: 5.0})
    return rs


def doors():
    rs = RecordSet(-2000023, u"Doors")
    for f in core_fields(False):
        rs.add_field(f)
    rs.add_field(Field(COMMENTS, u"Comments", "element", "text"))
    rs.add_type(TypeRecord(600, {K_TYPE_MARK: u"D1", K_FAMILY: u"Single", K_TYPE_NAME: u"0900x2100"}))
    rs.add_type(TypeRecord(700, {K_TYPE_MARK: u"D2", K_FAMILY: u"Single", K_TYPE_NAME: u"1000x2100"}))
    sz = lambda w, h: {K_WIDTH: w, K_HEIGHT: h}
    _el(rs, 1, 600, u"L0", None, **dict(sz(0.9, 2.1), **{COMMENTS: u"a"}))
    _el(rs, 2, 600, u"L0", None, **dict(sz(0.9, 2.1), **{COMMENTS: u"b"}))
    _el(rs, 3, 600, u"L1", None, **dict(sz(0.9, 2.1), **{COMMENTS: u"a"}))
    _el(rs, 4, 700, u"L0", None, **dict(sz(1.0, 2.1), **{COMMENTS: u"c"}))
    _el(rs, 5, 700, u"L0", None, **sz(1.0, 2.2))
    return rs


def settings(rs, mode="standard", **kw):
    s = P.default_settings(rs, mode, u"Abaco Muratura")
    s.update(kw)
    return s


def fs(s, key):
    return [f for f in s["fields"] if f["key"] == key][0]


# ------------------------------------------------------------------------- default = v1, row for row
def test_layered_matches_v1():
    m = P.build_table(walls(), settings(walls())).excel.to_matrix()
    assert m == [
        [u"Abaco Muratura"] + [u""] * 8,
        [u"Type Mark", u"Wall Type Name", u"Order", u"Material", u"Thickness (m)", u"Function",
         u"Material Area (%s)" % M2, u"Wall Area (%s)" % M2, u"Base Constraint"],
        [u"A1", u"Brick", 1, u"Brick", 0.2, u"Structure", 16.0, 32.0, u"L0"],
        [u"A1", u"Brick", 2, u"None / Air", 0.05, u"Insulation", u"", 32.0, u"L0"],
        [u"A1", u"Brick", 3, u"Plaster", 0.02, u"Finish", 8.0, 32.0, u"L0"],
        [u""] * 9,
        [u"A2", u"Plaster", 1, u"Plaster", 0.1, u"Structure", 7.0, 14.0, u"L0"],
        [u""] * 9,
        [u"S1", u"Stacked", u"", u"(no layers)", u"", u"", u"", 5.0, u"L0"],
        [u""] * 9,
        [u"A1", u"Brick", 1, u"Brick", 0.2, u"Structure", 4.0, 8.0, u"L1"],
        [u"A1", u"Brick", 2, u"None / Air", 0.05, u"Insulation", u"", 8.0, u"L1"],
        [u"A1", u"Brick", 3, u"Plaster", 0.02, u"Finish", 2.0, 8.0, u"L1"],
    ], m


def test_curtain_matches_v1():
    rs = walls()
    m = P.build_table(rs, settings(rs, "curtain")).excel.to_matrix()
    assert m == [
        [u"Abaco Muratura"] + [u""] * 6,
        [u"Type Mark", u"Wall Type Name", u"Count", u"Total Length (m)", u"Height (m)",
         u"Area (%s)" % M2, u"Base Constraint"],
        [u"C1", u"CW1", 2, 5.0, 3.0, 15.0, u"L0"],
        [u"C1", u"CW1", 1, 1.0, 4.0, 4.0, u"L0"],
        [u""] * 7,
        [u"C2", u"CW2", 1, 5.0, 3.0, u"", u"L1"],
    ], m


def test_simple_matches_v1():
    rs = doors()
    m = P.build_table(rs, settings(rs)).excel.to_matrix()
    assert m == [
        [u"Abaco Muratura"] + [u""] * 6,
        [u"Type Mark", u"Family", u"Type Name", u"Width (m)", u"Height (m)", u"Count", u"Level"],
        [u"D1", u"Single", u"0900x2100", 0.9, 2.1, 2, u"L0"],
        [u""] * 7,
        [u"D2", u"Single", u"1000x2100", 1.0, 2.1, 1, u"L0"],
        [u"D2", u"Single", u"1000x2100", 1.0, 2.2, 1, u"L0"],
        [u""] * 7,
        [u"D1", u"Single", u"0900x2100", 0.9, 2.1, 1, u"L1"],
    ], m


def test_revit_table_drops_v1_hidden_columns():
    rs = walls()
    r = P.build_table(rs, settings(rs))
    assert [c.heading for c in r.revit.columns] == [
        u"Type Mark", u"Material", u"Thickness (m)", u"Material Area (%s)" % M2, u"Wall Area (%s)" % M2,
        u"Base Constraint"]
    assert len(r.excel.columns) == 9                       # Excel keeps every column
    assert r.revit.to_matrix()[2] == [u"A1", u"Brick", 0.2, 16.0, 32.0, u"L0"]


def test_default_title_when_blank():
    rs = doors()
    s = settings(rs)
    s["title"] = u"  "
    assert P.build_table(rs, s).table.title == u"Abaco Doors"


# ----------------------------------------------------------------------------------------------- Varies
def test_varies_and_single_value():
    rs = doors()
    s = settings(rs)
    s["fields"].append(P.field_setting(COMMENTS))
    m = P.build_table(rs, s).excel.to_matrix()
    assert m[2][-1] == u"Varies"                 # D1 L0: "a" and "b"
    assert m[4][-1] == u"c"                      # D2 w1.0 h2.1: one element
    assert m[5][-1] == u""                       # D2 h2.2: empty
    assert m[7][-1] == u"a"                      # D1 L1


def test_varies_label_is_configurable():
    rs = doors()
    s = settings(rs)
    s["fields"].append(P.field_setting(COMMENTS))
    s["labels"] = {"varies": u"Varia"}
    assert P.build_table(rs, s).excel.to_matrix()[2][-1] == u"Varia"


# ---------------------------------------------------------------------------------------------- itemize
def test_itemize_one_row_per_element():
    rs = doors()
    s = settings(rs, itemize=True)
    s["fields"].append(P.field_setting(COMMENTS))
    r = P.build_table(rs, s)
    m = r.excel.to_matrix()
    assert m[1][0] == u"Element Id"
    ids = [row[0] for row in m[2:] if row[0] != u""]
    assert ids == [1, 2, 4, 5, 3], ids
    assert [row[6] for row in m[2:] if row[0] != u""] == [1, 1, 1, 1, 1]      # Count
    assert u"Varies" not in [row[-1] for row in m]


def test_itemize_layered_makes_one_block_per_element():
    rs = walls()
    r = P.build_table(rs, settings(rs, itemize=True))
    blocks = [b for b in r.table.blocks]
    # elements 1,2,3,4,5 -> five blocks (A1 L0 twice, A2, S1, A1 L1)
    assert len(blocks) == 5
    assert [len(b) for b in blocks] == [3, 3, 1, 1, 3]


# ------------------------------------------------------------------------------------------------- sort
def test_sort_value_ordering():
    vals = [u"b1", None, u"A2", 10, 2, u"a10", u""]
    out = sorted(vals, key=P.sort_value)
    assert out[:2] == [None, u""] or out[:2] == [u"", None]
    assert out[2:] == [2, 10, u"a10", u"A2", u"b1"]


def test_sort_desc_and_not_in_table():
    rs = doors()
    s = settings(rs)
    s["sort"] = [P.sort_setting(K_TYPE_MARK, "desc", gap=True)]
    m = P.build_table(rs, s).excel.to_matrix()
    assert [r[0] for r in m[2:] if r[0] != u""] == [u"D2", u"D2", u"D1", u"D1"], m
    # hidden / not included fields still sort
    s = settings(rs)
    fs(s, K_TYPE_MARK)["include"] = False
    s["sort"] = [P.sort_setting(K_TYPE_MARK, "desc", gap=True)]
    m = P.build_table(rs, s).excel.to_matrix()
    assert m[1][0] == u"Family"
    assert [r[0] for r in m[2:] if r[0] != u""] == [u"Single"] * 4
    assert [r[1] for r in m[2:] if r[1] != u""] == [u"1000x2100", u"1000x2100", u"0900x2100", u"0900x2100"]


def test_layer_order_stays_last_even_when_sorting_desc():
    rs = walls()
    s = settings(rs)
    s["sort"] = [P.sort_setting(K_LEVEL, "desc", gap=True), P.sort_setting(K_TYPE_MARK, gap=True)]
    m = P.build_table(rs, s).excel.to_matrix()
    assert m[2][2] == 1 and m[3][2] == 2 and m[4][2] == 3          # L1 first, layers still 1,2,3
    assert m[2][8] == u"L1"


def test_shared_type_mark_one_block_blank_mark_separate_blocks():
    rs = doors()
    rs.types[700].values[K_TYPE_MARK] = u"D1"                 # two types, same mark, same level
    s = settings(rs)
    m = P.build_table(rs, s).excel.to_matrix()
    l0 = [r for r in m[2:] if r[6] == u"L0"]
    assert [r[0] for r in l0] == [u"D1"] * 3 and u"" not in [r[6] for r in l0[:3]]   # no blank row inside
    rs = doors()
    rs.types[600].values[K_TYPE_MARK] = None
    rs.types[700].values[K_TYPE_MARK] = None                  # blank marks: one block per type
    m = P.build_table(rs, settings(rs)).excel.to_matrix()
    assert [r for r in m[2:] if r[0] == u"" and r[1] == u""] != []
    assert len(P.build_table(rs, settings(rs)).table.blocks) == 3


def test_gap_flags_control_blocks():
    rs = walls()
    s = settings(rs)
    for st in s["sort"]:
        st["gap"] = (st["key"] == K_LEVEL)
    r = P.build_table(rs, s)
    assert len(r.table.blocks) == 2                                # only a level change starts a block


# ------------------------------------------------------------------------------------- calculations
def test_calculations_per_block_and_grand_total():
    rs = walls()
    s = settings(rs, grandTotals=True)
    fs(s, K_LAYER_THICKNESS)["calc"] = "total"
    fs(s, K_LAYER_AREA)["calc"] = "minmax"
    r = P.build_table(rs, s)
    b0 = r.table.blocks[0]                                         # L0 / A1
    kinds = [x.kind for x in b0]
    assert kinds == ["data", "data", "data", "total", "min", "max"], kinds
    assert b0[3].cells == {K_LAYER_THICKNESS: 0.27}
    assert b0[4].cells == {K_LAYER_AREA: 8.0} and b0[5].cells == {K_LAYER_AREA: 16.0}
    assert [x.kind for x in r.table.blocks[2]] == ["data"]         # stacked wall: nothing to calculate
    grand = r.table.blocks[-1]
    assert [x.kind for x in grand] == ["gtotal", "gmin", "gmax"]
    assert grand[0].cells == {K_LAYER_THICKNESS: 0.64}
    assert grand[1].cells == {K_LAYER_AREA: 2.0} and grand[2].cells == {K_LAYER_AREA: 16.0}
    m = r.excel.to_matrix()
    assert m[5][0] == u"Total" and m[5][4] == 0.27
    assert m[-3][0] == u"Grand total" and m[-2][0] == u"Grand total min"


def test_calc_label_moves_to_first_visible_non_calc_column():
    rs = walls()
    s = settings(rs)
    fs(s, K_LAYER_THICKNESS)["calc"] = "total"
    fs(s, K_TYPE_MARK)["hiddenInRevit"] = True
    r = P.build_table(rs, s)
    rev = r.revit.to_matrix()
    assert rev[1][0] == u"Material" and rev[5][0] == u"Total"


def test_calc_skips_varies_text_and_empty():
    rs = doors()
    s = settings(rs)
    s["fields"].append(P.field_setting(COMMENTS, calc="total"))
    r = P.build_table(rs, s)
    assert all(x.kind == "data" for b in r.table.blocks for x in b)    # nothing numeric to total


# ------------------------------------------------------------------------------------ outputs / fields
def test_hidden_and_excel_flags_are_independent():
    rs = doors()
    s = settings(rs)
    fs(s, K_FAMILY)["hiddenInRevit"] = True            # Excel only
    fs(s, K_WIDTH)["showInExcel"] = False              # Revit only
    fs(s, K_HEIGHT)["hiddenInRevit"] = True
    fs(s, K_HEIGHT)["showInExcel"] = False             # neither, still used for grouping and sorting
    r = P.build_table(rs, s)
    assert [c.heading for c in r.excel.columns] == [u"Type Mark", u"Family", u"Type Name", u"Count", u"Level"]
    assert [c.heading for c in r.revit.columns] == [u"Type Mark", u"Type Name", u"Width (m)", u"Count", u"Level"]
    assert len(r.table.blocks) == 3 and r.table.n_data_rows() == 4


def test_heading_override_decimals_and_unknown_field():
    rs = walls()
    s = settings(rs)
    fs(s, K_LAYER_THICKNESS)["heading"] = u"Spessore"
    fs(s, K_LAYER_THICKNESS)["decimals"] = 1
    s["fields"].append(P.field_setting("NOT_THERE"))
    r = P.build_table(rs, s)
    assert r.excel.to_matrix()[1][4] == u"Spessore"
    assert [row[4] for row in r.excel.to_matrix()[2:5]] == [0.2, 0.1, 0.0]      # 1 decimal
    assert len(r.warnings) == 1 and u"NOT_THERE" in r.warnings[0]


def test_no_columns_is_an_error():
    rs = doors()
    s = settings(rs)
    for f in s["fields"]:
        f["include"] = False
    try:
        P.build_table(rs, s)
        assert False
    except ValueError:
        pass


def test_required_keys():
    s = settings(doors())
    assert K_TYPE_MARK in P.required_keys(s) and K_HEIGHT in P.required_keys(s)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for n, f in tests:
        f()
        print("ok   " + n)
    print("%d tests passed" % len(tests))
