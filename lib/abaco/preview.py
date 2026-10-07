# -*- coding: utf-8 -*-
"""Preview rendering (Phase 4). Two layers:
  pure functions   excel_view(), canvas_primitives(), ruler_items()   no WPF, unit-tested
  WPF drawing      fill_grid(), draw_canvas()                         WPF imports happen inside the functions
The Revit preview is drawn from the SAME layout.build_layout output as the real drafting views.
"""
PX_PER_MM = 3.6
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
    for bi, block in enumerate(table.rendered_blocks()):
        if bi:
            rows.append([u""] * n)
            kinds.append("blank")
        for kind, line in block:
            rows.append([cell_display(v, c) for v, c in zip(line, cols)])
            kinds.append("data" if kind == "data" else "total")
    return [c.heading for c in cols], rows, kinds


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
def _align_style(grid, align, cache):
    if align in cache:
        return cache[align]
    import clr
    from System.Windows import Style, Setter, TextAlignment, HorizontalAlignment
    from System.Windows.Controls import TextBlock
    ta = {"left": TextAlignment.Left, "center": TextAlignment.Center, "right": TextAlignment.Right}[align]
    st = Style(clr.GetClrType(TextBlock))
    st.BasedOn = grid.FindResource("CellText")
    st.Setters.Add(Setter(TextBlock.TextAlignmentProperty, ta))
    st.Setters.Add(Setter(TextBlock.HorizontalAlignmentProperty, HorizontalAlignment.Stretch))
    cache[align] = st
    return st


def fill_grid(grid, table):
    """As-Excel preview. Returns the row kinds (the window's LoadingRow handler needs them)."""
    from System.Collections.Generic import List
    from System.Windows.Controls import DataGridTextColumn, TextBlock
    from System.Windows.Data import Binding
    from System.Windows.Media import RotateTransform

    heads, rows, kinds = excel_view(table)
    grid.ItemsSource = None
    grid.Columns.Clear()
    cache = {}
    for i, c in enumerate(table.columns):
        col = DataGridTextColumn()
        if c.orientation == "vertical":
            tb = TextBlock()
            tb.Text = heads[i]
            tb.LayoutTransform = RotateTransform(-90)
            col.Header = tb
        else:
            col.Header = heads[i]
        col.Binding = Binding("[%d]" % i)
        col.ElementStyle = _align_style(grid, c.align if c.align in ("left", "center", "right") else "left", cache)
        grid.Columns.Add(col)
    items = List[object]()
    for r in rows:
        item = List[object]()
        for v in r:
            item.Add(v)
        items.Add(item)
    grid.ItemsSource = items
    return kinds


def draw_canvas(canvas, ruler, layout, scale=PX_PER_MM):
    """As-Revit preview: lines + text boxes on a Canvas, plus the per-column width ruler."""
    from System.Windows import FontWeights, TextAlignment, Thickness
    from System.Windows.Controls import Canvas, TextBlock
    from System.Windows.Media import Brushes, RotateTransform
    from System.Windows.Shapes import Line

    lines, texts, captions, width, height = canvas_primitives(layout, scale)
    canvas.Children.Clear()
    canvas.Width, canvas.Height = width, height
    for (x0, y0, x1, y1) in lines:
        ln = Line()
        ln.X1, ln.Y1, ln.X2, ln.Y2 = x0, y0, x1, y1
        ln.Stroke = Brushes.Black
        ln.StrokeThickness = 0.8
        canvas.Children.Add(ln)
    ta = {"left": TextAlignment.Left, "center": TextAlignment.Center, "right": TextAlignment.Right}
    for kind, txt, x, y, w, align, rot in texts:
        tb = TextBlock()
        tb.Text = u"%s" % txt
        tb.FontSize = layout_font_px(layout, scale)
        if kind in ("title", "head", "total"):
            tb.FontWeight = FontWeights.Bold
        if w is not None:
            tb.Width = w
            tb.TextAlignment = ta.get(align, TextAlignment.Left)
        if rot:
            tb.RenderTransform = RotateTransform(-rot)       # Revit rotates counter-clockwise
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
