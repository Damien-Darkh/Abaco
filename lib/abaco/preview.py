# -*- coding: utf-8 -*-
"""Preview rendering (Phase 4). Two layers:
  pure functions   excel_view(), canvas_primitives(), ruler_items()   no WPF, unit-tested
  WPF drawing      fill_grid(), draw_canvas()                         WPF imports happen inside the functions
The Revit preview is drawn from the SAME layout.build_layout output as the real drafting views.
Every number is shown with layout.cell_display(), so the grid, the canvas and the Excel file agree.
"""
from abaco import measure as M
from abaco.layout import cell_display, count_lines   # noqa: F401  (count_lines kept for callers)

PX_PER_MM = 3.6
_PT_PER_MM = 2.835
PAGE_GAP_PX = 36.0
CAPTION_PX = 18.0


# ------------------------------------------------------------------------------------------- pure part
def excel_view(table):
    """-> (headings, rows, kinds). rows hold display text; blocks are separated by a blank row.
    kinds: 'data' | 'total' | 'blank' (same length as rows)."""
    cols = table.columns
    rows, kinds = [], []
    for block in table.rendered_blocks():
        for kind, line in block:
            rows.append([cell_display(v, c.decimals, c.prefix) for v, c in zip(line, cols)])
            kinds.append("blank" if kind == "blank" else ("data" if kind == "data" else "total"))
    return table.headings(), rows, kinds


def canvas_primitives(layout, scale=PX_PER_MM):
    """Layout pages stacked top to bottom -> (lines, texts, captions, width_px, height_px).
    lines  (x0, y0, x1, y1) px        texts  (kind, text, x, y, width_or_None, align, rotation) px
    captions (text, x, y) px; only when there is more than one page."""
    lines, texts, captions = [], [], []
    multi = len(layout.pages) > 1
    off = 0.0
    for pi, page in enumerate(layout.pages):
        if multi:
            captions.append((u"Sheet %d of %d" % (pi + 1, len(layout.pages)), 0.0, off))
            off += CAPTION_PX
        for (x0, y0, x1, y1) in page.lines:
            lines.append((x0 * scale, off - y0 * scale, x1 * scale, off - y1 * scale))
        for kind, txt, x, y, w, align, rot in page.texts:
            texts.append((kind, txt, x * scale, off - y * scale, None if w is None else w * scale, align, rot))
        off += page.height * scale + PAGE_GAP_PX
    return lines, texts, captions, layout.table_w * scale, max(off - PAGE_GAP_PX, 1.0)


def ruler_items(layout, scale=PX_PER_MM):
    """[(text, width_px)] one per column, e.g. ('18 mm', 64.8)."""
    return [(u"%.0f mm" % w, w * scale) for w in layout.col_w]


# ------------------------------------------------------------------------------------------ WPF part
def _sheet_text(sheet, r, ci):
    """Text of one sheet cell as Excel shows it (same decimals and currency prefix as the number format)."""
    return cell_display(sheet.values[r - 1][ci], sheet.decimals[ci], sheet.prefixes[ci])


def _w(on):
    return 1.0 if on else 0.0


def _auto_mm(sheet, ci):
    """Width of an auto column: the widest text in it, measured with each row's font."""
    app = sheet.appearance
    em = app["font"]["sizeMm"]
    fam = app["font"]["family"]
    best = 0.0
    for r in range(2, sheet.nrows + 1):
        el = sheet.row_el[r - 1]
        if el is None or r in sheet.merged_rows:
            continue
        if r == 2 and sheet.vertical[ci]:
            continue                              # a vertical heading does not widen the column
        e = app["elements"][el]
        text = _sheet_text(sheet, r, ci)
        best = max(best, M.width_mm(text, fam, em, e["bold"], e["italic"]) * 1.06)
    return max(best + 2 * 0.8 * em, 12.0)


def fill_grid(host, sheet):
    """Build the As Excel preview. If building fails, the reason is shown in the grid instead of
    leaving it empty."""
    from System.Windows import Thickness, TextWrapping
    from System.Windows.Controls import TextBlock
    try:
        _build_grid(host, sheet)
    except Exception as ex:
        host.Children.Clear()
        host.RowDefinitions.Clear()
        host.ColumnDefinitions.Clear()
        msg = TextBlock()
        msg.Text = u"As Excel preview could not be drawn: %s" % ex
        msg.TextWrapping = TextWrapping.Wrap
        msg.Margin = Thickness(8)
        msg.Foreground = _brush("#8A4B08")
        host.Children.Add(msg)


