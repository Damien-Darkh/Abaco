# -*- coding: utf-8 -*-
"""Run with:  python3 tests/test_records.py   (no Revit needed)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

from abaco.records import (Field, Layer, TypeRecord, ElementRecord, RecordSet, core_fields,
                           K_TYPE_MARK, K_LEVEL, K_COUNT, K_LAYER_AREA)


def make_set():
    rs = RecordSet(-2000011, u"Walls")
    for f in core_fields(True):
        rs.add_field(f)
    layers = [Layer(1, 10, u"Brick", 0.12, u"Structure"),
              Layer(2, None, u"None / Air", 0.05, u"Insulation"),
              Layer(3, 10, u"Brick", 0.12, u"Finish")]
    rs.add_type(TypeRecord(100, {K_TYPE_MARK: u"A1"}, layers))
    rs.add_type(TypeRecord(200, {K_TYPE_MARK: u"CW1"}, None, is_curtain=True))
    rs.add_element(ElementRecord(1, 100, {K_LEVEL: u"L0"}, {10: 4.0}))
    rs.add_element(ElementRecord(2, 100, {K_LEVEL: u"L1"}, {10: 6.0}))
    rs.add_element(ElementRecord(3, 200, {K_LEVEL: None}))
    return rs


def test_core_labels_match_v1():
    labels = [f.label for f in core_fields(True)]
    assert u"Wall Type Name" in labels and u"Base Constraint" in labels
    labels = [f.label for f in core_fields(False)]
    assert u"Type Name" in labels and u"Level" in labels
    assert u"Material Area (m\u00b2)" in labels and u"Total Length (m)" in labels


def test_add_field_ignores_duplicates():
    rs = make_set()
    n = len(rs.fields)
    assert rs.add_field(Field(K_TYPE_MARK, u"x", "type", "text")) is False
    assert len(rs.fields) == n
    assert rs.field(K_TYPE_MARK).label == u"Type Mark"


def test_value_resolves_scope():
    rs = make_set()
    e1, e3 = rs.elements[0], rs.elements[2]
    assert rs.value(e1, K_TYPE_MARK) == u"A1"       # type value, stored once per type
    assert rs.value(e1, K_LEVEL) == u"L0"           # element value
    assert rs.value(e3, K_LEVEL) is None            # missing = None
    for key in (K_COUNT, K_LAYER_AREA, "NOPE"):
        try:
            rs.value(e1, key)
            assert False, key
        except KeyError:
            pass


def test_material_ids_distinct_in_order():
    rs = make_set()
    assert rs.types[100].material_ids() == [10]     # repeated brick and the air layer are not duplicated
    assert rs.types[200].material_ids() == []
    assert rs.types[100].is_layered and not rs.types[200].is_layered


def test_modes_split_curtain_walls():
    rs = make_set()
    assert [e.element_id for e in rs.elements_in_mode(False)] == [1, 2]
    assert [e.element_id for e in rs.elements_in_mode(True)] == [3]
    assert rs.has_layered


def test_display_labels_tag_clashes():
    rs = make_set()
    rs.add_field(Field(u"G-1", u"Comments", "element", "text"))
    rs.add_field(Field(u"G-2", u"Comments", "type", "text"))
    lab = rs.display_labels()
    assert lab[u"G-1"] == u"Comments (instance)" and lab[u"G-2"] == u"Comments (type)"
    assert lab[K_TYPE_MARK] == u"Type Mark"


def test_display_labels_twins_use_group():
    rs = make_set()
    rs.add_field(Field(u"A", u"Spacing", "type", "length", group=u"Vertical Grid"))
    rs.add_field(Field(u"B", u"Spacing", "type", "length", group=u"Horizontal Grid"))
    rs.add_field(Field(u"C", u"Category", "type", "elementid"))
    rs.add_field(Field(u"D", u"Category", "type", "elementid"))
    lab = rs.display_labels()
    assert lab[u"A"] == u"Spacing (type, Vertical Grid)" and lab[u"B"] == u"Spacing (type, Horizontal Grid)"
    assert lab[u"C"] != lab[u"D"] and len(set(lab.values())) == len(lab)


def test_field_roundtrip_and_validation():
    f = Field(u"G-1", u"Fire Rating", "type", "text")
    g = Field.from_dict(f.to_dict())
    assert (g.key, g.label, g.scope, g.kind) == (f.key, f.label, f.scope, f.kind)
    try:
        Field("k", "l", "bogus", "text")
        assert False
    except ValueError:
        pass


def test_summary():
    lines = make_set().summary_lines()
    assert u"3 elements, 2 types (1 layered), 1 curtain-wall" in lines[0]


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for n, f in tests:
        f()
        print("ok   " + n)
    print("%d tests passed" % len(tests))
