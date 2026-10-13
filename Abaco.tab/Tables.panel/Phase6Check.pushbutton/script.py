# -*- coding: utf-8 -*-
"""Phase 6 check (temporary dev button): custom (formula) fields on the real model.

Run in a TEST COPY of the project. Builds Doors and Walls tables with calculated fields and checks each
result against values computed independently: from the row's own cells, from the record set, or from
Excel's own readback. Output is PASS / FAIL / INFO lines in the output window.
Delete this button when Phase 6 is done.
"""
import os
import tempfile
import traceback

from pyrevit import forms, script, revit
from System import Type, Activator, Array, Object
from System.Reflection import BindingFlags

from abaco import revit_reader as rr
from abaco import pipeline as P
from abaco import runner
from abaco import formula as F
from abaco import evaluate as E
from abaco import records as R
from abaco import units as U

doc = revit.doc
out = script.get_output()

DRAW_REVIT = False      # True: also draws the Doors table as drafting views (test copy only)
WRITE_EXCEL = True      # True: writes a temp .xlsx and reads it back through Excel COM
EXCEL_PATH = os.path.join(tempfile.gettempdir(), "abaco_phase6_check.xlsx")
EXCEL_TAB = u"Phase6 doors"

SQM = u"\u00b2"
EPS = 1e-6

try:
    _NUM = (int, long, float)
except NameError:
    _NUM = (int, float)

results = []            # (name, passed)


# ------------------------------------------------------------------ reporting
def check(name, ok, detail=u""):
    results.append((name, bool(ok)))
    out.print_md(u"- **%s** %s%s" % (u"PASS" if ok else u"FAIL", name, (u" - " + detail) if detail else u""))


def info(text):
    out.print_md(u"- INFO %s" % text)


def guarded(name, fn, *args):
    try:
        fn(*args)
    except Exception:
        check(name + u" ran without error", False)
        out.print_md(u"```\n%s\n```" % traceback.format_exc())


def _quiet(msg):
    pass


def _no_fields(key):
    return None


# -------------------------------------------------------------------- helpers
def is_num(v):
    return isinstance(v, _NUM) and not isinstance(v, bool)


def approx(a, b):
    return is_num(a) and is_num(b) and abs(a - b) < EPS


def same(cell, expected):
    """expected is a number (float) or a marker text such as '#NONE' or '#ERROR'."""
    if isinstance(expected, float):
        return approx(cell, expected)
    return cell == expected


def find_category(name):
    for n, count, cat in rr.list_model_categories(doc):
        if n == name:
            return cat
    return None


def field_setting(s, key):
    for f in s["fields"]:
        if f["key"] == key:
            return f
    raise KeyError(key)


def make_settings(rs, customs, table_type, tweak):
    s = P.default_settings(rs, table_type, u"Phase6 check", custom=customs)
    for d in customs:
        s["fields"].append(P.field_setting(d["key"]))
    if tweak is not None:
        tweak(s)
    return s


def build(category_name, customs, table_type="schedule", tweak=None):
    """Read the category, apply the settings and build the table through the same entry point as Run."""
    cat = find_category(category_name)
    if cat is None:
        raise ValueError(u"category %s not in the model" % category_name)
    rs = rr.read_category(doc, cat, _quiet)
    s = make_settings(rs, customs, table_type, tweak)
    res = runner.build_result(doc, rs, s, _quiet)
    return rs, s, res


def data_rows(res):
    return [r for b in res.table.blocks for r in b if r.kind == "data"]


def kind_rows(res, kind):
    return [r for b in res.table.blocks for r in b if r.kind == kind]


def numbers(rows, key):
    return [r.cells.get(key) for r in rows if is_num(r.cells.get(key))]


# ----------------------------------------------------------- Doors: schedule
DOOR_CUSTOMS = [
    {"key": u"calc:1", "name": u"Door Area", "formula": u"{@WIDTH} * {@HEIGHT}"},
    {"key": u"calc:2", "name": u"Ratio", "formula": u"{@WIDTH} * {@HEIGHT} / ({@COUNT} - 1)"},
    {"key": u"calc:3", "name": u"Circ A", "formula": u"{calc:4} + 1"},
    {"key": u"calc:4", "name": u"Circ B", "formula": u"{calc:3} + 1"},
    {"key": u"calc:5", "name": u"Bad Ref", "formula": u"{NOPE} + 1"},
    {"key": u"calc:6", "name": u"Ratio Safe", "formula": u"{@WIDTH} / {@HEIGHT}"},
]


def expect_area(r):
    w, h = r.cells.get(R.K_WIDTH), r.cells.get(R.K_HEIGHT)
    if not (is_num(w) and is_num(h)):
        return u"#NONE"
    return float(w) * float(h)


