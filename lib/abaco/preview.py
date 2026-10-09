# -*- coding: utf-8 -*-
"""Preview rendering (Phase 4). Two layers:
  pure functions   excel_view(), canvas_primitives(), ruler_items()   no WPF, unit-tested
  WPF drawing      fill_grid(), draw_canvas()                         WPF imports happen inside the functions
The Revit preview is drawn from the SAME layout.build_layout output as the real drafting views.
"""
PX_PER_MM = 3.6
_PT_PER_MM = 2.835
PAGE_GAP_PX = 36.0
CAPTION_PX = 18.0


# ------------------------------------------------------------------------------------------- pure part
def cell_display(v, col):
    """Cell text as Excel will show it: floats use the column's decimals."""
    if v is None or v == u"":
        return u""
    if isinstance(v, bool):
        return u"%s" % v
    if isinstance(v, float):
        if col.decimals is not None:
            return u"%.*f" % (col.decimals, v)
        return format(v, ".15g")
    return u"%s" % v


def excel_view(table):
    """-> (headings, rows, kinds). rows hold display text; blocks are separated by a blank row.
    kinds: 'data' | 'total' | 'blank' (same length as rows)."""
    cols = table.columns
    n = len(cols)
    rows, kinds = [], []
    for block in table.rendered_blocks():
        for kind, line in block:
            rows.append([cell_display(v, c) for v, c in zip(line, cols)])
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
def _excel_cell(v, numfmt):
    """Cell text as Excel shows it: floats use the number format's decimals."""
    if v is None or v == u"":
        return u""
    if isinstance(v, bool):
        return u"%s" % v
    if isinstance(v, float):
        if numfmt and numfmt != u"General":
            dec = len(numfmt.split(u".")[1]) if u"." in numfmt else 0
            return u"%.*f" % (dec, v)
        return format(v, ".15g")
    return u"%s" % v


def _cell_style(grid, align, wrap, bold, italic, underline, fg, bg, cache):
    """One WPF style per distinct combination of cell properties (cached)."""
    key = (align, bool(wrap), bool(bold), bool(italic), bool(underline), fg, bg)
    if key in cache:
        return cache[key]
    import clr
    from System.Windows import Style, Setter, TextAlignment, HorizontalAlignment, TextWrapping
    from System.Windows import FontWeights, FontStyles, TextDecorations
    from System.Windows.Controls import TextBlock, Control, Border
    from System.Windows.Media import SolidColorBrush
    ta = {"left": TextAlignment.Left, "center": TextAlignment.Center, "right": TextAlignment.Right}[align]
    st = Style(clr.GetClrType(TextBlock))
    st.BasedOn = grid.FindResource("CellText")
    st.Setters.Add(Setter(TextBlock.TextAlignmentProperty, ta))
    st.Setters.Add(Setter(TextBlock.HorizontalAlignmentProperty, HorizontalAlignment.Stretch))
    st.Setters.Add(Setter(TextBlock.FontWeightProperty, FontWeights.Bold if bold else FontWeights.Normal))
    st.Setters.Add(Setter(TextBlock.FontStyleProperty, FontStyles.Italic if italic else FontStyles.Normal))
    if underline:
        st.Setters.Add(Setter(TextBlock.TextDecorationsProperty, TextDecorations.Underline))
    if wrap:
        st.Setters.Add(Setter(TextBlock.TextWrappingProperty, TextWrapping.Wrap))
    if fg:
        st.Setters.Add(Setter(TextBlock.ForegroundProperty, _brush_obj(fg)))
    cache[key] = st
    return st


def _brush_obj(hexcolor):
    from System.Windows.Media import SolidColorBrush, Color
    h = hexcolor.lstrip("#")
    return SolidColorBrush(Color.FromRgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))


def fill_grid(grid, sheet):
    """As-Excel preview of the sheet model, with the appearance styles per cell and per row.

    Underline and text colour are set per cell (WPF has no per-row underline). Row backgrounds are set
    per row (a DataGridRow background), so zebra striping and background colours appear.
    Returns one style dict per data row, in the same order as the grid rows.
    """
    from System.Collections.Generic import List
    from System.Windows.Controls import DataGridTextColumn, DataGridLength
    from System.Windows.Data import Binding
    from System.Windows.Media import FontFamily

    app = sheet.appearance
    wrap = bool(app["wrap"])
    zebra = app["zebra"]
    grid.ItemsSource = None
    grid.FontFamily = FontFamily(app["font"]["family"])
    grid.FontSize = app["font"]["sizeMm"] * _PT_PER_MM * 4.0 / 3.0       # pt -> WPF units
    grid.Columns.Clear()

    # per data row: the element's properties and the row background
    styles, row_style = [], []
    data_index = 0
    for r in range(3, sheet.nrows + 1):
        el = sheet.row_el[r - 1]
        if el is None:
            styles.append({"blank": True})
            row_style.append(None)
            continue
        e = app["elements"][el]
        bg = e["background"]
        if not bg and zebra["on"] and el == "data" and data_index % 2 == 1:
            bg = zebra["color"]
        if el == "data":
            data_index += 1
        st = {"blank": False, "bold": e["bold"], "italic": e["italic"], "underline": e["underline"],
              "fg": e["color"], "bg": bg}
        styles.append(st)
        row_style.append(st)

    cache = {}
    for i in range(sheet.ncols):
        col = DataGridTextColumn()
        col.Header = sheet.values[1][i]
        col.Binding = Binding("[%d]" % i)
        align = sheet.aligns[i] if sheet.aligns[i] in ("left", "center", "right") else "left"
        # the column style is the cell style of the data rows; per-row bold/italic/underline/colour
        # are applied to each cell in the row's own style below
        col.ElementStyle = _cell_style(grid, align, wrap, False, False, False, None, None, cache)
        col.Width = DataGridLength(sheet.widths[i] * PX_PER_MM) if sheet.widths[i] else DataGridLength.Auto
        grid.Columns.Add(col)

    items = List[object]()
    for r in range(3, sheet.nrows + 1):
        item = List[object]()
        for i, v in enumerate(sheet.values[r - 1]):
            item.Add(_excel_cell(v, sheet.numfmts[i]))
        items.Add(item)
    grid.ItemsSource = items

    # per-row styling: rows are created by the grid, so the style is applied on LoadingRow
    grid.Tag = (row_style,)
    return styles


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
