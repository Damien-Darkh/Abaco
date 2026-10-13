# -*- coding: utf-8 -*-
"""Units and decimals for display. Pure Python: no Revit, no WPF.

Stored values are base units: metres, m2, m3 and radians. Conversion happens once, at output
(pipeline Table._line). Sorting, grouping, footers, filters and formulas always see base values.

Currency is a symbol only. No exchange rate is applied.
"""
import math

try:
    _STR = (str, unicode)
except NameError:
    _STR = (str,)

TOL = 1e-6

# dimension -> [(unit label, units per base unit)]
DIMENSIONS = {
    "length": [(u"mm", 1000.0), (u"cm", 100.0), (u"m", 1.0), (u"Km", 0.001)],
    "area": [(u"mm\u00b2", 1e6), (u"cm\u00b2", 1e4), (u"m\u00b2", 1.0), (u"Km\u00b2", 1e-6)],
    "volume": [(u"mm\u00b3", 1e9), (u"cm\u00b3", 1e6), (u"m\u00b3", 1.0), (u"Km\u00b3", 1e-9)],
    "angle": [(u"rad", 1.0), (u"\u00b0", 180.0 / math.pi),
              (u"'", 10800.0 / math.pi), (u"''", 648000.0 / math.pi)],
    "currency": [(u"$", 1.0), (u"\u20ac", 1.0), (u"\u00a5 JPY", 1.0),
                 (u"\u00a3", 1.0), (u"\u00a5 CNY", 1.0)],
}

# unit that stored values are in
BASE_UNIT = {"length": u"m", "area": u"m\u00b2", "volume": u"m\u00b3", "angle": u"rad", "currency": None}

# fallback when Revit's project units cannot be read or are not in the list
DEFAULT_UNIT = {"length": u"m", "area": u"m\u00b2", "volume": u"m\u00b3", "angle": u"\u00b0", "currency": u"$"}
DEFAULT_DECIMALS = {"length": 3, "area": 2, "volume": 3, "angle": 0, "currency": 2}

# decimal choices, with the example shown in the drop-down
DECIMAL_CHOICES = [(u"1234", 0), (u"1234.0", 1), (u"1234.00", 2), (u"1234.000", 3), (u"1234.0000", 4)]


def is_dimension(dim):
    return dim in DIMENSIONS


def allowed_units(dim):
    """Unit labels offered in the Formatting drop-down for a dimension. [] when there is none."""
    if dim not in DIMENSIONS:
        return []
    return [lab for lab, _ in DIMENSIONS[dim]]


def match_unit(dim, units_per_base):
    """Label of the allowed unit for a Revit unit, given how many of it make one base unit.
    None when the unit is not in the list (feet, inches, ...) or the dimension is currency."""
    if dim not in DIMENSIONS or dim == "currency":
        return None
    for label, per_base in DIMENSIONS[dim]:
        if abs(units_per_base - per_base) <= TOL * per_base:
            return label
    return None


def factor(dim, unit):
    """Units per base unit for a unit label."""
    return dict(DIMENSIONS[dim])[unit]


def to_display(value, dim, unit):
    """Base value -> display unit. Values without a dimension or unit are returned unchanged."""
    if value is None or dim is None or unit is None:
        return value
    return value * factor(dim, unit)


def heading_suffix(dim, unit):
    """' (m)' for a dimensioned field, '' otherwise."""
    return u" (%s)" % unit if dim and unit else u""


def excel_format(decimals, prefix=u""):
    """Excel number format. None = General. A currency prefix is quoted before the number: "$ "0.00"""
    if decimals is None:
        return u"General"
    body = u"0" + (u"." + u"0" * decimals if decimals else u"")
    return (u'"%s "' % prefix if prefix else u"") + body


def _is_number(v):
    return v is not None and not isinstance(v, bool) and not isinstance(v, _STR)


def format_text(value, decimals, prefix=u""):
    """Revit text for one cell. Currency keeps its symbol: '$ 1234.00'. decimals None = no rounding."""
    if value is None or value == u"":
        return u""
    if not _is_number(value):
        return u"%s" % value
    if decimals is None:
        return u"%s" % value
    text = u"%.*f" % (decimals, value)
    return (u"%s %s" % (prefix, text)) if prefix else text