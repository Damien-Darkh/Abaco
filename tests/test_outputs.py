# -*- coding: utf-8 -*-
"""Layout engine and Excel sheet model (Phase 3). Run: python3 tests/test_outputs.py   (no Revit needed)

Uses the fixtures and helpers of test_pipeline.py. Row numbers are Excel rows (1-based): row 1 title,
row 2 headings, then the table rows including blank gap rows.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)

from abaco.records import K_TYPE_MARK, K_FAMILY, K_WIDTH, K_HEIGHT, K_LAYER_THICKNESS, K_LAYER_AREA
from abaco import pipeline as P
from abaco.layout import build_layout
from abaco.sheet import build_sheet
from test_pipeline import walls, doors, settings, fs, only
from abaco import measure as M
from abaco import appearance as AP
from abaco.records import Field, RecordSet, TypeRecord, ElementRecord, core_fields
from abaco.records import K_LEVEL, K_TYPE_NAME

TEXT = 2.5
PAD_X = 2.0
ROW_H = 6.0          # row height of one text line at 2.5 mm: max(2.5 * 2.4, 5) = 6 mm
COST = u"@COST"

def _wall_takeoff(**kw):
    """Standard walls as a material takeoff (layers expanded), the view the window shows for walls."""
    rs = walls()
    return only(rs, False), settings(rs, "takeoff", **kw)


def _layout(rs, s, page_h=490, revit=True):
    r = P.build_table(rs, s)
    return build_layout(r.revit if revit else r.table, TEXT, page_h)


# ----------------------------------------------------------------------------------------------- layout
def test_basic_geometry_and_header_by_position():
    """Doors, schedule. Two top-level blocks (L0, L1). Rows on the page: D1 | gap | D2 | D2 | gap | D1 L1.
    The gap after D2 is the Type Mark gap and the Level gap, collapsed into one."""
    rs = doors()
    lay = _layout(rs, settings(rs))
    assert lay.n_cols == 7
    assert lay.n_blocks == 2
    assert len(lay.pages) == 1
    pg = lay.pages[0]
    assert pg.nrows == 6                                   # 4 data rows + 2 gap rows
    heads = [t[1] for t in pg.texts if t[0] == "heading"]
    assert heads == [u"Type Mark", u"Family", u"Type Name", u"Width (m)", u"Height (m)", u"Count", u"Level"]
    first_cell = [t for t in pg.texts if t[0] == "data"][0]
    assert first_cell[1] == u"D1"
    assert abs(first_cell[2] - PAD_X) < 1e-9                       # x: column start + side padding
    assert abs(first_cell[4] - (lay.col_w[0] - 2 * PAD_X)) < 1e-9  # width: column minus padding both sides


def test_header_uses_heading_override_when_type_mark_is_not_shown():
    """Type Mark can be left out of the table; the header row must not depend on it."""
    rs = doors()
    s = settings(rs)
    fs(s, K_TYPE_MARK)["include"] = False
    fs(s, K_FAMILY)["heading"] = u"Famiglia"
    lay = _layout(rs, s)
    assert [t[1] for t in lay.pages[0].texts if t[0] == "heading"][0] == u"Famiglia"


def test_alignment_gets_fixed_width_box():
    """Right-aligned width and centred family: each cell is a box as wide as its column less the padding."""
    rs = doors()
    s = settings(rs)
    fs(s, K_WIDTH)["align"] = "right"
    fs(s, K_FAMILY)["align"] = "center"
    lay = _layout(rs, s)
    width_col = 3                                          # Type Mark, Family, Type Name, Width (m) ...
    wcells = [t for t in lay.pages[0].texts
              if t[0] == "data" and abs(t[2] - (lay.col_x[width_col] + PAD_X)) < 1e-9]
    assert len(wcells) == 4
    assert all(t[5] == "right" and abs(t[4] - (lay.col_w[width_col] - 2 * PAD_X)) < 1e-9 for t in wcells)
    fam = [t for t in lay.pages[0].texts if t[0] == "data" and t[1] == u"Single"]
    assert len(fam) == 4 and all(t[5] == "center" and t[4] is not None for t in fam)


def test_fixed_width_column():
    rs = doors()
    s = settings(rs)
    fs(s, K_FAMILY)["widthMm"] = 40
    lay = _layout(rs, s)
    assert lay.col_w[1] == 40.0
    assert abs(lay.table_w - sum(lay.col_w)) < 1e-9


def test_vertical_heading_raises_header_and_rotates():
    """A vertical heading (Appearance) makes the header as tall as its text, and does not widen the column.
    The expected height is measured with the same function as the layout (title case, bold heading,
    safety margin, padding), so the test follows the layout's rules, not a fixed character width."""
    rs = doors()
    s = settings(rs)
    s["fields"][0]["heading"] = u"Type Mark long heading"
    s["appearance"]["elements"]["heading"]["orientation"] = "vertical"
    lay = _layout(rs, s)

    text = AP.apply_case(u"Type Mark long heading", AP.case_of(s["appearance"], "heading"))
    need = M.width_mm(text, "Arial", TEXT, True, False) * 1.06 + 2 * PAD_X
    assert abs(lay.header_h - need) < 1e-6
    assert lay.header_h > ROW_H

    head = [t for t in lay.pages[0].texts if t[0] == "heading"][0]
    assert head[6] == 90 and head[4] is None
    assert lay.col_w[0] < need


