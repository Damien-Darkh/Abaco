# -*- coding: utf-8 -*-
"""pipeline Table -> drawing geometry, paginated. Pure Python, no Revit API.

mm; y measured downward from the top of a page and stored negated (Revit's y points up).
Text tuples: (element, text, x, y, width_or_None, align, rotation_deg)
  text     line breaks are \\r (already wrapped here: Revit never wraps on its own)
  width    the column's text box, used for alignment and the preview; drawn without a Revit width
Line tuples: (x0, y0, x1, y1). Only the line types switched on in the appearance are emitted.
Band tuples: (x0, y0, x1, y1, colour_or_None). Row backgrounds (element background or zebra).

Number text: cell_display() is the one place a number becomes text for Revit and the preview. It uses
units.format_text with the column's decimals and currency prefix, so it shows what Excel shows.
Alignment: data rows use the field's alignment (Formatting); title, heading, header, summary header
and summary rows use the element's alignment (Appearance). Heading orientation comes from Appearance.
"""
from abaco import appearance as AP
from abaco import measure as M
from abaco import units as U

try:
    _NUMBER = (int, long, float)
except NameError:
    _NUMBER = (int, float)

MM = 1.0 / 304.8
LINE_PITCH = 1.6        # distance between wrapped lines, x text height. Compare with Revit's Line Spacing
PAD_TOP = 0.45          # space above and below the text, x text height
PAD_SIDE = 0.8          # space left and right of the text, x text height
SAFETY = 1.06           # measured widths are over-estimated slightly, so wrapping is never too little
MIN_COL_W = 12.0
SPAN_KINDS = ("header", "sumhead", "blank")      # full-row text, not used to size columns


def _el_of(kind):
    if kind == "data":
        return "data"
    if kind == "header":
        return "header"
    if kind == "sumhead":
        return "summaryHeader"
    if kind == "blank":
        return None
    return "summary"


class Page(object):
    def __init__(self, lines, texts, height, nrows, bands):
        self.lines = lines
        self.texts = texts
        self.height = height
        self.nrows = nrows
        self.bands = bands


class TableLayout(object):
    def __init__(self):
        self.pages = []
        self.table_w = 0.0
        self.row_h = 0.0
        self.header_h = 0.0
        self.n_cols = 0
        self.n_blocks = 0
        self.col_x = []
        self.col_w = []
        self.appearance = None
        self.report = []


def cell_text(v):
    """Text of a value that is not a number (or a number without decimals, as Excel's General shows it)."""
    if v is None:
        return u""
    if isinstance(v, bool):
        return u"%s" % v
    if isinstance(v, float):
        return format(v, ".15g")
    return (u"%s" % v).strip()


def cell_display(v, decimals, prefix=u""):
    """Text for one cell, the same as Excel displays it. Numbers go through units.format_text with the
    column's decimals and currency prefix. decimals None (General) keeps the value as it is."""
    if v is None or v == u"":
        return u""
    if isinstance(v, bool) or not isinstance(v, _NUMBER):
        return cell_text(v)
    if decimals is None:
        return cell_text(v)
    return U.format_text(v, decimals, prefix)


def count_lines(text, cpl):
    """Character-based line count, kept for the Excel row heights (excel_writer.py)."""
    if not text:
        return 1
    n, cur = 1, 0
    for word in text.split(u" "):
        L = len(word)
        if cur == 0:
            cur = L
        elif cur + 1 + L <= cpl:
            cur += 1 + L
        else:
            n += 1
            cur = L
        while cur > cpl:
            n += 1
            cur -= cpl
    return n


