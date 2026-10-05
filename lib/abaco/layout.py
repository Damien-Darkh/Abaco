# -*- coding: utf-8 -*-
"""Table rows -> drawing geometry (lines + text) paginated into pages.

Pure Python (no Revit API), port of the first half of the Dynamo "Revit table" node (3436a1).
All coordinates are in mm, y measured downward from 0 on a page.
"""
import re

try:
    _STR = (basestring,)       # IronPython / Python 2
except NameError:
    _STR = (str,)              # Python 3

MM = 1.0 / 304.8               # mm -> feet


def _s(v):
    if isinstance(v, _STR):
        return v
    return u"%s" % v


def cell_text(v):
    if v is None:
        return u""
    if isinstance(v, bool):
        return u"%s" % v
    if isinstance(v, float):
        return format(v, ".15g")
    return _s(v).strip()


def norm(v):
    return re.sub(r"\s+", " ", _s(v)).strip().lower()


class Page(object):
    def __init__(self, lines, texts, height, nrows):
        self.lines = lines     # (x0, y0, x1, y1)
        self.texts = texts     # (kind, text, x, y, width_or_None)  kind: title | head | cell
        self.height = height
        self.nrows = nrows


class TableLayout(object):
    def __init__(self):
        self.pages = []
        self.table_w = 0.0
        self.row_h = 0.0
        self.n_cols = 0
        self.n_blocks = 0
        self.report = []


def build_layout(table_data, text_mm, page_h_mm, hidden_cols_text=""):
    out = TableLayout()
    hidden_cols = set(norm(x) for x in re.split(r"[;,]", _s(hidden_cols_text)) if x.strip())

    # rows as {column index: text}; empty cells are left out, an all-empty row is a blank spacer row
    rows = []
    for r in table_data:
        d = {}
        for i, v in enumerate(r):
            s = cell_text(v)
            if s != u"":
                d[i] = s
        rows.append(d)
    while rows and not rows[-1]:
        rows.pop()

    # columns hidden in the Revit table (still kept in Excel)
    hdr_map = None
    for r in rows:
        cand = dict((k, norm(v)) for k, v in r.items())
        if "type mark" in cand.values() or "typemark" in cand.values():
            hdr_map = cand
            break
    if hdr_map:
        hide_idx = set(k for k, v in hdr_map.items() if v in hidden_cols and v not in ("type mark", "typemark"))
        if hide_idx:
            rows = [dict((k, v) for k, v in r.items() if k not in hide_idx) for r in rows]
        hidden_found = sorted(set(v for k, v in hdr_map.items() if k in hide_idx))
        if hidden_found:
            out.report.append(u"Hidden in Revit: " + u", ".join(hidden_found))

    ncols = sorted(set(k for r in rows for k in r.keys()))
    if not ncols:
        raise ValueError("The table is empty")
    matrix = [[r.get(c, u"").strip() for c in ncols] for r in rows]

    # classify rows: title (before the header), header (has "Type Mark"), blank, data
    title_rows, header_row, blocks, cur = [], None, [], []
    for r in matrix:
        filled = [c for c in r if c != u""]
        if header_row is None:
            if any(norm(c) in ("type mark", "typemark") for c in r):
                header_row = r
            elif len(filled) >= 1:
                title_rows.append(r)
            continue
        if not filled:
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(r)
    if cur:
        blocks.append(cur)
    if header_row is None:
        raise ValueError("Header row with 'Type Mark' not found")

    # geometry in mm
    ROW_H = max(text_mm * 2.4, 5.0)
    PAD_X = text_mm * 0.8
    PAD_Y = (ROW_H - text_mm) / 2.0 - text_mm * 0.15
    CHAR_W = text_mm * 0.62
    GAP = ROW_H

    col_w = []
    for ci in range(len(ncols)):
        longest = len(header_row[ci])
        for b in blocks:
            for r in b:
                longest = max(longest, len(r[ci]))
        col_w.append(max(longest * CHAR_W + 2 * PAD_X, 12.0))
    TABLE_W = sum(col_w)
    col_x = [0.0]
    for w in col_w:
        col_x.append(col_x[-1] + w)

    title = u"  ".join(c for r in title_rows for c in r if c)

    def layout_page(page_blocks):
        lines, texts = [], []
        y = 0.0

        def hline(y_):
            lines.append((0.0, -y_, TABLE_W, -y_))

        def vlines(y0, y1):
            for x in col_x:
                lines.append((x, -y0, x, -y1))

        if title_rows:      # title merged across the whole table, centred
            hline(y)
            hline(y + ROW_H)
            lines.append((0.0, -y, 0.0, -(y + ROW_H)))
            lines.append((TABLE_W, -y, TABLE_W, -(y + ROW_H)))
            texts.append(("title", title, 0.0, -(y + PAD_Y), TABLE_W))
            y += ROW_H
        hline(y)
        hline(y + ROW_H)
        vlines(y, y + ROW_H)
        for ci, c in enumerate(header_row):
            if c:
                texts.append(("head", c, col_x[ci] + PAD_X, -(y + PAD_Y), None))
        y += ROW_H
        y += GAP
        for b in page_blocks:
            top = y
            hline(y)
            for r in b:
                for ci, c in enumerate(r):
                    if c:
                        texts.append(("cell", c, col_x[ci] + PAD_X, -(y + PAD_Y), None))
                y += ROW_H
                hline(y)
            vlines(top, y)
            y += GAP
        return lines, texts, y - GAP

    # paginate whole blocks (a type is never split across sheets; title + header repeat)
    head_h = (ROW_H if title_rows else 0) + ROW_H + GAP
    pages, cur_pg, cur_h = [], [], head_h
    for b in blocks:
        bh = len(b) * ROW_H
        if cur_pg and cur_h + bh > page_h_mm:
            pages.append(cur_pg)
            cur_pg, cur_h = [], head_h
        cur_pg.append(b)
        cur_h += bh + GAP
    if cur_pg:
        pages.append(cur_pg)
    if not pages:
        pages = [[]]

    for pg in pages:
        lines, texts, h = layout_page(pg)
        out.pages.append(Page(lines, texts, h, sum(len(b) for b in pg)))

    out.table_w, out.row_h, out.n_cols, out.n_blocks = TABLE_W, ROW_H, len(ncols), len(blocks)
    out.report.append(u"Table: %d columns, %d type blocks, %d sheet(s). Width %.0f mm "
                      u"(check it fits your title block)." % (len(ncols), len(blocks), len(pages), TABLE_W))
    return out
