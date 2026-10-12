# -*- coding: utf-8 -*-
"""Formula parser and checker (Phase 5). Run: python3 tests/test_formula.py   (no Revit needed)

Field labels are the full labels the editor shows, for example {Width (m)}.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from abaco.records import Field
from abaco import formula as F

FIELDS = [
    Field(u"@WIDTH", u"Width (m)", "element", "length"),
    Field(u"@HEIGHT", u"Height (m)", "element", "length"),
    Field(u"@AREA", u"Area (m\u00b2)", "element", "area"),
    Field(u"@VOLUME", u"Volume (m\u00b3)", "element", "volume"),
    Field(u"@COUNT", u"Count", "group", "integer"),
    Field(u"@NUMBER", u"Ratio", "element", "number"),
    Field(u"@NAME", u"Type Name", "type", "text"),
    Field(u"ALL_MODEL_TYPE_MARK", u"Type Mark", "type", "text"),
    Field(u"@LOAD", u"Load Bearing", "element", "yesno"),
]
LABELS = dict((f.key, f.label) for f in FIELDS)
M2 = u"m\u00b2"
M3 = u"m\u00b3"


def run(text):
    return F.check(text, FIELDS, LABELS)


def ok(text):
    r = run(text)
    assert not r.errors, (text, [(e.reason, e.message) for e in r.errors])
    return F.unit_of(r.ty)


def bad(text, reason):
    r = run(text)
    reasons = [e.reason for e in r.errors]
    assert reason in reasons, (text, reasons, [e.message for e in r.errors])
    return r.errors


# ------------------------------------------------------------------------------- tokenizer and parser
def test_text_literal_escape():
    assert F._tokenize(u'"a""b"')[0].value == u'a"b'


def test_unclosed_text_and_field():
    bad(u'"abc', "syntax")
    bad(u"{Width (m)", "syntax")
    bad(u"{}", "syntax")


def test_number_forms():
    bad(u".5", "syntax")                     # write 0.5
    bad(u"1e3", "syntax")                    # no scientific notation
    bad(u"2mm", "syntax")                    # unknown unit
    assert ok(u"2.50") == u"unitless"


def test_precedence_and_chain_refused():
    assert ok(u"1 + 2 * 3") == u"unitless"
    bad(u"1 < {Count} < 3", "syntax")


def test_keywords_case_insensitive():
    assert ok(u"true AND FALSE") == u"TRUE or FALSE"
    assert ok(u"True = TRUE") == u"TRUE or FALSE"
    assert ok(u"min({Width (m)}, 2 m)") == u"m"


def test_reserved_and_unavailable():
    bad(u"ELSE", "syntax")
    bad(u"LEN({Type Name})", "syntax")
    r = run(u"LEN({Type Name})")
    assert u"version 2" in r.errors[0].message
    bad(u"Width", "syntax")                  # fields go between braces
    bad(u"True_key", "syntax")
    bad(u"foo({Width (m)})", "syntax")       # unknown function
    bad(u"MIN", "syntax")                    # needs brackets


def test_error_position():
    text = u"{Width (m)} + {Area (m\u00b2)}"
    r = run(text)
    assert r.errors[0].pos == text.index(u"+")


# ----------------------------------------------------------------------------------- unit algebra
def test_products_and_quotients():
    assert ok(u"{Width (m)} * {Height (m)}") == M2
    assert ok(u"{Area (m\u00b2)} / {Width (m)}") == u"m"
    assert ok(u"{Width (m)} * {Height (m)} * {Width (m)}") == M3


def test_add_and_compare_need_same_unit():
    bad(u"{Width (m)} * {Height (m)} + {Height (m)}", "unit")   # m2 + m
    bad(u"{Width (m)} + {Area (m\u00b2)}", "unit")


def test_count_and_units():
    assert ok(u"{Count} m + {Height (m)}") == u"m"       # count with a unit suffix becomes a length
    bad(u"{Count} + {Height (m)}", "unit")
    assert ok(u"{Count} + 1") == u"count"
    assert ok(u"{Count} * 2") == u"count"
    assert ok(u"2 m + {Height (m)}") == u"m"
    bad(u"{Height (m)} m", "unit")                       # a length field already has its unit
    bad(u"{Height (m)} + 1", "unit")
    assert ok(u"{Height (m)} + 0") == u"m"               # literal zero fits any unit
    assert ok(u"0 + {Height (m)}") == u"m"
    assert ok(u"{Height (m)} > 0") == u"TRUE or FALSE"


def test_unit_text():
    assert F.unit_text(F.num(3)) == M3
    assert F.unit_text(F.num(4)) == u"m^4"
    assert F.unit_text(F.num(-1)) == u"m^-1"


def test_power():
    assert ok(u"{Width (m)} ^ 2") == M2
    assert ok(u"{Width (m)} ^ -2") == u"m^-2"             # negative whole number exponent scrutiny
    bad(u"{Width (m)} ^ {Count}", "unit")                # exponent must be a literal
    bad(u"{Width (m)} ^ {Height (m)}", "unit")
    assert ok(u"2 ^ {Count}") == u"unitless"


# --------------------------------------------------------------------------------- division by zero
def test_literal_division_by_zero_refused():
    bad(u"{Width (m)} / 0", "div0")
    bad(u"1 / 0", "div0")
    bad(u"{Width (m)} % 0", "div0")


def test_runtime_division_allowed_by_checker():
    assert ok(u"{Width (m)} / {Ratio}") == u"m"          # zero only shows at run time, as #ERROR


# ------------------------------------------------------------------------------------- functions
def test_sqrt_and_root():
    assert ok(u"SQRT({Area (m\u00b2)})") == u"m"
    bad(u"SQRT({Width (m)})", "unit")
    bad(u"SQRT(-4)", "sqrt_neg")
    assert ok(u"ROOT({Volume (m\u00b3)}, 3)") == u"m"
    bad(u"ROOT({Volume (m\u00b3)}, 2)", "unit")
    bad(u"ROOT({Volume (m\u00b3)}, 1.5)", "type")
    bad(u"ROOT(-8, 2)", "sqrt_neg")
    assert ok(u"ROOT(-8, 3)") == u"unitless"


def test_abs_keeps_unit():
    assert ok(u"ABS({Height (m)} - 1 m)") == u"m"


def test_min_max():
    assert ok(u"MIN({Width (m)}, {Height (m)}, 2 m)") == u"m"
    bad(u"MIN({Width (m)}, {Area (m\u00b2)})", "unit")   # different units: refused at save time
    bad(u"MAX(1)", "syntax")                             # needs two arguments
    assert ok(u"MAX(1, 2)") == u"unitless"


def test_if_function():
    assert ok(u"IF({Load Bearing}, {Width (m)}, {Height (m)})") == u"m"
    assert ok(u"IF({Load Bearing}, 1, IF({Count} > 2, 2, 3))") == u"unitless"
    assert ok(u"IF({Load Bearing}, IF({Count} > 1, {Width (m)}, {Height (m)}), {Height (m)})") == u"m"  # nested IF scrutiny
    bad(u"IF({Width (m)}, 1, 2)", "type")                # condition must be boolean
    bad(u"IF({Load Bearing}, {Width (m)}, 2)", "unit")   # branches need the same unit
    bad(u'IF({Load Bearing}, 1, "a")', "type")           # branches need the same type
    bad(u"IF({Load Bearing}, 1)", "syntax")              # arity


def test_conversions():
    assert ok(u"INT(1.9)") == u"unitless"
    assert ok(u"INT({Type Name})") == u"count"
    assert ok(u"FLOAT({Width (m)})") == u"m"
    assert ok(u"STRING({Width (m)})") == u"text"
    assert ok(u"STRING(2.00)") == u"text"
    bad(u"INT(TRUE)", "type")


# ----------------------------------------------------------------------------- booleans and yes/no
def test_yesno_is_boolean():
    assert ok(u"{Load Bearing} AND {Count} > 2") == u"TRUE or FALSE"
    assert ok(u"{Load Bearing} = TRUE") == u"TRUE or FALSE"
    bad(u"{Load Bearing} = 1", "type")
    bad(u"{Width (m)} AND {Load Bearing}", "type")


def test_boolean_ordering_refused():
    bad(u"TRUE < FALSE", "type")


# ------------------------------------------------------------------------------------------- text
def test_text_operations():
    assert ok(u'{Type Name} + "-"') == u"text"
    bad(u"{Type Name} + 1", "type")
    bad(u'{Type Name} - "a"', "type")
    bad(u'"abc" m', "type")                              # unit after text literal scrutiny
    assert ok(u'{Type Mark} = "A1"') == u"TRUE or FALSE"
    assert ok(u'SENSITIVE({Type Name}) = "abc"') == u"TRUE or FALSE"
    bad(u'SENSITIVE({Type Name}) < "abc"', "type")
    bad(u"SENSITIVE({Width (m)}) = 1", "type")
    bad(u"SENSITIVE({Type Name})", "type")


# ------------------------------------------------------------------------------- references
def test_unknown_field_suggestion():
    r = run(u"{Widht (m)}")
    assert r.errors[0].reason == "ref" and u"Width" in r.errors[0].fix


def test_both_unknown_fields_reported():
    r = run(u"{Widht} + {Heigth}")
    assert [e.reason for e in r.errors] == ["ref", "ref"]


def test_refs_collected():
    r = run(u"{@WIDTH} * {Height (m)}")
    assert not r.errors and r.refs == set([u"@WIDTH", u"@HEIGHT"])


def test_key_check():
    assert F.key_ok(u"@WIDTH") and F.key_ok(u"id:12") and F.key_ok(u"Width (m)")
    assert not F.key_ok(u"a}b") and not F.key_ok(u"") and not F.key_ok(u"a{b")


def test_to_stored_and_editor():
    assert F.to_stored(u"{Width (m)} * 2", {u"Width (m)": u"@WIDTH"}) == u"{@WIDTH} * 2"
    assert F.to_editor(u"{@WIDTH} * 2", {u"@WIDTH": u"Width (m)"}) == u"{Width (m)} * 2"


# ----------------------------------------------------------------------------------------- editor
def test_to_caps_keywords_and_functions():
    assert F.to_caps(u"true and min(2, 3)") == u"TRUE AND MIN(2, 3)"
    assert F.to_caps(u"True") == u"TRUE"
    assert F.to_caps(u"if(true, 1, 2)") == u"IF(TRUE, 1, 2)"


def test_to_caps_leaves_fields_text_and_units():
    assert F.to_caps(u"{True_key} = True_key") == u"{True_key} = True_key"
    assert F.to_caps(u'"true" and x') == u'"true" AND x'
    assert F.to_caps(u"2 m + {Count} m") == u"2 m + {Count} m"


# -------------------------------------------------------------------------------- test runner
if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for n, f in tests:
        f()
        print("ok   " + n)
    print("%d tests passed" % len(tests))