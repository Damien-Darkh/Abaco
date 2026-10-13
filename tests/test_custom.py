# -*- coding: utf-8 -*-
"""Custom (formula) fields in the table (Phase 6). Run: python3 tests/test_custom.py   (no Revit needed)

Fixtures are tiny hand-built projects. Expected values are worked out by hand in the comments.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from abaco.records import (Field, Layer, TypeRecord, ElementRecord, RecordSet, core_fields,
                           K_TYPE_MARK, K_TYPE_NAME, K_FAMILY, K_LEVEL, K_WIDTH, K_HEIGHT, K_AREA, K_COUNT,
                           K_LAYER_THICKNESS)
from abaco import pipeline as P
from abaco import evaluate as EV

CMT = u"CMT"


def doors(height5=2.2):
    """D1 L0 x2 (area 1.89 each), D1 L1 x1, D2 L0 1.0 x 2.1 and D2 L0 1.0 x height5.
    Rows (default grouping): D1/L0 count 2 area 3.78 | D2/L0 h2.1 count 1 area 2.1 | D2/L0 h2.2 count 1 | D1/L1."""
    rs = RecordSet(-2000023, u"Doors")
    for f in core_fields(False):
        rs.add_field(f)
    rs.add_field(Field(CMT, u"Comments", "element", "text"))
    rs.add_type(TypeRecord(600, {K_TYPE_MARK: u"D1", K_FAMILY: u"Single", K_TYPE_NAME: u"0900x2100"}))
    rs.add_type(TypeRecord(700, {K_TYPE_MARK: u"D2", K_FAMILY: u"Single", K_TYPE_NAME: u"1000x2100"}))

    def el(i, t, lv, w, h, c, a):
        rs.add_element(ElementRecord(i, t, {K_LEVEL: lv, K_WIDTH: w, K_HEIGHT: h, CMT: c, K_AREA: a}))
    el(1, 600, u"L0", 0.9, 2.1, u"a", 1.89)
    el(2, 600, u"L0", 0.9, 2.1, u"b", 1.89)
    el(3, 600, u"L1", 0.9, 2.1, u"a", 1.89)
    el(4, 700, u"L0", 1.0, 2.1, u"c", 2.1)
    el(5, 700, u"L0", 1.0, height5, None, 2.2)
    return rs


def walls():
    """One layered type (0.2 + 0.05 + 0.02) with two elements on L0."""
    rs = RecordSet(-2000011, u"Walls")
    for f in core_fields(True):
        rs.add_field(f)
    rs.add_type(TypeRecord(100, {K_TYPE_MARK: u"A1", K_TYPE_NAME: u"Brick"}, [
        Layer(1, 10, u"Brick", 0.2, u"Structure"),
        Layer(2, None, u"None / Air", 0.05, u"Insulation"),
        Layer(3, 11, u"Plaster", 0.02, u"Finish")]))
    rs.add_element(ElementRecord(1, 100, {K_LEVEL: u"L0", K_AREA: 20.0}, {10: 10.0, 11: 5.0}))
    rs.add_element(ElementRecord(2, 100, {K_LEVEL: u"L0", K_AREA: 12.0}, {10: 6.0, 11: 3.0}))
    return rs


def custom(key, name, formula):
    return {"key": key, "name": name, "formula": formula}


def setup(rs, defs, table_type="schedule", extra_fields=(), **kw):
    s = P.default_settings(rs, table_type, u"T")
    s["custom"] = list(defs)
    for d in defs:
        s["fields"].append(P.field_setting(d["key"]))
    for f in extra_fields:
        s["fields"].append(f)
    s.update(kw)
    return s


def column(res, heading):
    """Values of one column over the data rows (blank spacer and footer rows left out)."""
    m = res.table.to_matrix()
    i = m[1].index(heading)
    rows = [r for blk in res.table.blocks for r in blk if r.kind == "data"]
    lines = [dict(zip([c.key for c in res.table.columns], ln)) for ln in
             [l for blk in res.table.rendered_blocks() for k, l in blk if k == "data"]]
    assert len(rows) == len(lines)
    key = [c.key for c in res.table.columns][i]
    return [ln[key] for ln in lines]


def build(rs, s):
    return P.build_table(rs, s)


# ------------------------------------------------------------------------------------ catalogue
def test_attach_adds_typed_fields_and_replaces_in_place():
    rs = doors()
    s = setup(rs, [custom(u"calc:1", u"Door Area", u"{@WIDTH} * {@HEIGHT}")])
    customs, order, warns = P.attach_custom(rs, s)
    f = rs.field(u"calc:1")
    assert f.scope == "formula" and f.kind == "area" and f.unit == u"m\u00b2" and f.result == ("num", 2, False)
    assert order == [u"calc:1"] and warns == [] and customs[u"calc:1"].broken is None
    pos = rs.fields.index(f)
    s["custom"][0]["formula"] = u"{@WIDTH}"                  # edited: now a length
    P.attach_custom(rs, s)
    assert rs.field(u"calc:1").kind == "length" and rs.fields.index(rs.field(u"calc:1")) == pos
    s["custom"] = []                                          # deleted: gone from the catalogue
    P.attach_custom(rs, s)
    assert rs.field(u"calc:1") is None


def test_result_kinds_for_every_type():
    rs = doors()
    cases = [(u"{@WIDTH} * {@HEIGHT} * {@WIDTH}", "volume"), (u"{@COUNT} + 1", "integer"),
             (u"{@WIDTH} / {@HEIGHT}", "number"), (u'{@FAMILY} + "!"', "text"), (u"{@COUNT} > 1", "yesno"),
             (u"{@WIDTH} ^ 4", "number")]
    s = setup(rs, [custom(u"c%d" % i, u"F%d" % i, t) for i, (t, k) in enumerate(cases)])
    P.attach_custom(rs, s)
    for i, (t, k) in enumerate(cases):
        assert rs.field(u"c%d" % i).kind == k, (t, rs.field(u"c%d" % i).kind)
    assert rs.field(u"c5").unit == u"m^4"                    # no kind of its own: a number with the unit as text


def test_display_labels_keep_a_clashing_name_apart():
    rs = doors()
    s = setup(rs, [custom(u"calc:1", u"Family", u'{@FAMILY} + "!"')])
    P.attach_custom(rs, s)
    labs = rs.display_labels()
    assert labs[u"calc:1"] != labs[u"@FAMILY"] and u"custom" in labs[u"calc:1"]


# ---------------------------------------------------------------------------- per-row evaluation
def test_formula_sees_the_row_not_the_element():
    rs = doors()
    s = setup(rs, [custom(u"calc:1", u"Door Area", u"{@WIDTH} * {@HEIGHT}")])
    assert column(build(rs, s), u"Door Area") == [1.89, 2.1, 2.2, 1.89]       # 0.9*2.1, 1*2.1, 1*2.2, 0.9*2.1


def test_group_count_and_summed_area_are_row_values():
    rs = doors()
    s = setup(rs, [custom(u"calc:1", u"Average", u"{@AREA} / {@COUNT}")],
              extra_fields=[P.field_setting(K_AREA, include=False)])           # in the field list, not shown
    res = build(rs, s)
    assert [c.heading for c in res.table.columns][-1] == u"Average" and u"Area (m\u00b2)" not in [c.heading for c in res.table.columns]
    assert column(res, u"Average") == [1.89, 2.1, 2.2, 1.89]                   # D1/L0: 3.78 / 2
    s["custom"][0]["formula"] = u"{@AREA} * 2"
    assert column(build(rs, s), u"Average")[0] == 7.56                         # doubles the group's SUM


def test_chain_of_custom_fields_in_any_order_and_unlisted_middle_field():
    rs = doors()
    defs = [custom(u"calc:2", u"Per Leaf", u"{calc:1} / {@COUNT}"),
            custom(u"calc:1", u"Door Area", u"{@WIDTH} * {@HEIGHT}")]
    s = setup(rs, defs)
    s["fields"] = [f for f in s["fields"] if f["key"] != u"calc:1"]            # only Per Leaf is a column
    assert column(build(rs, s), u"Per Leaf") == [0.95, 2.1, 2.2, 1.89]         # 1.89/2 = 0.945, shown with 2 decimals


def test_none_input_gives_none_and_shows_the_marker():
    rs = doors(height5=None)
    s = setup(rs, [custom(u"calc:1", u"Door Area", u"{@WIDTH} * {@HEIGHT}")])
    assert column(build(rs, s), u"Door Area") == [1.89, u"#NONE", 2.1, 1.89]    # the empty height sorts first inside D2


def test_division_by_zero_is_error_with_a_warning():
    rs = doors()
    s = setup(rs, [custom(u"calc:1", u"Ratio", u"{@AREA} / ({@COUNT} - 1)")],
              extra_fields=[P.field_setting(K_AREA, include=False)])
    res = build(rs, s)
    assert column(res, u"Ratio") == [3.78, u"#ERROR", u"#ERROR", u"#ERROR"]    # count 1 -> division by zero
    assert any(u"div0: 3" in w and u"3 of 4 rows" in w and u"Ratio" in w for w in res.warnings), res.warnings


def test_varies_input_is_none():
    rs = doors()
    s = setup(rs, [custom(u"calc:1", u"Note", u'{CMT} + "!"')], extra_fields=[P.field_setting(CMT)])
    res = build(rs, s)
    assert column(res, u"Comments") == [u"Varies", u"c", u"", u"a"]
    assert column(res, u"Note") == [u"#NONE", u"c!", u"#NONE", u"a!"]          # D2/h2.2 has no comment: NONE too
    assert not res.warnings


def test_boolean_result_shows_markers_and_keeps_its_case():
    rs = doors()
    s = setup(rs, [custom(u"calc:1", u"Many", u"{@COUNT} > 1")])
    res = build(rs, s)
    assert column(res, u"Many") == [u"#TRUE", u"#FALSE", u"#FALSE", u"#FALSE"]
    s["appearance"]["elements"]["data"]["case"] = "lower"                       # data rows in lower case ...
    res = build(rs, s)
    assert column(res, u"Many") == [u"#TRUE", u"#FALSE", u"#FALSE", u"#FALSE"]   # ... but the markers keep their capitals
    assert column(res, u"Type Name")[0] == u"0900x2100" and column(res, u"Family")[0] == u"single"


# ----------------------------------------------------------------------------------- broken formulas
def test_circular_reference_breaks_only_the_loop():
    rs = doors()
    defs = [custom(u"calc:1", u"A Field", u"{calc:2} + 1"), custom(u"calc:2", u"B Field", u"{calc:1} + 1"),
            custom(u"calc:3", u"Fine", u"{@WIDTH} * 2")]
    res = build(rs, setup(rs, defs))
    assert set(column(res, u"A Field") + column(res, u"B Field")) == set([u"#ERROR"])
    assert column(res, u"Fine") == [1.8, 2.0, 2.0, 1.8]
    assert any(u"circular reference" in w and u"A Field" in w for w in res.warnings), res.warnings


def test_self_reference_is_a_loop():
    rs = doors()
    res = build(rs, setup(rs, [custom(u"calc:1", u"Self", u"{calc:1} + 1")]))
    assert set(column(res, u"Self")) == set([u"#ERROR"]) and any(u"circular" in w for w in res.warnings)


def test_syntax_unit_and_type_errors_keep_the_table_building():
    rs = doors()
    defs = [custom(u"calc:1", u"Bad Syntax", u"{@WIDTH} *"), custom(u"calc:2", u"Bad Unit", u"{@WIDTH} + {@COUNT}"),
            custom(u"calc:3", u"Bad Ref", u"{NOPE} + 1"), custom(u"calc:4", u"Good", u"{@WIDTH}")]
    res = build(rs, setup(rs, defs))
    for h in (u"Bad Syntax", u"Bad Unit", u"Bad Ref"):
        assert set(column(res, h)) == set([u"#ERROR"]), h
    assert column(res, u"Good") == [0.9, 1.0, 1.0, 0.9]
    msgs = u" | ".join(res.warnings)
    assert msgs.count(u"cannot be calculated") == 3 and u"Bad Unit" in msgs


def test_field_removed_from_the_table_gives_ref_errors():
    rs = doors()
    s = setup(rs, [custom(u"calc:1", u"Door Area", u"{@WIDTH} * {@HEIGHT}")])
    assert column(build(rs, s), u"Door Area")[0] == 1.89
    s["fields"] = [f for f in s["fields"] if f["key"] != K_HEIGHT]             # the x in the field list
    res = build(rs, s)
    assert set(column(res, u"Door Area")) == set([u"#ERROR"])
    assert any(u"ref: 4" in w for w in res.warnings), res.warnings


def test_unchecked_field_is_still_readable():
    rs = doors()
    s = setup(rs, [custom(u"calc:1", u"Door Area", u"{@WIDTH} * {@HEIGHT}")])
    [f for f in s["fields"] if f["key"] == K_HEIGHT][0]["include"] = False
    res = build(rs, s)
    assert u"Height (m)" not in [c.heading for c in res.table.columns]
    assert column(res, u"Door Area") == [1.89, 2.1, 2.2, 1.89]


# -------------------------------------------------------------------------- sort, group, footers
def test_sort_on_a_custom_field_none_first_errors_last():
    rs = doors(height5=None)
    s = setup(rs, [custom(u"calc:1", u"Door Area", u"{@WIDTH} * {@HEIGHT}"),
                   custom(u"calc:2", u"Inverse", u"1 m / ({@WIDTH} - 1 m)")], levels=[P.sort_setting(u"calc:1")])
    assert column(build(rs, s), u"Door Area") == [u"#NONE", 1.89, 1.89, 2.1]
    s["levels"] = [P.sort_setting(u"calc:1", "desc")]
    assert column(build(rs, s), u"Door Area") == [2.1, 1.89, 1.89, u"#NONE"]
    s["levels"] = [P.sort_setting(u"calc:2")]
    inv = column(build(rs, s), u"Inverse")
    assert inv[:2] == [-10.0, -10.0] and inv[2:] == [u"#ERROR", u"#ERROR"]     # 1/(0.9-1) = -10; width 1.0 divides by 0


def test_block_header_of_a_custom_level_uses_the_marker():
    rs = doors(height5=None)
    s = setup(rs, [custom(u"calc:1", u"Door Area", u"{@WIDTH} * {@HEIGHT}")],
              levels=[P.sort_setting(u"calc:1", header=True, gap=True)])
    heads = [r.label for blk in build(rs, s).table.blocks for r in blk if r.kind == "header"]
    assert heads == [u"#NONE", u"1.89", u"2.1"], heads            # 0.9 * 2.1 = 1.8900000000000001 is shown as the cells show it


def test_footer_totals_skip_markers():
    rs = doors(height5=None)
    f = P.field_setting(u"calc:1", calc="total")
    s = setup(rs, [], extra_fields=[f], grandTotals=True)
    s["custom"] = [custom(u"calc:1", u"Door Area", u"{@WIDTH} * {@HEIGHT}")]
    res = build(rs, s)
    tot = [r for blk in res.table.blocks for r in blk if r.kind == "gtotal"]
    assert len(tot) == 1 and abs(tot[0].cells[u"calc:1"] - (1.89 + 2.1 + 1.89)) < 1e-9      # the #NONE row adds nothing


def test_layer_formula_is_summed_on_every_layer_row():
    rs = walls()
    f = P.field_setting(u"calc:1", calc="total")
    s = setup(rs, [], table_type="takeoff", extra_fields=[f])
    s["custom"] = [custom(u"calc:1", u"Double", u"{@LAYER_THICKNESS} * 2")]
    P.attach_custom(rs, s)
    assert rs.field(u"calc:1").per_row is True
    res = build(rs, s)
    assert column(res, u"Double") == [0.4, 0.1, 0.04]
    totals = [r for blk in res.table.blocks for r in blk if r.kind == "total"]
    assert len(totals) == 1 and abs(totals[0].cells[u"calc:1"] - 0.54) < 1e-9, totals[0].cells   # all three layers, not just the first
    s["custom"][0]["formula"] = u"{@AREA} * 2"                                 # no layer value used: one value per group
    P.attach_custom(rs, s)
    assert rs.field(u"calc:1").per_row is False


# ------------------------------------------------------------------------------------- settings
def test_default_settings_have_a_custom_list_and_required_keys_cover_custom_fields():
    rs = doors()
    s = P.default_settings(rs, "schedule", u"T")
    assert s["custom"] == []
    s2 = setup(rs, [custom(u"calc:1", u"Door Area", u"{@WIDTH}")])
    assert u"calc:1" in P.required_keys(s2)


def test_sort_value_orders_formula_values():
    vals = [EV.Err("div0", u"x"), True, 2.5, EV.NONE, False, u"b", None]
    out = sorted(vals, key=P.sort_value)
    assert out[0] is EV.NONE or out[0] is None and out[1] is not out[0]      # the two empty kinds first
    assert [v for v in out if isinstance(v, bool)] == [False, True]          # FALSE before TRUE
    assert out.index(2.5) < out.index(u"b") and isinstance(out[-1], EV.Err)  # numbers, then text, errors last


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for n, f in tests:
        f()
        print("ok   " + n)
    print("%d tests passed" % len(tests))
