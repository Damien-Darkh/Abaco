# -*- coding: utf-8 -*-
"""pipeline Table -> everything the Excel writer needs (Phase 3). Pure Python, testable without Excel.

Excel rows are 1-based: row 1 = title, row 2 = headings, then the blocks separated by one blank row.
Total / min / max rows get real formulas over their block (SUM / MIN / MAX); grand-total rows combine the
data ranges of every block, so the workbook stays live. 'Varies' and empty cells are text and are ignored
by the functions.
"""
from abaco.pipeline import CALC_ROW_KINDS, ROW_TOTAL, ROW_MIN, ROW_MAX, ROW_GTOTAL, ROW_GMIN, ROW_GMAX

_FUNC = {ROW_TOTAL: "SUM", ROW_MIN: "MIN", ROW_MAX: "MAX", ROW_GTOTAL: "SUM", ROW_GMIN: "MIN", ROW_GMAX: "MAX"}
_GRAND = (ROW_GTOTAL, ROW_GMIN, ROW_GMAX)
MAX_FORMULA_ARGS = 200            # Excel allows 255 arguments; beyond this the plain value is kept


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
        self.values = []          # list of rows (u'' for empty)
        self.formulas = {}        # (row, col) 1-based -> u"=SUM(E3:E5)"
        self.bold_rows = []       # Excel row numbers drawn bold (headings, total rows)
        self.header_row = 2
        self.ncols = 0
        self.aligns = []          # per column: left | center | right
        self.vertical = []        # per column: heading rotated 90 degrees
        self.numfmts = []         # per column NumberFormat ("0.00", ...) or "General"

    @property
    def nrows(self):
        return len(self.values)


def build_sheet(table):
    cols = table.columns
    n = len(cols)
    sh = Sheet()
    sh.ncols = n
    sh.aligns = [c.align for c in cols]
    sh.vertical = [c.orientation == "vertical" for c in cols]
    sh.numfmts = [(u"0." + u"0" * c.decimals if c.decimals else u"0") if c.decimals is not None else u"General"
                  for c in cols]

    sh.values.append([table.title] + [u""] * (n - 1))
    sh.values.append([c.heading for c in cols])
    sh.bold_rows.append(2)

    row = 3
    spans = []                                    # (first, last) Excel rows of the data rows of each block
    for bi, (block, rows) in enumerate(zip(table.blocks, table.rendered_blocks())):
        if bi:
            sh.values.append([u""] * n)
            row += 1
        first = last = None
        for r, (kind, line) in zip(block, rows):
            sh.values.append(line)
            if kind == "data":
                if first is None:
                    first = row
                last = row
            else:
                sh.bold_rows.append(row)
                for ci, c in enumerate(cols):
                    if r.cells.get(c.key) is None:
                        continue
                    letter = col_letter(ci + 1)
                    if kind in _GRAND:
                        if 0 < len(spans) <= MAX_FORMULA_ARGS:
                            args = u",".join(_rng(letter, a, b) for a, b in spans)
                            sh.formulas[(row, ci + 1)] = u"=%s(%s)" % (_FUNC[kind], args)
                    elif first is not None:
                        sh.formulas[(row, ci + 1)] = u"=%s(%s)" % (_FUNC[kind], _rng(letter, first, last))
            row += 1
        if first is not None:
            spans.append((first, last))
    return sh
