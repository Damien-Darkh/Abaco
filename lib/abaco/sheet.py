# -*- coding: utf-8 -*-
"""pipeline Table -> sheet model for the Excel writer. Pure Python, testable without Excel.

Excel rows are 1-based: row 1 title, row 2 headings, then the table rows.
Numbers stay numbers. The display is the number format from units.excel_format(), so Excel shows
exactly what the Revit drawing and the preview show (units.format_text), and formulas keep working.
Footers and summary rows get SUBTOTAL formulas, only where they give the same answer as the Python value.
"""
from abaco import appearance as AP
from abaco import units as U
from abaco.pipeline import (ROW_DATA, ROW_BLANK, ROW_HEADER, ROW_SUMHEAD, ROW_TOTAL, ROW_MIN, ROW_MAX,
                            ROW_GTOTAL, ROW_GMIN, ROW_GMAX)

_FUNC = {ROW_TOTAL: 9, ROW_MIN: 5, ROW_MAX: 4, ROW_GTOTAL: 9, ROW_GMIN: 5, ROW_GMAX: 4}   # SUBTOTAL codes
_GRAND = (ROW_GTOTAL, ROW_GMIN, ROW_GMAX)
_ELEMENT = {ROW_DATA: "data", ROW_HEADER: "header", ROW_SUMHEAD: "summaryHeader"}
MAX_FORMULA_ARGS = 200


def col_letter(n):
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def _rng(letter, first, last):
    if first == last:
        return u"%s%d" % (letter, first)
    return u"%s%d:%s%d" % (letter, first, letter, last)


class Sheet(object):
    def __init__(self):
        self.values = []
        self.formulas = {}          # (row, col) 1-based -> "=SUBTOTAL(9,E3:E5)"
        self.appearance = None
        self.ncols = 0
        self.aligns = []
        self.vertical = []
        self.decimals = []          # per column: decimal places, or None (General)
        self.prefixes = []          # per column: currency symbol, or u""
        self.numfmts = []           # per column: Excel number format (units.excel_format)
        self.widths = []            # fixed column width in mm, or None
        self.row_el = []            # per Excel row: appearance element name, None for blank rows
        self.merged_rows = []       # rows whose text runs across the table
        self.zebra_rows = []        # data rows that take the zebra colour

    @property
    def nrows(self):
        return len(self.values)


def _is_text(v):
    return not isinstance(v, (int, float)) and v not in (None, u"")


def _formula_ok(sh, c, ci, member_rows, expanded):
    if expanded and c.field is not None and c.field.scope != "layer":
        return False                # one element on several layer rows would be counted twice
    for mr in member_rows:
        if _is_text(sh.values[mr - 1][ci]):
            return False            # 'Varies' or 'min - max' text: SUBTOTAL would ignore it
    return True


def build_sheet(table):
    cols = table.columns
    n = len(cols)
    app = table.appearance
    sh = Sheet()
    sh.appearance = app
    sh.ncols = n
    sh.aligns = [c.align for c in cols]
    vert = app["elements"]["heading"].get("orientation") == "vertical"
    sh.vertical = [vert] * n
    sh.widths = [c.width_mm for c in cols]
    sh.decimals = [c.decimals for c in cols]
    sh.prefixes = [c.prefix or u"" for c in cols]
    sh.numfmts = [U.excel_format(c.decimals, c.prefix) for c in cols]

    title = AP.apply_case(table.title, AP.case_of(app, "title"))
    sh.values.append([title] + [u""] * (n - 1))
    sh.values.append(table.headings())
    sh.row_el = ["title", "heading"]
    sh.merged_rows = [1]

    rowno = {}
    block_spans = []
    row = 3
    data_count = 0
    expanded = False
    for block, lines in zip(table.blocks, table.rendered_blocks()):
        data_rows = []
        for r, (kind, line) in zip(block, lines):
            sh.values.append(line)
            rowno[id(r)] = row
            if kind == "blank":
                sh.row_el.append(None)
            else:
                sh.row_el.append(_ELEMENT.get(kind, "summary"))
            if kind in ("header", "sumhead"):
                sh.merged_rows.append(row)
            if kind == ROW_DATA:
                data_rows.append(row)
                if r.lorder:
                    expanded = True
                if data_count % 2 == 1:
                    sh.zebra_rows.append(row)
                data_count += 1
            row += 1
        if data_rows:
            block_spans.append((data_rows[0], data_rows[-1]))

    for block in table.blocks:
        for r in block:
            if r.kind not in _FUNC or id(r) not in rowno:
                continue
            members = sorted(rowno[id(m)] for m in r.members if id(m) in rowno)
            if not members:
                continue
            spans = block_spans if r.kind in _GRAND else [(members[0], members[-1])]
            if not spans or len(spans) > MAX_FORMULA_ARGS:
                continue
            for ci, c in enumerate(cols):
                if r.cells.get(c.key) is None or not _formula_ok(sh, c, ci, members, expanded):
                    continue
                letter = col_letter(ci + 1)
                refs = u",".join(_rng(letter, a, b) for a, b in spans)
                sh.formulas[(rowno[id(r)], ci + 1)] = u"=SUBTOTAL(%d,%s)" % (_FUNC[r.kind], refs)
    return sh