# -*- coding: utf-8 -*-
"""Layout engine and Excel sheet model (Phase 3). Run: python3 tests/test_outputs.py   (no Revit needed)"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)

from abaco.records import (K_TYPE_MARK, K_FAMILY, K_WIDTH, K_LAYER_THICKNESS, K_LAYER_AREA)
from abaco import pipeline as P
from abaco.layout import build_layout
from abaco.sheet import build_sheet
from test_pipeline import walls, doors, settings, fs

TEXT = 2.5
ROW_H = 6.0                      # max(2.5 * 2.4, 5)
PAD_X = 2.0
CHAR_W = 1.55


def _layout(rs, s, page_h=490, revit=True):
    r = P.build_table(rs, s)
    return build_layout(r.revit if revit else r.table, TEXT, page_h)


# ----------------------------------------------------------------------------------------------- layout
def test_basic_geometry_and_header_by_position():
    lay = _layout(doors(), settings(doors()))
    assert lay.n_cols == 7 and lay.n_blocks == 3 and len(lay.pages) == 1
    pg = lay.pages[0]
    assert pg.nrows == 4
    heads = [t for t in pg.texts if t[0] == "head"]
    assert [t[1] for t in heads] == [u"Type Mark", u"Family", u"Type Name", u"Width (m)", u"Height (m)",
                                     u"Count", u"Level"]
    first_cell = [t for t in pg.texts if t[0] == "cell"][0]
    assert first_cell[1] == u"D1" and abs(first_cell[2] - PAD_X) < 1e-9 and first_cell[4] is None
    assert [t for t in pg.texts if t[0] == "title"][0][5] == "center"


def test_header_does_not_depend_on_type_mark_column():
    rs = doors()
    s = settings(rs)
    s["fields"][0]["include"] = False                     # Type Mark gone: v1 would have failed here
    s["fields"][1]["heading"] = u"Famiglia"
    lay = _layout(rs, s)
    assert [t[1] for t in lay.pages[0].texts if t[0] == "head"][0] == u"Famiglia"


def test_alignment_gets_fixed_width_box():
    rs = doors()
    s = settings(rs)
    fs(s, K_WIDTH)["align"] = "right"
    fs(s, K_FAMILY)["align"] = "center"
    lay = _layout(rs, s)
    col = 3                                               # Width (m)
    wcells = [t for t in lay.pages[0].texts if t[0] == "cell" and abs(t[2] - (lay.col_x[col] + PAD_X)) < 1e-9]
    assert wcells and all(t[5] == "right" and abs(t[4] - (lay.col_w[col] - 2 * PAD_X)) < 1e-9 for t in wcells)
    fam = [t for t in lay.pages[0].texts if t[0] == "cell" and t[1] == u"Single"]
    assert fam and all(t[5] == "center" and t[4] is not None for t in fam)


def test_fixed_width_column():
    rs = doors()
    s = settings(rs)
    fs(s, K_FAMILY)["widthMm"] = 40
    lay = _layout(rs, s)
    assert lay.col_w[1] == 40.0 and abs(lay.table_w - sum(lay.col_w)) < 1e-9


def test_vertical_heading_raises_header_and_rotates():
    rs = doors()
    s = settings(rs)
    fs(s, K_TYPE_MARK)["orientation"] = "vertical"
    s["fields"][0]["heading"] = u"Type Mark long heading"
    lay = _layout(rs, s)
    need = len(u"Type Mark long heading") * CHAR_W + 2 * PAD_X
    assert abs(lay.header_h - need) < 1e-9 and lay.header_h > ROW_H
    head = [t for t in lay.pages[0].texts if t[0] == "head"][0]
    assert head[6] == 90 and head[4] is None
    assert lay.col_w[0] < need                            # the heading does not widen the column


def test_total_rows_are_bold_and_stay_with_their_block():
    rs = walls()
    s = settings(rs)
    fs(s, K_LAYER_THICKNESS)["calc"] = "total"
    lay = _layout(rs, s, page_h=60)
    total_txt = [t for p in lay.pages for t in p.texts if t[0] == "total"]
    assert any(t[1] == u"Total" for t in total_txt) and any(t[1] == 0.27 or t[1] == u"0.27" for t in total_txt)
    assert sum(p.nrows for p in lay.pages) == 8 + 3          # 8 data rows + one total row for 3 blocks
    assert [t[1] for t in total_txt if t[1] == u"Total"] == [u"Total"] * 3


def test_pagination_never_splits_a_block():
    rs = walls()
    lay = _layout(rs, settings(rs), page_h=60)
    assert [p.nrows for p in lay.pages] == [5, 3]         # blocks of 3,1,1 | 3 rows
    assert lay.n_blocks == 4


def test_revit_table_has_only_visible_columns():
    rs = walls()
    lay = _layout(rs, settings(rs))
    assert lay.n_cols == 6


# ------------------------------------------------------------------------------------------------ sheet
def _calc_sheet():
    rs = walls()
    s = settings(rs, grandTotals=True)
    fs(s, K_LAYER_THICKNESS)["calc"] = "total"
    fs(s, K_LAYER_AREA)["calc"] = "minmax"
    return build_sheet(P.build_table(rs, s).excel)


def test_sheet_block_formulas():
    sh = _calc_sheet()
    f = sh.formulas
    assert f[(6, 5)] == u"=SUM(E3:E5)"                    # thickness total, block 1
    assert f[(7, 7)] == u"=MIN(G3:G5)" and f[(8, 7)] == u"=MAX(G3:G5)"
    assert f[(11, 5)] == u"=SUM(E10)"                     # single-row block
    assert f[(20, 5)] == u"=SUM(E17:E19)"
    assert sh.values[5][0] == u"Total" and sh.values[6][0] == u"Min"        # rows 6 and 7 (0-based 5, 6)


def test_sheet_grand_total_formulas_combine_blocks():
    sh = _calc_sheet()
    assert sh.formulas[(24, 5)] == u"=SUM(E3:E5,E10,E15,E17:E19)"
    assert sh.formulas[(25, 7)] == u"=MIN(G3:G5,G10,G15,G17:G19)"
    assert sh.formulas[(26, 7)] == u"=MAX(G3:G5,G10,G15,G17:G19)"
    assert sh.values[23][0] == u"Grand total"


def test_sheet_bold_rows_formats_and_alignment():
    sh = _calc_sheet()
    assert sh.header_row == 2 and sh.bold_rows[0] == 2
    assert sorted(sh.bold_rows) == [2, 6, 7, 8, 11, 12, 13, 20, 21, 22, 24, 25, 26]
    assert sh.nrows == 26 and sh.ncols == 9
    assert sh.numfmts[4] == u"0.0000" and sh.numfmts[0] == u"General" and sh.numfmts[6] == u"0.00"
    rs = doors()
    s = settings(rs)
    fs(s, K_WIDTH)["align"] = "right"
    fs(s, K_FAMILY)["orientation"] = "vertical"
    sh = build_sheet(P.build_table(rs, s).excel)
    assert sh.aligns[3] == "right" and sh.vertical[1] is True and sh.vertical[0] is False


def test_sheet_without_calculations_has_no_formulas():
    rs = doors()
    sh = build_sheet(P.build_table(rs, settings(rs)).excel)
    assert sh.formulas == {} and sh.bold_rows == [2]
    assert sh.values == P.build_table(rs, settings(rs)).excel.to_matrix()


def test_apply_hidden_headings():
    rs = walls()
    s = settings(rs)
    P.apply_hidden_headings(rs, s, u"Wall Type Name; order , Type Mark")
    hid = [f["key"] for f in s["fields"] if f["hiddenInRevit"]]
    assert sorted(hid) == sorted([P.K_TYPE_NAME, P.K_LAYER_ORDER])       # Type Mark never hidden, Function shown
    P.apply_hidden_headings(rs, s, u"")
    assert not any(f["hiddenInRevit"] for f in s["fields"])


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for n, f in tests:
        f()
        print("ok   " + n)
    print("%d tests passed" % len(tests))
