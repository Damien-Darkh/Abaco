# -*- coding: utf-8 -*-
"""Pipeline tests (Phase 2): records + settings -> table. Run: python3 tests/test_pipeline.py   (no Revit)

Fixtures are small hand-built projects. The v1 tests check the tables the v1 builder produced for the same
fixtures. Other expectations are worked out by hand in the comments.

Settings used here:
  - sort & group is a list of levels (settings["levels"]); the first level is the outermost
  - curtain walls are not a table mode: they are removed by a filter before grouping (only())
  - a takeoff table is requested with table_type="takeoff" (falls back to a schedule when not layered)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from abaco.records import (Field, Layer, TypeRecord, ElementRecord, RecordSet, core_fields,
                           K_TYPE_MARK, K_TYPE_NAME, K_FAMILY, K_LEVEL, K_WIDTH, K_HEIGHT, K_LENGTH, K_AREA,
                           K_COUNT, K_LAYER_ORDER, K_LAYER_THICKNESS, K_LAYER_AREA, K_IS_CURTAIN)
from abaco import pipeline as P
from abaco import filters

M2 = u"m\u00b2"
COMMENTS = u"ALL_MODEL_INSTANCE_COMMENTS"


# ------------------------------------------------------------------------------------------- fixtures
def _el(rs, eid, tid, level, ma=None, **vals):
    v = {K_LEVEL: level}
    v.update(vals)
    rs.add_element(ElementRecord(eid, tid, v, ma or {}))


def walls():
    """Types: 100 layered (3 layers), 200 layered (1 layer), 300 stacked (no layers),
    400 and 500 curtain walls. Elements 1-5 are standard walls, 6-9 curtain walls."""
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
    """Types 600 (D1) and 700 (D2). Elements: 1,2 D1 L0 0.9x2.1 ('a','b'); 3 D1 L1 0.9x2.1 ('a');
    4 D2 L0 1.0x2.1 ('c'); 5 D2 L0 1.0x2.2 (no comment)."""
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


# -------------------------------------------------------------------------------------------- helpers
def settings(rs, table_type="schedule", **kw):
    s = P.default_settings(rs, table_type, u"Abaco Muratura")
    s.update(kw)
    return s


def fs(s, key):
    return [f for f in s["fields"] if f["key"] == key][0]


def lv(s, key):
    return [l for l in s["levels"] if l["key"] == key][0]


def only(rs, curtain):
    """Curtain walls only (curtain=True) or the other walls, as the Filter tab does before grouping."""
    rs.loaded_keys.update(f.key for f in rs.fields)
    flt = {"match": "all", "conditions": [
        {"key": K_IS_CURTAIN, "op": "eq", "value": u"Yes" if curtain else u"No"}]}
    kept = filters.apply_filters(rs, rs.elements, flt).kept
    return filters.filtered_view(rs, kept)


def build(rs, s):
    return P.build_table(rs, s)


def blanks(res):
    return sum(1 for b in res.table.blocks for r in b if r.kind == "blank")


# ------------------------------------------------------------------------------- default = v1 tables
def test_layered_matches_v1():
    """Layers expanded, Level as Base Constraint, blank rows between type groups only.
    Layer rows of A1 L0 (elements 1+2): material areas 16 (brick) and 8 (plaster); the air layer has none.
    A1 L1 (element 3): 4 and 2. S1 has no layers: one '(no layers)' row."""
    rs = walls()
    m = build(only(rs, False), settings(rs, "takeoff")).excel.to_matrix()
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
    ]


def test_layered_revit_view_drops_hidden_columns():
    rs = walls()
    r = build(only(rs, False), settings(rs, "takeoff"))
    assert [c.heading for c in r.revit.columns] == [
        u"Type Mark", u"Material", u"Thickness (m)", u"Material Area (%s)" % M2, u"Wall Area (%s)" % M2,
        u"Base Constraint"]
    assert len(r.excel.columns) == 9
    assert r.revit.to_matrix()[2] == [u"A1", u"Brick", 0.2, 16.0, 32.0, u"L0"]


def test_curtain_matches_v1():
    """Curtain walls (elements 6-9): one row per type, level and height."""
    rs = walls()
    m = build(only(rs, True), settings(rs, "schedule")).excel.to_matrix()
    assert m == [
        [u"Abaco Muratura"] + [u""] * 6,
        [u"Type Mark", u"Wall Type Name", u"Count", u"Total Length (m)", u"Height (m)",
         u"Area (%s)" % M2, u"Base Constraint"],
        [u"C1", u"CW1", 2, 5.0, 3.0, 15.0, u"L0"],
        [u"C1", u"CW1", 1, 1.0, 4.0, 4.0, u"L0"],
        [u""] * 7,
        [u"C2", u"CW2", 1, 5.0, 3.0, u"", u"L1"],
    ]


def test_simple_matches_v1():
    rs = doors()
    m = build(rs, settings(rs)).excel.to_matrix()
    assert m == [
        [u"Abaco Muratura"] + [u""] * 6,
        [u"Type Mark", u"Family", u"Type Name", u"Width (m)", u"Height (m)", u"Count", u"Level"],
        [u"D1", u"Single", u"0900x2100", 0.9, 2.1, 2, u"L0"],
        [u""] * 7,
        [u"D2", u"Single", u"1000x2100", 1.0, 2.1, 1, u"L0"],
        [u"D2", u"Single", u"1000x2100", 1.0, 2.2, 1, u"L0"],
        [u""] * 7,
        [u"D1", u"Single", u"0900x2100", 0.9, 2.1, 1, u"L1"],
    ]


def test_default_title_when_blank():
    rs = doors()
    s = settings(rs)
    s["title"] = u"  "
    assert build(rs, s).table.title == u"Abaco Doors"


def test_required_keys_cover_fields_and_levels():
    s = settings(doors())
    keys = P.required_keys(s)
    assert K_TYPE_MARK in keys and K_HEIGHT in keys and K_LEVEL in keys


# ----------------------------------------------------------------------------------------- Varies
def test_varies_and_single_value():
    rs = doors()
    s = settings(rs)
    s["fields"].append(P.field_setting(COMMENTS))
    m = build(rs, s).excel.to_matrix()
    assert m[2][-1] == u"Varies"        # D1 L0: 'a' and 'b'
    assert m[4][-1] == u"c"             # D2 2.1: one element
    assert m[5][-1] == u""              # D2 2.2: no comment
    assert m[7][-1] == u"a"             # D1 L1


def test_varies_label_is_configurable():
    rs = doors()
    s = settings(rs)
    s["fields"].append(P.field_setting(COMMENTS))
    s["labels"] = {"varies": u"Varia"}
    assert build(rs, s).excel.to_matrix()[2][-1] == u"Varia"


# -------------------------------------------------------------------------------------- itemize
def test_itemize_one_row_per_element():
    """Element Id is added as the first column. Order of elements: L0 by type mark, type name, size; then L1."""
    rs = doors()
    s = settings(rs, itemize=True)
    s["fields"].append(P.field_setting(COMMENTS))
    m = build(rs, s).excel.to_matrix()
    assert m[1][0] == u"Element Id"
    rows = [r for r in m[2:] if r[0] != u""]
    assert [r[0] for r in rows] == [1, 2, 4, 5, 3]
    assert [r[6] for r in rows] == [1, 1, 1, 1, 1]            # Count
    assert u"Varies" not in [r[-1] for r in rows]


def test_itemize_layered_one_block_per_element():
    """Five elements give five blocks, each with its own layer rows. Blocks follow the sort order:
    A1 L0 (elements 1, 2), A2 (4), S1 (5), A1 L1 (3). Layer rows per block: 3, 3, 1, 1, 3."""
    rs = walls()
    r = build(only(rs, False), settings(rs, "takeoff", itemize=True))
    counts = [sum(1 for x in b if x.kind == "data") for b in r.table.blocks]
    assert len(r.table.blocks) == 5
    assert counts == [3, 3, 1, 1, 3], counts


# ----------------------------------------------------------------------------------- sorting
def test_sort_value_ordering():
    vals = [u"b1", None, u"A2", 10, 2, u"a10", u""]
    out = sorted(vals, key=P.sort_value)
    assert out[:2] == [None, u""] or out[:2] == [u"", None]           # empty first
    assert out[2:] == [2, 10, u"a10", u"A2", u"b1"]                   # numbers, then text case-insensitive


def test_descending_level_reverses_order():
    rs = doors()
    s = settings(rs)
    s["levels"] = [P.sort_setting(K_TYPE_MARK, "desc", gap=True)]
    m = build(rs, s).excel.to_matrix()
    assert [r[0] for r in m[2:] if r[0] != u""] == [u"D2", u"D2", u"D1", u"D1"]


def test_level_on_field_not_in_table_is_skipped():
    """A level only sorts on fields checked in the Fields tab. Unchecked fields are skipped with a warning."""
    rs = doors()
    s = settings(rs)
    fs(s, K_TYPE_MARK)["include"] = False
    r = build(rs, s)
    assert any(u"not in the Fields tab" in w for w in r.warnings), r.warnings
    assert r.excel.to_matrix()[1][0] == u"Family"


def test_layer_order_stays_last_when_sorting_desc():
    rs = walls()
    s = settings(rs, "takeoff")
    s["levels"] = [P.sort_setting(K_LEVEL, "desc", gap=True), P.sort_setting(K_TYPE_MARK, gap=True)]
    m = build(only(rs, False), s).excel.to_matrix()
    assert m[2][2] == 1 and m[3][2] == 2 and m[4][2] == 3          # L1 first, layers still 1, 2, 3
    assert m[2][8] == u"L1"


def test_shared_type_mark_stays_in_one_block_and_blank_marks_split():
    rs = doors()
    rs.types[700].values[K_TYPE_MARK] = u"D1"                      # two types, same mark, same level
    r = build(rs, settings(rs))
    l0 = [x for b in r.table.blocks[:1] for x in b]
    marks = [x.cells.get(K_TYPE_MARK) for x in l0 if x.kind == "data"]
    assert marks == [u"D1", u"D1", u"D1"]
    seq = [x.kind for x in l0]
    assert seq[:3] == ["data", "data", "data"]                     # no gap row inside the D1 mark group

    rs = doors()
    rs.types[600].values[K_TYPE_MARK] = None
    rs.types[700].values[K_TYPE_MARK] = None                       # blank marks: a group per type
    r = build(rs, settings(rs))
    assert sum(1 for x in r.table.blocks[0] if x.kind == "blank") == 2


# ------------------------------------------------------------------------------------ gap rows
def test_gap_flags_control_blank_rows():
    """Default: a gap after each type group and after each level (collapsed to one): 3 blanks in the table.
    Gap off on the type mark level: only the level gap remains (1 blank)."""
    rs = walls()
    s = settings(rs, "takeoff")
    assert blanks(build(only(rs, False), s)) == 3
    lv(s, K_TYPE_MARK)["gap"] = False
    assert blanks(build(only(rs, False), s)) == 1


def test_two_gap_rows_at_one_boundary_collapse_to_one():
    rs = walls()
    r = build(only(rs, False), settings(rs, "takeoff"))
    for b in r.table.blocks:
        for a, c in zip(b, b[1:]):
            assert not (a.kind == "blank" and c.kind == "blank")


def test_no_blank_row_at_the_very_end():
    rs = walls()
    r = build(only(rs, False), settings(rs, "takeoff"))
    assert r.table.blocks[-1][-1].kind != "blank"


# -------------------------------------------------------------------------------- calculations
def test_calculations_per_block_and_grand_total():
    """Footers sit under each type group (Total, Min, Max) and the summary block at the bottom.
    Thickness total of A1 L0 = 0.2 + 0.05 + 0.02 = 0.27. Layer area minmax of A1 L0 = 8 and 16.
    Grand total thickness = 0.27 * 2 + 0.1 = 0.64. Grand layer area minmax = 2 and 16."""
    rs = walls()
    s = settings(rs, "takeoff", grandTotals=True)
    fs(s, K_LAYER_THICKNESS)["calc"] = "total"
    fs(s, K_LAYER_AREA)["calc"] = "minmax"
    r = build(only(rs, False), s)

    kinds = [x.kind for x in r.table.blocks[0]]
    assert kinds == (["data"] * 3 + ["total", "min", "max", "blank"]
                     + ["data", "total", "min", "max", "blank"]
                     + ["data", "blank"]), kinds
    a1 = r.table.blocks[0]
    assert a1[3].cells == {K_LAYER_THICKNESS: 0.27}
    assert a1[4].cells == {K_LAYER_AREA: 8.0} and a1[5].cells == {K_LAYER_AREA: 16.0}

    grand = r.table.blocks[-1]
    assert [x.kind for x in grand] == ["sumhead", "gtotal", "gmin", "gmax"]
    assert grand[1].cells == {K_LAYER_THICKNESS: 0.64}
    assert grand[2].cells == {K_LAYER_AREA: 2.0} and grand[3].cells == {K_LAYER_AREA: 16.0}


def test_calculations_in_excel_labels_and_values():
    rs = walls()
    s = settings(rs, "takeoff", grandTotals=True)
    fs(s, K_LAYER_THICKNESS)["calc"] = "total"
    fs(s, K_LAYER_AREA)["calc"] = "minmax"
    m = build(only(rs, False), s).excel.to_matrix()
    assert m[5][0] == u"Total" and m[5][4] == 0.27
    assert m[-4][0] == u"Summary"
    assert m[-3][0] == u"Total" and m[-2][0] == u"Min" and m[-1][0] == u"Max"


def test_calc_label_goes_to_first_visible_column_without_value():
    rs = walls()
    s = settings(rs, "takeoff")
    fs(s, K_LAYER_THICKNESS)["calc"] = "total"
    fs(s, K_TYPE_MARK)["hiddenInRevit"] = True
    rev = build(only(rs, False), s).revit.to_matrix()
    assert rev[1][0] == u"Material" and rev[5][0] == u"Total"


def test_calc_on_text_column_adds_nothing():
    rs = doors()
    s = settings(rs)
    s["fields"].append(P.field_setting(COMMENTS, calc="total"))
    r = build(rs, s)
    assert all(x.kind in ("data", "blank") for b in r.table.blocks for x in b)


# ------------------------------------------------------------------------ outputs and fields
def test_hidden_and_excel_flags_are_independent():
    rs = doors()
    s = settings(rs)
    fs(s, K_FAMILY)["hiddenInRevit"] = True                        # Excel only
    fs(s, K_WIDTH)["showInExcel"] = False                          # Revit only
    fs(s, K_HEIGHT)["hiddenInRevit"] = True
    fs(s, K_HEIGHT)["showInExcel"] = False                         # neither: still groups and sorts
    r = build(rs, s)
    assert [c.heading for c in r.excel.columns] == [u"Type Mark", u"Family", u"Type Name", u"Count", u"Level"]
    assert [c.heading for c in r.revit.columns] == [u"Type Mark", u"Type Name", u"Width (m)", u"Count", u"Level"]
    assert len(r.table.blocks) == 2 and r.table.n_data_rows() == 4


def test_heading_override_decimals_and_unknown_field():
    rs = walls()
    s = settings(rs, "takeoff")
    fs(s, K_LAYER_THICKNESS)["heading"] = u"Spessore"
    fs(s, K_LAYER_THICKNESS)["decimals"] = 1
    s["fields"].append(P.field_setting("NOT_THERE"))
    r = build(only(rs, False), s)
    m = r.excel.to_matrix()
    assert m[1][4] == u"Spessore"
    assert [row[4] for row in m[2:5]] == [0.2, 0.1, 0.0]            # 1 decimal
    assert len(r.warnings) == 1 and u"NOT_THERE" in r.warnings[0]


def test_takeoff_on_unlayered_category_becomes_schedule():
    rs = doors()
    assert P.effective_type(rs, {"tableType": "takeoff"}) == "schedule"
    s = settings(rs)
    s["tableType"] = "takeoff"
    r = build(rs, s)
    assert any(u"needs layered types" in w for w in r.warnings), r.warnings


def test_no_columns_is_an_error():
    rs = doors()
    s = settings(rs)
    for f in s["fields"]:
        f["include"] = False
    try:
        build(rs, s)
        assert False, "expected ValueError"
    except ValueError:
        pass

def test_unknown_calc_mode_is_refused():
    rs = doors()
    s = settings(rs)
    fs(s, K_WIDTH)["calc"] = "summary"
    try:
        build(rs, s)
        assert False, "expected ValueError for unknown calc mode"
    except ValueError as ex:
        assert u"summary" in u"%s" % ex and u"Allowed" in u"%s" % ex

        
if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for n, f in tests:
        f()
        print("ok   " + n)
    print("%d tests passed" % len(tests))