def _build_grid(host, sheet):
    """As-Excel preview: a Grid of styled cells built from the sheet model. Each cell carries its own
    font, bold, italic, underline, colours, background, wrapping, alignment and lines, so every appearance
    setting shows the same way it is written to Excel. Merged rows span the whole table."""
    from System.Windows import GridLength, Thickness, TextWrapping, FontWeights, FontStyles, TextDecorations
    from System.Windows import TextAlignment, HorizontalAlignment, VerticalAlignment
    from System.Windows.Controls import Grid, Border, TextBlock, ColumnDefinition, RowDefinition
    from System.Windows.Media import FontFamily, RotateTransform

    app = sheet.appearance
    n = sheet.ncols
    fam = app["font"]["family"]
    px = app["font"]["sizeMm"] * _PT_PER_MM * 4.0 / 3.0       # pt -> WPF pixels
    lc = app["lines"]
    zebra = app["zebra"]
    wrap = bool(app["wrap"])
    ta = {"left": TextAlignment.Left, "center": TextAlignment.Center, "right": TextAlignment.Right}

    host.Children.Clear()
    host.RowDefinitions.Clear()
    host.ColumnDefinitions.Clear()
    for ci in range(n):
        cd = ColumnDefinition()
        mm = sheet.widths[ci] or _auto_mm(sheet, ci)
        cd.Width = GridLength(mm * PX_PER_MM)
        host.ColumnDefinitions.Add(cd)

    for r in range(1, sheet.nrows + 1):
        el = sheet.row_el[r - 1]
        rd = RowDefinition()
        if el is None:
            rd.Height = GridLength(app["blankMm"] * PX_PER_MM)
        else:
            rd.Height = GridLength.Auto
        host.RowDefinitions.Add(rd)
        if el is None:
            continue

        e = app["elements"][el]
        bg = e["background"]
        if not bg and zebra["on"] and r in sheet.zebra_rows:
            bg = zebra["color"]
        spans = r in sheet.merged_rows

        for ci in ([0] if spans else range(n)):
            if spans:
                text = sheet.values[r - 1][0]
                align = "center" if el == "title" else e.get("align", "left")
            else:
                text = _sheet_text(sheet, r, ci)
                align = sheet.aligns[ci] if el == "data" else e.get("align", "left")

            tb = TextBlock()
            tb.Text = u"%s" % text
            tb.FontFamily = FontFamily(fam)
            tb.FontSize = px
            tb.FontWeight = FontWeights.Bold if e["bold"] else FontWeights.Normal
            tb.FontStyle = FontStyles.Italic if e["italic"] else FontStyles.Normal
            if e["underline"]:
                tb.TextDecorations = TextDecorations.Underline
            tb.Foreground = _brush(e["color"])
            tb.TextAlignment = ta.get(align, TextAlignment.Left)
            tb.TextWrapping = TextWrapping.Wrap if wrap else TextWrapping.NoWrap
            tb.HorizontalAlignment = HorizontalAlignment.Stretch
            tb.VerticalAlignment = VerticalAlignment.Center
            tb.Margin = Thickness(3, 1, 3, 1)
            if el == "heading" and sheet.vertical[ci] and not spans:
                tb.LayoutTransform = RotateTransform(-90)
                tb.TextWrapping = TextWrapping.NoWrap

            border = Border()
            if bg:
                border.Background = _brush(bg)
            if e["lines"]:
                last = spans or ci == n - 1
                border.BorderBrush = _brush(lc["color"])
                border.BorderThickness = Thickness(
                    _w(lc["outer"] if ci == 0 else lc["inner"]),
                    _w(lc["outer"] if r == 1 else lc["inner"]),
                    _w(lc["outer"] if last else lc["inner"]),
                    _w(lc["outer"] if r == sheet.nrows else lc["inner"]))
            border.Child = tb

            Grid.SetRow(border, r - 1)
            Grid.SetColumn(border, ci)
            if spans:
                Grid.SetColumnSpan(border, n)
            host.Children.Add(border)