def expect_ratio(r):
    # NONE is checked before the division, as in evaluate: an empty width or height gives #NONE
    w, h, c = r.cells.get(R.K_WIDTH), r.cells.get(R.K_HEIGHT), r.cells.get(R.K_COUNT)
    if not (is_num(w) and is_num(h)):
        return u"#NONE"
    if c == 1:
        return u"#ERROR"            # count - 1 = 0
    return float(w) * float(h) / (float(c) - 1)


def expect_safe(r):
    w, h = r.cells.get(R.K_WIDTH), r.cells.get(R.K_HEIGHT)
    if not (is_num(w) and is_num(h)):
        return u"#NONE"
    if float(h) == 0:
        return u"#ERROR"
    return float(w) / float(h)


def tw_area_total(s):
    field_setting(s, u"calc:1")["calc"] = "total"
    s["grandTotals"] = True


def run_doors():
    out.print_md(u"## Doors (schedule)")
    rs, s, res = build(u"Doors", DOOR_CUSTOMS)
    rows = data_rows(res)
    check("Doors: rows built", len(rows) > 0, u"%d data rows" % len(rows))

    # --- catalogue and heading
    f1 = rs.field(u"calc:1")
    check("calc:1 is an area field, base unit m%s" % SQM,
          f1 is not None and f1.dim == "area" and f1.base_unit == U.M2,
          u"dim=%s" % (f1.dim if f1 is not None else None))
    heads = [c.heading for c in res.table.columns]
    check("Heading carries the formula unit", u"Door Area (m%s)" % SQM in heads, u" | ".join(heads))

    # --- row values, checked against the row's own width, height and count
    bad = [r for r in rows if not same(r.cells.get(u"calc:1"), expect_area(r))]
    check("Door Area = Width x Height on every row", not bad,
          u"%d of %d rows differ" % (len(bad), len(rows)))

    n_one = sum(1 for r in rows if r.cells.get(R.K_COUNT) == 1)
    bad = [r for r in rows if not same(r.cells.get(u"calc:2"), expect_ratio(r))]
    check("Ratio: count 1 gives #ERROR, other rows divide by (count - 1)", not bad,
          u"%d rows with count 1" % n_one)
    if n_one:
        check("Ratio: division-by-zero warning reported",
              any(u"div0" in w for w in res.warnings))
    else:
        info(u"no row with count 1 in Doors: division-by-zero warning check skipped")

    # --- non-error path: Ratio Safe has no zero divisor on real rows
    bad = [r for r in rows if not same(r.cells.get(u"calc:6"), expect_safe(r))]
    nums = sum(1 for r in rows if is_num(expect_safe(r)))
    check("Ratio Safe = Width / Height on every row", not bad and nums > 0,
          u"%d numeric rows, %d differ" % (nums, len(bad)))

    # --- circular references and unknown fields
    circ = [r for r in rows for k in (u"calc:3", u"calc:4") if r.cells.get(k) != u"#ERROR"]
    check("Circular references show #ERROR", not circ)
    check("Circular reference warning reported",
          any(u"circular" in w for w in res.warnings))

    check("Unknown field gives #ERROR", all(r.cells.get(u"calc:5") == u"#ERROR" for r in rows))
    check("Unknown field warning reported",
          any(u"cannot be calculated" in w and u"Bad Ref" in w for w in res.warnings))

    # --- grand total: independent expectation is sum of area x count over the rows
    rs2, s2, res2 = build(u"Doors", DOOR_CUSTOMS[:1], tweak=tw_area_total)
    gts = kind_rows(res2, "gtotal")
    exp = 0.0
    for r in data_rows(res2):
        w, h, c = r.cells.get(R.K_WIDTH), r.cells.get(R.K_HEIGHT), r.cells.get(R.K_COUNT)
        if is_num(w) and is_num(h) and is_num(c):
            exp += float(w) * float(h) * float(c)
    got = gts[0].cells.get(u"calc:1") if gts else None
    check("Grand total of Door Area = sum of width x height x count over the rows",
          len(gts) == 1 and approx(got, exp),
          u"got %s, expected %.6f" % (got, exp))

    # --- row filter on a calculated field: median threshold, expected count computed in Python
    vals_all = sorted(numbers(rows, u"calc:1"))
    if len(vals_all) >= 2 and vals_all[0] < vals_all[-1] - EPS:
        thr = vals_all[len(vals_all) // 2]
        expected_kept = sum(1 for v in vals_all if v > thr + EPS)

        def tw_filter(s):
            s["filter"] = {"match": "all", "conditions": [
                {"key": u"calc:1", "op": "gt", "value": u"%.9f" % thr}]}

        rs3, s3, res3 = build(u"Doors", DOOR_CUSTOMS[:1], tweak=tw_filter)
        kept = numbers(data_rows(res3), u"calc:1")
        ok = len(kept) == expected_kept and all(v > thr + EPS for v in kept)
        check("Filter on a calculated field keeps the rows above the median", ok,
              u"threshold %.4f: kept %d, expected %d" % (thr, len(kept), expected_kept))
    else:
        info(u"Door Area values are not distinct: filter check skipped")

    # --- Excel: read the written workbook back and compare with the table
    if WRITE_EXCEL:
        try:
            runner.write_excel(EXCEL_PATH, EXCEL_TAB, res)
            got_xl = excel_readback(EXCEL_PATH, EXCEL_TAB[:31])
            if got_xl is None:
                check("Excel: tab found", False, EXCEL_TAB)
            else:
                headers, first = got_xl
                check("Excel: headers match the table", headers == res.excel.headings(),
                      u" | ".join(headers))
                first_row = res.table.blocks[0][0] if res.table.blocks and res.table.blocks[0] else None
                if first_row is not None and first_row.kind == "data" and u"Door Area (m%s)" % SQM in headers:
                    xl_val = first[headers.index(u"Door Area (m%s)" % SQM)]
                    check("Excel: first Door Area cell equals the table's first row",
                          approx(xl_val, first_row.cells.get(u"calc:1")),
                          u"Excel %s, table %s" % (xl_val, first_row.cells.get(u"calc:1")))
                else:
                    info(u"first table row is not a data row: Excel value check skipped")
        except Exception as ex:
            check("Excel: workbook written and read back", False, u"%s" % ex)

    if DRAW_REVIT:
        try:
            with revit.Transaction(u"Phase6 check: draw doors"):
                lines = runner.draw_revit(doc, res, u"Phase6 check - Doors", u"P6", 2.5, 490, None)
            for ln in lines:
                info(ln)
            check("Revit: drafting views drawn", True)
        except Exception as ex:
            check("Revit: drafting views drawn", False, u"%s" % ex)


# ------------------------------------------------- Excel readback (COM, read-only)
def _invoke(o, name, flags, *args):
    return o.GetType().InvokeMember(name, flags, None, o, Array[Object](list(args)))


def _get(o, name, *args):
    return _invoke(o, name, BindingFlags.GetProperty, *args)


def _put(o, name, value):
    _invoke(o, name, BindingFlags.SetProperty, value)


def _call(o, name, *args):
    return _invoke(o, name, BindingFlags.InvokeMethod, *args)


def excel_readback(path, tab):
    """(headers, first data row) of one tab, or None when the tab is missing. Read-only through Excel COM.
    Value2 is used, so numbers come back as numbers. Row 2 holds headings, row 3 the first table row."""
    xl_type = Type.GetTypeFromProgID("Excel.Application")
    app = Activator.CreateInstance(xl_type)
    wb = None
    try:
        _put(app, "Visible", False)
        _put(app, "DisplayAlerts", False)
        wb = _call(_get(app, "Workbooks"), "Open", path, 0, True)
        sheets = _get(wb, "Worksheets")
        ws = None
        for i in range(1, int(_get(sheets, "Count")) + 1):
            s = _get(sheets, "Item", i)
            if (u"%s" % _get(s, "Name")).strip().lower() == tab.strip().lower():
                ws = s
                break
        if ws is None:
            return None
        cells = _get(ws, "Cells")

        def val(r, c):
            return _get(_get(cells, "Item", r, c), "Value2")

        headers, first, col = [], [], 1
        while col <= 200:
            h = val(2, col)
            if h is None or u"%s" % h == u"":
                break
            headers.append(u"%s" % h)
            first.append(val(3, col))
            col += 1
        return headers, first
    finally:
        try:
            if wb is not None:
                _call(wb, "Close", False)
        finally:
            _call(app, "Quit")


# --------------------------------------------------------- Walls: takeoff
WALL_CUSTOMS = [{"key": u"calc:1", "name": u"Layer x2", "formula": u"{@LAYER_THICKNESS} * 2"}]


def expect_layer(r):
    t = r.cells.get(R.K_LAYER_THICKNESS)
    return 2.0 * float(t) if is_num(t) else u"#NONE"


def tw_layer_total(s):
    field_setting(s, u"calc:1")["calc"] = "total"


def footer_expectation(res, rs, footer):
    """(expected, rows covered, layers of the type) for one footer, from the record set.

    The rows a footer totals are the data rows directly above it in its block, back to the first row
    of a different type. The expected value is 2 x the thickness of every layer of that type, taken from
    the record set, so it does not depend on how the pipeline grouped the rows.
    Returns (None, 0, 0) when the footer has no rows above it.
    """
    for b in res.table.blocks:
        if footer not in b:
            continue
        i = b.index(footer)
        if i == 0 or b[i - 1].kind != "data" or not b[i - 1].els:
            return None, 0, 0
        tid = b[i - 1].els[0].type_id
        covered, j = [], i - 1
        while j >= 0 and b[j].kind == "data" and b[j].els and b[j].els[0].type_id == tid:
            covered.insert(0, b[j])
            j -= 1
        layers = rs.types[tid].layers or []
        exp = 2.0 * sum(float(x.thickness) for x in layers)
        return exp, len(covered), len(layers)
    return None, 0, 0


def run_walls():
    out.print_md(u"## Walls (takeoff, per-layer formula)")
    rs, s, res = build(u"Walls", WALL_CUSTOMS, u"takeoff", tw_layer_total)
    rows = data_rows(res)
    check("Walls: layer rows built", len(rows) > 0, u"%d data rows" % len(rows))

    f = rs.field(u"calc:1")
    check("Layer formula is evaluated per layer row", f is not None and f.per_row is True)

    bad = [r for r in rows if not same(r.cells.get(u"calc:1"), expect_layer(r))]
    check("Layer x2 = 2 x Thickness on every layer row", not bad,
          u"%d of %d rows differ" % (len(bad), len(rows)))

    totals = kind_rows(res, "total")
    if not totals:
        info(u"no footer rows in the Walls takeoff: footer check skipped")
        return
    bad_t = []
    for t in totals:
        exp, n_cov, n_lay = footer_expectation(res, rs, t)
        if exp is None or n_cov != n_lay or not approx(t.cells.get(u"calc:1"), exp):
            bad_t.append((t, exp, n_cov, n_lay))
    check("Footer totals equal 2 x the layer thicknesses of their type, from the record set",
          not bad_t, u"%d footer rows checked, %d differ" % (len(totals), len(bad_t)))


# ---------------------------------------------- text and number functions
def run_strings():
    out.print_md(u"## Text and number functions (run without the model)")
    cases = [
        (u"STRING(0.1 + 0.2)", u"0.30000000000000004"),
        (u"STRING(2.00)", u"2.00"),
        (u"STRING(2.5 * 2)", u"5"),
        (u"STRING(-2.50)", u"-2.50"),
        (u"INT(2.5)", 3.0),
        (u"ROOT(64, 3)", 4.0),
    ]
    for text, want in cases:
        r = F.check(text, [], {})
        if r.errors:
            check(u"%s parses" % text, False, r.errors[0].message)
            continue
        got = E.evaluate(r.ast, _no_fields)
        check(u"%s = %s" % (text, want), got == want, u"got %s" % (got,))


# ------------------------------------------------------- project units
def run_units():
    out.print_md(u"## Project units")
    cat = find_category(u"Doors")
    if cat is None:
        return
    rs = rr.read_category(doc, cat, _quiet)
    proj = rs.project or {}
    info(u"Project units read from Revit: %s" % (proj if proj else u"none"))

    if u"area" in proj:
        label, dec = proj[u"area"]
        check("Project area unit read from Revit", True, u"%s, %s decimals" % (label, dec))
        if label != U.M2:
            info(u"project area is %s; the custom heading still shows m%s (checked in Doors)" % (label, SQM))
    else:
        info(u"no area entry in rs.project: the project unit is not in units.DIMENSIONS, or it was not read")

    info(u"Area default the pipeline uses for model fields: %s" % (P.project_default(rs, "area"),))


# ------------------------------------------------------------------- main
def main():
    out.print_md(u"# Phase 6 check: custom fields")
    out.print_md(u"Run in a test copy. DRAW_REVIT = %s, WRITE_EXCEL = %s" % (DRAW_REVIT, WRITE_EXCEL))

    if find_category(u"Doors") is None:
        info(u"Doors not in the model: door checks skipped")
    else:
        guarded(u"Doors", run_doors)

    if find_category(u"Walls") is None:
        info(u"Walls not in the model: wall checks skipped")
    else:
        guarded(u"Walls", run_walls)

    guarded(u"Text and number functions", run_strings)
    guarded(u"Project units", run_units)

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    out.print_md(u"---")
    out.print_md(u"**%d of %d checks passed**" % (passed, total))
    forms.alert(u"Phase 6 check: %d of %d passed. See the output window." % (passed, total),
                title=u"Abaco Phase 6 check", warn_icon=passed < total)


if __name__ == "__main__":
    if not doc or doc.IsFamilyDocument:
        forms.alert("Open a Revit project first.", exitscript=True)
    main()