def test_summary_rows_are_drawn_and_paged_with_their_block():
    """Thickness Total on the Type Mark level: one Total row per Type Mark group (A1 L0, A2, A1 L1) = 3.
    Each Total row keeps its value 0.27 (A1 L0) or 0.1 (A2) or 0.27 (A1 L1)."""
    rs, s = _wall_takeoff()
    fs(s, K_LAYER_THICKNESS)["calc"] = "total"
    lay = _layout(rs, s, page_h=60)
    summary = [t for p in lay.pages for t in p.texts if t[0] == "summary"]
    assert [t[1] for t in summary if t[1] == u"Total"] == [u"Total"] * 3
    assert [t[1] for t in summary if t[1] != u"Total"] == [u"0.270", u"0.100", u"0.270"]


def test_pagination_never_splits_a_block():
    """Takeoff walls, page height 60 mm. Two top-level blocks: L0 (A1, A2, S1 with their gap rows, 8 rows)
    and L1 (A1, 3 rows). L0 is 67.75 mm tall with the header, which is over the limit, but a block is never
    split, so it stays whole on page 1. L1 goes to page 2."""
    rs, s = _wall_takeoff()
    lay = _layout(rs, s, page_h=60)
    assert lay.n_blocks == 2
    assert len(lay.pages) == 2
    assert [p.nrows for p in lay.pages] == [8, 3]


def test_revit_table_has_only_visible_columns():
    rs, s = _wall_takeoff()
    lay = _layout(rs, s)
    assert lay.n_cols == 6                                 # Excel has 9; Order and Function hidden in Revit


# ------------------------------------------------------------------------------------------------ sheet
def _calc_sheet():
    """Takeoff walls, grand totals on, Total on thickness, Min and Max on layer area (see the row map)."""
    rs, s = _wall_takeoff(grandTotals=True)
    fs(s, K_LAYER_THICKNESS)["calc"] = "total"
    fs(s, K_LAYER_AREA)["calc"] = "minmax"
    return build_sheet(P.build_table(rs, s).excel)


def test_sheet_block_formulas():
    """Footer rows use SUBTOTAL, so a grand total can include the footer rows without double counting.
    Thickness is column E (5), material area is column G (7)."""
    sh = _calc_sheet()
    f = sh.formulas
    assert f[(6, 5)] == u"=SUBTOTAL(9,E3:E5)"
    assert f[(7, 7)] == u"=SUBTOTAL(5,G3:G5)" and f[(8, 7)] == u"=SUBTOTAL(4,G3:G5)"
    assert f[(11, 5)] == u"=SUBTOTAL(9,E10)"
    assert f[(12, 7)] == u"=SUBTOTAL(5,G10)" and f[(13, 7)] == u"=SUBTOTAL(4,G10)"
    assert f[(20, 5)] == u"=SUBTOTAL(9,E17:E19)"
    assert f[(21, 7)] == u"=SUBTOTAL(5,G17:G19)" and f[(22, 7)] == u"=SUBTOTAL(4,G17:G19)"
    assert [sh.values[r - 1][0] for r in (6, 7, 8)] == [u"Total", u"Min", u"Max"]


def test_sheet_grand_total_block():
    """Grand totals cover every block's data rows: the ranges span each top-level block."""
    sh = _calc_sheet()
    assert sh.values[23][0] == u"Summary"
    assert sh.formulas[(25, 5)] == u"=SUBTOTAL(9,E3:E15,E17:E19)"
    assert sh.formulas[(26, 7)] == u"=SUBTOTAL(5,G3:G15,G17:G19)"
    assert sh.formulas[(27, 7)] == u"=SUBTOTAL(4,G3:G15,G17:G19)"
    assert [sh.values[r - 1][0] for r in (25, 26, 27)] == [u"Total", u"Min", u"Max"]
    assert len(sh.formulas) == 12