def _brush(hexcolor):
    from System.Windows.Media import SolidColorBrush, Color
    h = (hexcolor or "#000000").lstrip("#")
    return SolidColorBrush(Color.FromRgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))


def _band_fills(canvas, layout, scale):
    """Row backgrounds (background colour and zebra) behind the lines and text."""
    from System.Windows.Controls import Canvas
    from System.Windows.Shapes import Rectangle
    multi = len(layout.pages) > 1
    off = 0.0
    for page in layout.pages:
        if multi:
            off += CAPTION_PX
        for (x0, y0, x1, y1, color) in page.bands:
            if not color:
                continue
            rect = Rectangle()
            rect.Width = (x1 - x0) * scale
            rect.Height = (y1 - y0) * scale
            rect.Fill = _brush(color)
            Canvas.SetLeft(rect, x0 * scale)
            Canvas.SetTop(rect, off + y0 * scale)
            canvas.Children.Add(rect)
        off += page.height * scale + PAGE_GAP_PX


def draw_canvas(canvas, ruler, layout, scale=PX_PER_MM):
    """As-Revit preview: lines and text with the appearance styles, plus the per-column width ruler."""
    from System.Windows import FontWeights, FontStyles, TextAlignment, TextWrapping, TextDecorations
    from System.Windows.Controls import Canvas, TextBlock
    from System.Windows.Media import Brushes, RotateTransform, FontFamily
    from System.Windows.Shapes import Line

    app = layout.appearance
    els = app["elements"]
    lines, texts, captions, width, height = canvas_primitives(layout, scale)
    canvas.Children.Clear()
    canvas.Width, canvas.Height = width, height
    _band_fills(canvas, layout, scale)
    line_brush = _brush(app["lines"]["color"])
    for (x0, y0, x1, y1) in lines:
        ln = Line()
        ln.X1, ln.Y1, ln.X2, ln.Y2 = x0, y0, x1, y1
        ln.Stroke = line_brush
        ln.StrokeThickness = 0.8
        canvas.Children.Add(ln)
    ta = {"left": TextAlignment.Left, "center": TextAlignment.Center, "right": TextAlignment.Right}
    family = FontFamily(app["font"]["family"])
    size = layout_font_px(layout, scale)
    for kind, txt, x, y, w, align, rot in texts:
        st = els.get(kind, {})
        tb = TextBlock()
        tb.Text = u"%s" % txt.replace(u"\r", u"\n")
        tb.TextWrapping = TextWrapping.NoWrap
        tb.FontFamily = family
        tb.FontSize = size
        tb.FontWeight = FontWeights.Bold if st.get("bold") else FontWeights.Normal
        tb.FontStyle = FontStyles.Italic if st.get("italic") else FontStyles.Normal
        if st.get("underline"):
            tb.TextDecorations = TextDecorations.Underline
        tb.Foreground = Brushes.Black
        if w is not None:
            tb.Width = max(w, 1.0)
            tb.TextAlignment = ta.get(align, TextAlignment.Left)
        if rot:
            tb.RenderTransform = RotateTransform(-rot)
        Canvas.SetLeft(tb, x)
        Canvas.SetTop(tb, y)
        canvas.Children.Add(tb)
    for txt, x, y in captions:
        tb = TextBlock()
        tb.Text = txt
        tb.FontSize = 10
        tb.Foreground = Brushes.Gray
        Canvas.SetLeft(tb, x)
        Canvas.SetTop(tb, y)
        canvas.Children.Add(tb)

    ruler.Children.Clear()
    for txt, w in ruler_items(layout, scale):
        tb = TextBlock()
        tb.Text = txt
        tb.Width = w
        tb.FontSize = 9
        tb.Foreground = Brushes.Gray
        tb.TextAlignment = TextAlignment.Center
        ruler.Children.Add(tb)


def layout_font_px(layout, scale):
    """Text height in px: the layout's row height is 2.4 x text height (5 mm minimum)."""
    return max(layout.row_h / 2.4, 2.0) * scale * 1.1