def build_layout(table, text_mm, page_h_mm, appearance=None):
    app = appearance or table.appearance
    els = app["elements"]
    wrap = bool(app["wrap"])
    lc = app["lines"]
    zebra = app["zebra"]
    family = app["font"]["family"]
    cols = table.columns
    if not cols:
        raise ValueError("The table has no columns")
    n = len(cols)
    t = float(text_mm)
    PITCH = t * LINE_PITCH
    PAD_T = t * PAD_TOP
    PAD_S = t * PAD_SIDE
    BLANK_H = float(app["blankMm"])

    title = AP.apply_case(cell_text(table.title), AP.case_of(app, "title"))
    heads = [cell_text(h) for h in table.headings()]
    vertical_heads = els["heading"].get("orientation") == "vertical"
    # every number becomes its shown text here, once, so widths and wrapping measure what is drawn
    blocks = [[(kind, [cell_display(v, c.decimals, c.prefix) for v, c in zip(line, cols)])
               for kind, line in rows] for rows in table.rendered_blocks()]

    def tw(text, el):
        """Measured width of a text in mm for the element's style, with the safety margin."""
        e = els[el]
        return M.width_mm(text, family, t, e["bold"], e["italic"]) * SAFETY

    def cell_parts(text, width, el):
        """The text as a list of lines that fit `width` (one line when wrap is off)."""
        if not wrap or not text:
            return [text]
        e = els[el]
        return M.wrap_lines(text, width - 2 * PAD_S, family, t, e["bold"], e["italic"], SAFETY)

    def row_h(nl):
        return nl * PITCH + 2 * PAD_T

    # column widths: fixed (Formatting tab) or fitted to the widest text, heading included
    widths = []
    for ci, c in enumerate(cols):
        if c.width_mm:
            widths.append(max(float(c.width_mm), 2 * PAD_S + 1.0))
            continue
        natural = 0.0 if vertical_heads else tw(heads[ci], "heading")
        for b in blocks:
            for kind, line in b:
                if kind not in SPAN_KINDS:
                    natural = max(natural, tw(line[ci], _el_of(kind)))
        widths.append(max(natural + 2 * PAD_S, MIN_COL_W))

    col_x = [0.0]
    for w in widths:
        col_x.append(col_x[-1] + w)
    TABLE_W = col_x[-1]

    title_parts = cell_parts(title, TABLE_W, "title") if title else [u""]
    TITLE_H = row_h(len(title_parts))

    head_parts = [[h] if vertical_heads else cell_parts(h, widths[ci], "heading")
                  for ci, h in enumerate(heads)]
    HEAD_H = row_h(max([len(p) for p in head_parts] + [1]))
    if vertical_heads and heads:
        HEAD_H = max(HEAD_H, max(tw(h, "heading") for h in heads) + 2 * PAD_S)

    # rows: (kind, line, parts per column, height, zebra index)
    rblocks, data_index = [], 0
    for b in blocks:
        out = []
        for kind, line in b:
            if kind == "blank":
                out.append((kind, line, None, BLANK_H, None))
                continue
            el = _el_of(kind)
            if kind in SPAN_KINDS:
                parts = [[line[0]]]
            else:
                parts = [cell_parts(line[ci], widths[ci], el) for ci in range(n)]
            nl = max([len(p) for p in parts] + [1])
            idx = data_index if kind == "data" else None
            if kind == "data":
                data_index += 1
            out.append((kind, line, parts, row_h(nl), idx))
        rblocks.append(out)

    # pagination: whole blocks only; title and heading repeat on every page
    head_top = (TITLE_H if title else 0.0) + HEAD_H
    pages, cur, cur_h = [], [], head_top
    for b in rblocks:
        bh = sum(r[3] for r in b)
        if cur and cur_h + bh > page_h_mm:
            pages.append(cur)
            cur, cur_h = [], head_top
        cur.append(b)
        cur_h += bh
    if cur or not pages:
        pages.append(cur)

    show_outer, show_inner = lc["outer"], lc["inner"]

    def draw_page(pg):
        lines, texts, bands = [], [], []
        y = 0.0

        def hline(y0, outer):
            if (outer and show_outer) or (not outer and show_inner):
                lines.append((0.0, -y0, TABLE_W, -y0))

        def vline(x, y0, y1, outer):
            if y1 - y0 > 1e-9 and ((outer and show_outer) or (not outer and show_inner)):
                lines.append((x, -y0, x, -y1))

        def boxed(y0, h, top_outer, bottom_outer):
            hline(y0, top_outer)
            hline(y0 + h, bottom_outer)
            for ci in range(n + 1):
                vline(col_x[ci], y0, y0 + h, ci == 0 or ci == n)

        def put(el, txt, ci, y0, align):
            x = col_x[ci] + PAD_S
            width = widths[ci] - 2 * PAD_S
            texts.append((el, txt, x, -(y0 + PAD_T), width, align, 0))

        def span_text(el, txt, y0):
            """Full-row text (title, group header, summary header): aligned across the table width."""
            align = els[el].get("align", "left")
            if align == "left":
                texts.append((el, txt, PAD_S, -(y0 + PAD_T), None, "left", 0))
            else:
                texts.append((el, txt, 0.0, -(y0 + PAD_T), TABLE_W, align, 0))

        if title:
            if els["title"]["lines"]:
                hline(y, True)
                hline(y + TITLE_H, False)
                vline(0.0, y, y + TITLE_H, True)
                vline(TABLE_W, y, y + TITLE_H, True)
            span_text("title", u"\r".join(title_parts), y)
            bands.append((0.0, y, TABLE_W, y + TITLE_H, els["title"]["background"]))
            y += TITLE_H

        if els["heading"]["lines"]:
            boxed(y, HEAD_H, not title, False)
        halign = els["heading"].get("align", "left")
        for ci, h in enumerate(heads):
            if not h:
                continue
            if vertical_heads:
                texts.append(("heading", h, col_x[ci] + (widths[ci] - t) / 2.0,
                              -(y + HEAD_H - PAD_S), None, "left", 90))
            else:
                put("heading", u"\r".join(head_parts[ci]), ci, y, halign)
        bands.append((0.0, y, TABLE_W, y + HEAD_H, els["heading"]["background"]))
        y += HEAD_H

        for b in pg:
            for ri, (kind, line, parts, h, idx) in enumerate(b):
                if kind == "blank":
                    y += h
                    continue
                el = _el_of(kind)
                last_on_page = (b is pg[-1]) and ri == len(b) - 1
                fill = els[el]["background"]
                if not fill and zebra["on"] and idx is not None and idx % 2 == 1:
                    fill = zebra["color"]
                bands.append((0.0, y, TABLE_W, y + h, fill))
                if kind in SPAN_KINDS:
                    if els[el]["lines"]:
                        hline(y, False)
                        hline(y + h, False)
                        vline(0.0, y, y + h, True)
                        vline(TABLE_W, y, y + h, True)
                    span_text(el, line[0], y)
                else:
                    if els[el]["lines"]:
                        boxed(y, h, False, last_on_page)
                    for ci, txt in enumerate(line):
                        if txt:
                            align = cols[ci].align if el == "data" else els[el].get("align", "left")
                            put(el, u"\r".join(parts[ci]), ci, y, align)
                y += h
        return lines, texts, y, bands

    out = TableLayout()
    for pg in pages:
        lines, texts, h, bands = draw_page(pg)
        out.pages.append(Page(lines, texts, h, sum(len(b) for b in pg), bands))
    out.table_w, out.row_h, out.header_h = TABLE_W, row_h(1), HEAD_H
    out.n_cols, out.n_blocks = n, len(blocks)
    out.col_x, out.col_w = col_x, widths
    out.appearance = app
    out.report.append(u"Table: %d columns, %d blocks, %d sheet(s). Width %.0f mm "
                      u"(check it fits your title block)." % (n, len(blocks), len(pages), TABLE_W))
    return out