def test_sheet_grand_total_formulas_combine_blocks():
    """Grand totals use SUBTOTAL, so nested footer rows are not counted twice. Each grand-total range
    spans the first to the last data row of each top-level block (L0 = rows 3-15, L1 = rows 17-19),
    and the blank row between blocks (16) is inside the L0 range, which is harmless: blanks are empty."""
    sh = _calc_sheet()
    assert sh.formulas[(25, 5)] == u"=SUBTOTAL(9,E3:E15,E17:E19)"
    assert sh.formulas[(26, 7)] == u"=SUBTOTAL(5,G3:G15,G17:G19)"
    assert sh.formulas[(27, 7)] == u"=SUBTOTAL(4,G3:G15,G17:G19)"
    assert all(f.startswith(u"=SUBTOTAL(") for f in sh.formulas.values())


def test_sheet_bold_and_alignment():
    """Heading bold and orientation come from the Appearance heading element. Data alignment comes from
    each field's Formatting setting."""
    rs = doors()
    s = settings(rs)
    fs(s, K_WIDTH)["align"] = "right"
    s["appearance"]["elements"]["heading"]["orientation"] = "vertical"
    sh = build_sheet(P.build_table(rs, s).excel)
    assert sh.row_el[1] == "heading"
    assert sh.appearance["elements"]["heading"]["bold"] is True
    assert sh.aligns[3] == "right"
    assert sh.vertical == [True] * sh.ncols


def test_sheet_number_formats():
    rs, s = _wall_takeoff()
    sh = build_sheet(P.build_table(rs, s).excel)
    assert sh.numfmts[4] == u"0.000"           # Thickness: length, 3 decimals (units.DEFAULT_DECIMALS)
    assert sh.numfmts[0] == u"General"         # Order is an integer: no format
    assert sh.numfmts[6] == u"0.00"            # Material Area: area, 2 decimals
    assert sh.decimals[4] == 3 and sh.prefixes[4] == u""


def test_sheet_without_calculations_has_no_formulas():
    """No calculations: no formulas. The body rows match the pipeline's matrix. The title row is
    case-transformed for Excel (default preset: UPPER), while to_matrix() keeps the raw title."""
    rs = doors()
    tbl = P.build_table(rs, settings(rs)).excel
    sh = build_sheet(tbl)
    assert sh.formulas == {}
    assert sh.values[1:] == tbl.to_matrix()[1:]
    assert sh.values[0][0] == tbl.title.upper()

def test_apply_hidden_headings():
    rs = walls()
    s = P.default_settings(rs, "takeoff", u"T")
    P.apply_hidden_headings(rs, s, u"Wall Type Name; order , Type Mark")
    hid = [f["key"] for f in s["fields"] if f["hiddenInRevit"]]
    assert sorted(hid) == sorted([P.K_TYPE_NAME, P.K_LAYER_ORDER])
    P.apply_hidden_headings(rs, s, u"")
    assert not any(f["hiddenInRevit"] for f in s["fields"])


def test_heading_orientation_comes_only_from_appearance():
    """A field's own orientation setting does not exist: heading orientation is an Appearance choice."""
    rs = doors()
    s = settings(rs)
    assert all("orientation" not in f for f in s["fields"])
    s["appearance"]["elements"]["heading"]["orientation"] = "vertical"
    sh = build_sheet(P.build_table(rs, s).excel)
    assert sh.vertical == [True] * sh.ncols

def _cost_set():
    """One type, two elements on L0, both with a cost of 12.5 (currency, no width or height)."""
    rs = RecordSet(-2000023, u"Doors")
    for f in core_fields(False):
        rs.add_field(f)
    rs.add_field(Field(COST, u"Cost", "element", "currency"))
    rs.add_type(TypeRecord(600, {K_TYPE_MARK: u"D1", K_FAMILY: u"Single", K_TYPE_NAME: u"0900x2100"}))
    rs.add_element(ElementRecord(1, 600, {K_LEVEL: u"L0", COST: 12.5}))
    rs.add_element(ElementRecord(2, 600, {K_LEVEL: u"L0", COST: 12.5}))
    return rs


def test_currency_prefix_in_revit_text_and_excel_format():
    """Currency: the Revit text and the Excel format both carry the '$' prefix and 2 decimals.
    The Excel cell keeps the number, so the value is still usable in formulas."""
    rs = _cost_set()
    s = P.default_settings(rs, "schedule", u"Cost check")
    s["fields"].append(P.field_setting(COST))
    res = P.build_table(rs, s)
    cols = [c.key for c in res.excel.columns]
    i = cols.index(COST)

    sh = build_sheet(res.excel)
    assert sh.numfmts[i] == u'"$ "0.00'
    assert sh.values[2][i] == 12.5                       # the number, not text

    lay = build_layout(res.revit, 2.5, 490)
    data = [t[1] for t in lay.pages[0].texts if t[0] == "data"]
    assert u"$ 12.50" in data

    
if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for n, f in tests:
        f()
        print("ok   " + n)
    print("%d tests passed" % len(tests))
    #sh = _calc_sheet()
    #for i, row in enumerate(sh.values, 1):
    #    print(i, row)
    #print(sorted(sh.formulas.items()))