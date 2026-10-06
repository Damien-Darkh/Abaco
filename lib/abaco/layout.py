# -*- coding: utf-8 -*-
"""pipeline Table -> drawing geometry (lines + text) paginated into pages (Phase 3).

Pure Python (no Revit API). All coordinates are in mm, y measured downward from 0 on a page
(text/line y values are stored negated, as Revit's y axis points up).

Text tuples: (kind, text, x, y, width_or_None, align, rotation_deg)
  kind   title | head | cell | total      (title, head and total are drawn bold)
  align  left | center | right           (non-left text gets an explicit width = column width - padding)
  rotation 0 or 90 (vertical headings; no width)
The Revit preview (Phase 4) draws these same tuples, so preview and drawing cannot drift apart.
"""

try:
    _STR = (basestring,)       # IronPython / Python 2
except NameError:
    _STR = (str,)              # Python 3

MM = 1.0 / 304.8               # mm -> feet
CHAR_W_FACTOR = 0.62           # estimated character width = text height x this (raise it if text wraps)
MIN_COL_W = 12.0


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


class Page(object):
    def __init__(self, lines, texts, height, nrows):
        self.lines = lines     # (x0, y0, x1, y1)
        self.texts = texts     # see module docstring
        self.height = height
        self.nrows = nrows


class TableLayout(object):
    def __init__(self):
        self.pages = []
        self.table_w = 0.0
        self.row_h = 0.0
        self.header_h = 0.0
        self.n_cols = 0
        self.n_blocks = 0
        self.col_x = []        # left edge of every column (+ the right edge of the last one)
        self.col_w = []
        self.report = []


def build_layout(table, text_mm, page_h_mm):
    """table: pipeline.Table (already reduced to the Revit columns). Returns TableLayout."""
    out = TableLayout()
    cols = table.columns
    if not cols:
        raise ValueError("The table has no columns")
    n = len(cols)

    blocks = []
    for rows in table.rendered_blocks():
        b = [(kind, [cell_text(c) for c in line]) for kind, line in rows]
        if b:
            blocks.append(b)
    heads = [cell_text(c.heading) for c in cols]
    vertical = [c.orientation == "vertical" for c in cols]
    title = cell_text(table.title)

    # geometry in mm
    ROW_H = max(text_mm * 2.4, 5.0)
    PAD_X = text_mm * 0.8
    PAD_Y = (ROW_H - text_mm) / 2.0 - text_mm * 0.15
    CHAR_W = text_mm * CHAR_W_FACTOR
    GAP = ROW_H

    col_w = []
    for ci, c in enumerate(cols):
        if c.width_mm:
            col_w.append(float(c.width_mm))
            continue
        longest = 0 if vertical[ci] else len(heads[ci])      # a vertical heading does not widen the column
        for b in blocks:
            for kind, r in b:
                longest = max(longest, len(r[ci]))
        col_w.append(max(longest * CHAR_W + 2 * PAD_X, MIN_COL_W))
    TABLE_W = sum(col_w)
    col_x = [0.0]
    for w in col_w:
        col_x.append(col_x[-1] + w)

    HEAD_H = ROW_H                                           # vertical headings need a taller header row
    for ci in range(n):
        if vertical[ci]:
            HEAD_H = max(HEAD_H, len(heads[ci]) * CHAR_W + 2 * PAD_X)

    def text_item(kind, txt, ci, y_top, align):
        """One horizontal text in column ci whose cell top is at y_top."""
        if align == "left":
            return (kind, txt, col_x[ci] + PAD_X, -(y_top + PAD_Y), None, "left", 0)
        return (kind, txt, col_x[ci] + PAD_X, -(y_top + PAD_Y), max(col_w[ci] - 2 * PAD_X, 1.0), align, 0)

    def layout_page(page_blocks):
        lines, texts = [], []
        y = 0.0

        def hline(y_):
            lines.append((0.0, -y_, TABLE_W, -y_))

        def vlines(y0, y1):
            for x in col_x:
                lines.append((x, -y0, x, -y1))

        if title:           # title merged across the whole table, centred
            hline(y)
            hline(y + ROW_H)
            lines.append((0.0, -y, 0.0, -(y + ROW_H)))
            lines.append((TABLE_W, -y, TABLE_W, -(y + ROW_H)))
            texts.append(("title", title, 0.0, -(y + PAD_Y), TABLE_W, "center", 0))
            y += ROW_H
        hline(y)
        hline(y + HEAD_H)
        vlines(y, y + HEAD_H)
        for ci, h in enumerate(heads):
            if not h:
                continue
            if vertical[ci]:      # rotated 90 deg: reads bottom to top, anchored at the bottom of the cell
                texts.append(("head", h, col_x[ci] + (col_w[ci] - text_mm) / 2.0,
                              -(y + HEAD_H - PAD_X), None, "left", 90))
            else:
                texts.append(text_item("head", h, ci, y, cols[ci].align))
        y += HEAD_H
        y += GAP
        for b in page_blocks:
            top = y
            hline(y)
            for kind, r in b:
                tkind = "cell" if kind == "data" else "total"     # total / min / max rows are bold
                for ci, c in enumerate(r):
                    if c:
                        texts.append(text_item(tkind, c, ci, y, cols[ci].align))
                y += ROW_H
                hline(y)
            vlines(top, y)
            y += GAP
        return lines, texts, y - GAP

    # paginate whole blocks (a type is never split across sheets; title + header repeat;
    # total rows are part of their block, so they stay with it)
    head_h = (ROW_H if title else 0) + HEAD_H + GAP
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

    out.table_w, out.row_h, out.header_h, out.n_cols, out.n_blocks = TABLE_W, ROW_H, HEAD_H, n, len(blocks)
    out.col_x, out.col_w = col_x, col_w
    out.report.append(u"Table: %d columns, %d blocks, %d sheet(s). Width %.0f mm "
                      u"(check it fits your title block)." % (n, len(blocks), len(pages), TABLE_W))
    return out
