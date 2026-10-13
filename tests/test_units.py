# -*- coding: utf-8 -*-
"""Units and decimals (pure functions). Run: python3 tests/test_units.py   (no Revit needed)"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from abaco import units as U


def test_match_unit_metric():
    assert U.match_unit("length", 1000.0) == u"mm"
    assert U.match_unit("length", 100.0) == u"cm"
    assert U.match_unit("length", 1.0) == u"m"
    assert U.match_unit("length", 0.001) == u"Km"
    assert U.match_unit("area", 1e6) == u"mm\u00b2"
    assert U.match_unit("volume", 1e-9) == u"Km\u00b3"
    assert U.match_unit("angle", 180.0 / math.pi) == u"\u00b0"
    assert U.match_unit("angle", 1.0) == u"rad"


def test_match_unit_rejects_unlisted_and_currency():
    assert U.match_unit("length", 3.28084) is None      # feet per metre
    assert U.match_unit("length", 39.3701) is None      # inches per metre
    assert U.match_unit("currency", 1.0) is None         # never converted by Revit
    assert U.match_unit("count", 1.0) is None


def test_match_unit_tolerance():
    assert U.match_unit("length", 1000.0 * (1 + 1e-9)) == u"mm"
    assert U.match_unit("length", 1000.0 * 1.01) is None


def test_to_display():
    assert abs(U.to_display(2.5, "length", u"mm") - 2500.0) < 1e-9
    assert abs(U.to_display(0.0254, "length", u"m") - 0.0254) < 1e-12
    assert abs(U.to_display(math.pi, "angle", u"\u00b0") - 180.0) < 1e-9
    assert U.to_display(None, "length", u"mm") is None
    assert U.to_display(2.5, None, None) == 2.5
    assert U.to_display(2.5, "length", None) == 2.5


def test_heading_suffix():
    assert U.heading_suffix("length", u"m") == u" (m)"
    assert U.heading_suffix(None, None) == u""
    assert U.heading_suffix("length", None) == u""


def test_excel_format_decimals():
    assert U.excel_format(0) == u"0"
    assert U.excel_format(1) == u"0.0"
    assert U.excel_format(2) == u"0.00"
    assert U.excel_format(4) == u"0.0000"
    assert U.excel_format(None) == u"General"


def test_excel_format_currency_prefix():
    assert U.excel_format(2, u"$") == u'"$ "0.00'
    assert U.excel_format(0, u"\u00a5 JPY") == u'"\u00a5 JPY "0'


def test_format_text_decimals():
    assert U.format_text(1234, 0) == u"1234"
    assert U.format_text(1234, 1) == u"1234.0"
    assert U.format_text(1234, 2) == u"1234.00"
    assert U.format_text(1234.5678, 3) == u"1234.568"
    assert U.format_text(1234.5678, None) == u"1234.5678"


def test_format_text_currency_and_empties():
    assert U.format_text(1234, 2, u"$") == u"$ 1234.00"
    assert U.format_text(None, 2) == u""
    assert U.format_text(u"", 2) == u""
    assert U.format_text(u"Varies", 2) == u"Varies"
    assert U.format_text(True, 2) == u"True"


def test_allowed_units_and_base_units():
    assert U.allowed_units("length") == [u"mm", u"cm", u"m", u"Km"]
    assert U.allowed_units("count") == []
    assert U.BASE_UNIT["angle"] == u"rad" and U.BASE_UNIT["currency"] is None
    assert [d for _, d in U.DECIMAL_CHOICES] == [0, 1, 2, 3, 4]


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for n, f in tests:
        f()
        print("ok   " + n)
    print("%d tests passed" % len(tests))