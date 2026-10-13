# -*- coding: utf-8 -*-
"""Phase 6 check (temporary dev button): custom (formula) fields on the real model.

Run in a TEST COPY of the project. Builds Doors and Walls tables with calculated fields and checks each
result against values read back from the same table's cells. Output is PASS / FAIL lines in the output
window. Drawing and Excel writing are optional (flags below).
Delete this button when Phase 6 is done.
"""
import os
import tempfile
import traceback

from pyrevit import forms, script, revit

from abaco import revit_reader as rr
from abaco import pipeline as P
from abaco import runner
from abaco import formula as F
from abaco import evaluate as E
from abaco import records as R

doc = revit.doc
out = script.get_output()

DRAW_REVIT = False      # True: also draws the Doors table as drafting views (test copy only)
WRITE_EXCEL = True      # True: writes a temp .xlsx and checks that it exists
EXCEL_PATH = os.path.join(tempfile.gettempdir(), "abaco_phase6_check.xlsx")

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
]


def expect_area(r):
    w, h = r.cells.get(R.K_WIDTH), r.cells.get(R.K_HEIGHT)
    if not (is_num(w) and is_num(h)):
        return u"#NONE"
    return float(w) * float(h)


def expect_ratio(r):
    w, h, c = r.cells.get(R.K_WIDTH), r.cells.get(R.K_HEIGHT), r.cells.get(R.K_COUNT)
    if not (is_num(w) and is_num(h)):
        return u"#NONE"             # NONE is returned before the division is tried
    if c == 1:
        return u"#ERROR"            # count - 1 = 0
    return float(w) * float(h) / (float(c) - 1)


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
          f1 is not None and f1.dim == "area" and f1.base_unit == u"m" + SQM,
          u"dim=%s" % (f1.dim if f1 is not None else None))
    heads = [c.heading for c in res.table.columns]
    check("Heading carries the formula unit", u"Door Area (m%s)" % SQM in heads, u" | ".join(heads))

    # --- row values, checked against the row's own width, height and count
    bad = [r for r in rows if not same(r.cells.get(u"calc:1"), expect_area(r))]
    check("Door Area = Width x Height on every row", not bad,
          u"%d of %d rows differ" % (len(bad), len(rows)))

    n_one = sum(1 for r in rows if r.cells.get(R.K_COUNT) == 1)
    if n_one:
        bad = [r for r in rows if not same(r.cells.get(u"calc:2"), expect_ratio(r))]
        check("Ratio: count 1 gives #ERROR, other rows divide by (count - 1)", not bad,
              u"%d rows with count 1" % n_one)
        check("Ratio: division-by-zero warning reported",
              any(u"div0" in w for w in res.warnings))
    else:
        info(u"no row with count 1 in Doors: division-by-zero check skipped")

    # --- circular references and unknown fields
    circ = [r for r in rows for k in (u"calc:3", u"calc:4") if r.cells.get(k) != u"#ERROR"]
    check("Circular references show #ERROR", not circ)
    check("Circular reference warning reported",
          any(u"circular" in w for w in res.warnings))

    check("Unknown field gives #ERROR", all(r.cells.get(u"calc:5") == u"#ERROR" for r in rows))
    check("Unknown field warning reported",
          any(u"cannot be calculated" in w and u"Bad Ref" in w for w in res.warnings))

    # --- grand total = sum of the rows (no double counting, markers left out)
    rs2, s2, res2 = build(u"Doors", DOOR_CUSTOMS[:1], tweak=tw_area_total)
    gts = kind_rows(res2, "gtotal")
    exp = sum(numbers(data_rows(res2), u"calc:1"))
    check("Grand total of Door Area equals the sum of its rows",
          len(gts) == 1 and approx(gts[0].cells.get(u"calc:1"), exp),
          u"got %s, expected %s" % (gts[0].cells.get(u"calc:1") if gts else None, exp))

    # --- row filter on a calculated field (runs after grouping)
    vals_all = numbers(rows, u"calc:1")
    if vals_all and min(vals_all) < max(vals_all) - EPS:
        thr = min(vals_all)

        def tw_filter(s):
            s["filter"] = {"match": "all", "conditions": [
                {"key": u"calc:1", "op": "gt", "value": u"%.9f" % thr}]}

        rs3, s3, res3 = build(u"Doors", DOOR_CUSTOMS[:1], tweak=tw_filter)
        kept = numbers(data_rows(res3), u"calc:1")
        ok = bool(kept) and len(kept) < len(vals_all) and all(v > thr + EPS for v in kept)
        check("Filter on a calculated field keeps only rows above the threshold", ok,
              u"kept %d of %d rows" % (len(kept), len(vals_all)))
    else:
        info(u"all Door Area values are equal: filter check skipped")

    # --- Excel and Revit output (optional)
    if WRITE_EXCEL:
        try:
            runner.write_excel(EXCEL_PATH, u"Phase6 doors", res)
            check("Excel: workbook written with the calculated column", os.path.exists(EXCEL_PATH), EXCEL_PATH)
        except Exception as ex:
            check("Excel: workbook written", False, u"%s" % ex)

    if DRAW_REVIT:
        try:
            with revit.Transaction(u"Phase6 check: draw doors"):
                lines = runner.draw_revit(doc, res, u"Phase6 check - Doors", u"P6", 2.5, 490, None)
            for ln in lines:
                info(ln)
            check("Revit: drafting views drawn", True)
        except Exception as ex:
            check("Revit: drafting views drawn", False, u"%s" % ex)


# --------------------------------------------------------- Walls: takeoff
WALL_CUSTOMS = [{"key": u"calc:1", "name": u"Layer x2", "formula": u"{@LAYER_THICKNESS} * 2"}]


def expect_layer(r):
    t = r.cells.get(R.K_LAYER_THICKNESS)
    return 2.0 * float(t) if is_num(t) else u"#NONE"


def tw_layer_total(s):
    field_setting(s, u"calc:1")["calc"] = "total"


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
        exp = sum(numbers(t.members or [], u"calc:1"))
        if not approx(t.cells.get(u"calc:1"), exp):
            bad_t.append(t)
    check("Footer totals add every layer row of their group", not bad_t,
          u"%d footer rows checked" % len(totals))


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


# ------------------------------------------------------- project units (info)
def run_units():
    out.print_md(u"## Project units (information)")
    cat = find_category(u"Doors")
    if cat is None:
        return
    rs = rr.read_category(doc, cat, _quiet)
    proj = getattr(rs, "project", None) or {}
    info(u"Project units in the record set: %s" % (proj if proj else u"none (reader fix pending)"))
    info(u"Area unit the pipeline uses by default: %s" % (P.project_default(rs, "area"),))


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