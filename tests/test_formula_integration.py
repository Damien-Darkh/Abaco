# -*- coding: utf-8 -*-
"""Integration tests for Abaco formula language and record management.
Runs with: python3 tests/test_formula_integration.py (no Revit needed)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from abaco.records import Field
from abaco import formula as F

def test_record_catalogue_to_formula_integration():
    """Verify that records fields, display labels, and formula checks integrate smoothly."""
    # 1. Define standard fields as structured in records.py
    fields = [
        Field(u"@WIDTH", u"Width (m)", "element", "length"),
        Field(u"@HEIGHT", u"Height (m)", "element", "length"),
        Field(u"@VOLUME", u"Volume (m\u00b3)", "element", "volume"),
    ]
    
    # 2. Extract display labels mapping (key -> label)
    label_of = dict((f.key, f.label) for f in fields)
    key_of_label = dict((f.label, f.key) for f in fields)

    # 3. User types using editor form (labels) - multiplying Width * Height gives area (exp 2)
    editor_formula = u"{Width (m)} * {Height (m)}"

    # 4. Convert editor form to stored form (using keys)
    stored_formula = F.to_stored(editor_formula, key_of_label)
    assert stored_formula == u"{@WIDTH} * {@HEIGHT}", f"Unexpected stored form: {stored_formula}"

    # 5. Check formula using the record catalogue and labels
    checked_result = F.check(stored_formula, fields, label_of)
    
    # 6. Assert successful validation and proper ref collection (Width * Height = area, exp 2)
    assert checked_result.ok, f"Formula check failed with errors: {[(e.reason, e.message) for e in checked_result.errors]}"
    assert checked_result.ty.exp == 2, f"Expected area exponent 2, got {checked_result.ty.exp}"
    assert checked_result.refs == set([u"@WIDTH", u"@HEIGHT"]), f"Incorrect refs collected: {checked_result.refs}"

    # 7. Convert back from stored form to editor form
    back_to_editor = F.to_editor(stored_formula, label_of)
    assert back_to_editor == editor_formula, f"Roundtrip conversion mismatch: {back_to_editor}"


def test_label_disambiguation_and_unknown_handling():
    """Verify integration behavior when dealing with suggestions and unknown identifiers."""
    fields = [
        Field(u"@WIDTH", u"Width (m)", "element", "length"),
    ]
    label_of = dict((f.key, f.label) for f in fields)

    # Formula referencing a misspelled field name
    bad_formula = u"{Widht (m)} + 1 m"
    checked_result = F.check(bad_formula, fields, label_of)

    assert not checked_result.ok
    error = checked_result.errors[0]
    assert error.reason == "ref"
    assert u"Width (m)" in error.fix or u"Width" in error.fix


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for n, f in tests:
        f()
        print("ok   " + n)
    print("%d integration tests passed" % len(tests))