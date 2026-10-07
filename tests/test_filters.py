# -*- coding: utf-8 -*-
"""Run with:  python3 tests/test_filters.py   (no Revit needed)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

from abaco.records import (Field, TypeRecord, ElementRecord, RecordSet,
                           K_TYPE_MARK, K_LEVEL, K_HEIGHT, K_COUNT, K_LAYER_MATERIAL)
from abaco import filters as F


def make_set():
    rs = RecordSet(1, u"Walls")
    rs.add_field(Field(K_TYPE_MARK, u"Type Mark", "type", "text"))
    rs.add_field(Field(K_LEVEL, u"Base Constraint", "element", "text"))
    rs.add_field(Field(K_HEIGHT, u"Height (m)", "element", "length"))
    rs.add_field(Field(K_COUNT, u"Count", "group", "integer"))
    rs.add_field(Field(K_LAYER_MATERIAL, u"Material", "layer", "text"))
    rs.add_field(Field(u"CMT", u"Comments", "element", "text"))
    rs.add_field(Field(u"FIRE", u"Fire Rating", "type", "text"))
    rs.add_field(Field(u"LOAD", u"Load Bearing", "element", "yesno"))
    for f in rs.fields:
        rs.loaded_keys.add(f.key)
    rs.add_type(TypeRecord(1, {K_TYPE_MARK: u"A1", u"FIRE": u"EI 60"}))
    rs.add_type(TypeRecord(2, {K_TYPE_MARK: u"B2", u"FIRE": None}))
    rs.add_element(ElementRecord(10, 1, {K_LEVEL: u"L0", K_HEIGHT: 3.0, u"CMT": u"North  wing", u"LOAD": u"Yes"}))
    rs.add_element(ElementRecord(11, 1, {K_LEVEL: u"L1", K_HEIGHT: 2.5, u"CMT": None, u"LOAD": u"No"}))
    rs.add_element(ElementRecord(12, 2, {K_LEVEL: u"L1", K_HEIGHT: None, u"CMT": u"north", u"LOAD": None}))
    return rs


def run(rs, conds, match="all"):
    return F.apply_filters(rs, rs.elements, {"match": match, "conditions": conds})


def ids(res):
    return [e.element_id for e in res.kept]


def c(key, op, value=u""):
    return {"key": key, "op": op, "value": value}


def test_text_ops_case_and_space_insensitive():
    rs = make_set()
    assert ids(run(rs, [c(u"CMT", "contains", u"NORTH WING")])) == [10]     # double space collapsed
    assert ids(run(rs, [c(u"CMT", "begins", u"north")])) == [10, 12]
    assert ids(run(rs, [c(u"CMT", "ends", u"wing")])) == [10]
    assert ids(run(rs, [c(u"CMT", "not_contains", u"wing")])) == [11, 12]   # empty comment passes
    assert ids(run(rs, [c(u"CMT", "eq", u"NORTH")])) == [12]


def test_numeric_decimal_comma_and_missing():
    rs = make_set()
    assert ids(run(rs, [c(K_HEIGHT, "ge", u"2,5")])) == [10, 11]            # missing height fails
    assert ids(run(rs, [c(K_HEIGHT, "gt", u"2.5")])) == [10]
    assert ids(run(rs, [c(K_HEIGHT, "lt", u"3")])) == [11]
    assert ids(run(rs, [c(K_HEIGHT, "le", u"3")])) == [10, 11]
    assert ids(run(rs, [c(K_HEIGHT, "eq", u"3")])) == [10]
    assert ids(run(rs, [c(K_HEIGHT, "ne", u"3")])) == [11, 12]              # missing is "not equal"


def test_type_scope_field_and_empty_ops():
    rs = make_set()
    assert ids(run(rs, [c(u"FIRE", "no_value")])) == [12]
    assert ids(run(rs, [c(u"FIRE", "eq", u"ei 60")])) == [10, 11]
    assert ids(run(rs, [c(u"CMT", "has_value")])) == [10, 12]
    assert ids(run(rs, [c(u"CMT", "no_value")])) == [11]


def test_yesno():
    rs = make_set()
    assert ids(run(rs, [c(u"LOAD", "eq", u"yes")])) == [10]
    assert ids(run(rs, [c(u"LOAD", "ne", u"yes")])) == [11, 12]
    assert u"contains" not in [code for code, _ in F.operators_for("yesno")]


def test_and_or():
    rs = make_set()
    conds = [c(K_LEVEL, "eq", u"l1"), c(u"CMT", "has_value")]
    assert ids(run(rs, conds, "all")) == [12]
    assert ids(run(rs, conds, "any")) == [10, 11, 12]


def test_incomplete_conditions_are_skipped_silently():
    rs = make_set()
    res = run(rs, [c(u"CMT", "contains", u""), c(K_HEIGHT, "gt", u"  ")])
    assert len(res.kept) == 3 and res.n_active == 0 and res.n_incomplete == 2
    assert res.warnings == [] and u"waiting" in res.summary()
    res = run(rs, [c(u"CMT", "contains", u""), c(K_LEVEL, "eq", u"L0")])
    assert ids(res) == [10] and res.n_incomplete == 1


def test_bad_conditions_skipped_with_error_per_index():
    rs = make_set()
    conds = [c(u"NOPE", "eq", u"x"),
             c(K_LAYER_MATERIAL, "eq", u"x"),
             c(K_COUNT, "gt", u"1"),
             c(K_HEIGHT, "gt", u"abc"),
             c(K_HEIGHT, "contains", u"1"),
             c(K_LEVEL, "eq", u"L0")]
    res = run(rs, conds)
    assert [bool(e) for e in res.errors] == [True, True, True, True, True, False]
    assert len(res.warnings) == 5 and res.warnings[0].startswith(u"Filter 1 skipped")
    assert ids(res) == [10]                                                 # the one valid condition still applies


def test_unloaded_field_is_reported_not_silently_empty():
    rs = make_set()
    rs.loaded_keys.discard(u"CMT")
    res = run(rs, [c(u"CMT", "has_value")])
    assert res.errors == [u"values of 'Comments' are not loaded yet"] and len(res.kept) == 3


def test_empty_result_and_summary():
    rs = make_set()
    res = run(rs, [c(K_LEVEL, "eq", u"L9")])
    assert res.kept == [] and res.matched == 0 and res.summary().startswith(u"0 of 3")
    assert run(rs, []).summary().startswith(u"No filter applied")


def test_input_elements_not_mutated():
    rs = make_set()
    before = list(rs.elements)
    run(rs, [c(K_LEVEL, "eq", u"L0")])
    assert rs.elements == before


def test_normalize_settings_handles_corrupt_input():
    assert F.normalize_settings(None) == F.default_settings()
    assert F.normalize_settings("junk") == F.default_settings()
    d = F.normalize_settings({"match": "any", "conditions": [5, {"key": "K", "op": "eq", "value": 3}, {}]})
    assert d["match"] == "any" and len(d["conditions"]) == 2
    assert d["conditions"][0] == {"key": u"K", "op": u"eq", "value": u"3"}
    assert F.normalize_settings({"match": "weird"})["match"] == "all"


def test_needed_keys():
    s = {"conditions": [c(u"CMT", "eq", u"x"), {"op": "eq", "value": u"y"}, c(K_LEVEL, "eq", u"z")]}
    assert F.needed_keys(s) == [u"CMT", K_LEVEL]
    assert F.needed_keys(None) == []


def test_operators_by_kind():
    codes = lambda k: [code for code, _ in F.operators_for(k)]
    assert codes("length")[:2] == ["eq", "ne"] and "gt" in codes("area")
    assert "contains" in codes("text") and "contains" in codes("elementid")
    assert codes("text")[-2:] == ["has_value", "no_value"]
    assert F.needs_value("eq") and not F.needs_value("has_value")


def test_filtered_view_shares_records_but_not_elements():
    rs = make_set()
    res = run(rs, [c(K_LEVEL, "eq", u"L1")])
    v = F.filtered_view(rs, res.kept)
    assert [e.element_id for e in v.elements] == [11, 12]
    assert len(rs.elements) == 3                                           # original untouched
    assert v.types is rs.types and v.loaded_keys is rs.loaded_keys and v.field(K_LEVEL) is rs.field(K_LEVEL)


def test_parse_number():
    assert F.parse_number(u"1,25") == 1.25 and F.parse_number(u" 2 ") == 2.0
    assert F.parse_number(u"x") is None and F.parse_number(None) is None


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for n, f in tests:
        f()
        print("ok   " + n)
    print("%d tests passed" % len(tests))