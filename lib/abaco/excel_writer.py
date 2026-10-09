# -*- coding: utf-8 -*-
"""Write a sheet model (abaco.sheet.Sheet) to one tab of an .xlsx through Excel COM (late binding).

Open or create the workbook -> wipe the tab -> values and formulas -> number formats and alignment ->
fonts and colours per row -> borders -> merges -> wrapping and row heights -> freeze panes -> save -> close.

Alignment: data rows use each field's alignment (Formatting tab); title, heading, group header,
summary header and summary rows use the element's alignment (Appearance tab).
"""
import os
import System
from System import Type, Activator, Array
from System.Reflection import BindingFlags, Missing
from System.Runtime.InteropServices import Marshal

from abaco.sheet import col_letter
from abaco.layout import count_lines

_ALIGN = {"left": -4131, "center": -4108, "right": -4152}
_EDGE_IDX = (7, 8, 9, 10)           # xlEdgeLeft, Top, Bottom, Right
_INSIDE_IDX = (11, 12)              # xlInsideVertical, xlInsideHorizontal
_PT_PER_MM = 2.835
_CHARS_PER_MM = 0.54                # Excel column width unit (characters) per mm, approximate


# ------------------------------------------------------------------------------------------ COM helpers
def _args(a):
    return Array[System.Object](list(a))


def _get(o, name, *a):
    return o.GetType().InvokeMember(name, BindingFlags.GetProperty, None, o, _args(a))


def _put(o, name, value):
    o.GetType().InvokeMember(name, BindingFlags.SetProperty, None, o, _args([value]))


def _call(o, name, *a):
    return o.GetType().InvokeMember(name, BindingFlags.InvokeMethod, None, o, _args(a))


def _range(ws, a1):
    return _get(ws, "Range", a1)


def _bgr(hexcolor):
    h = (hexcolor or u"#000000").lstrip(u"#")
    return int(h[0:2], 16) + 256 * int(h[2:4], 16) + 65536 * int(h[4:6], 16)


def _align(name):
    return _ALIGN.get(name or "left", -4131)


# ------------------------------------------------------------------------------------------ row helpers
def _line_runs(sheet):
    """Runs (first, last) of consecutive Excel rows whose element draws lines (merged rows included)."""
    app = sheet.appearance
    runs, start = [], None
    for r in range(1, len(sheet.row_el) + 1):
        el = sheet.row_el[r - 1]
        on = el is not None and app["elements"][el]["lines"]
        if on and start is None:
            start = r
        elif not on and start is not None:
            runs.append((start, r - 1))
            start = None
    if start is not None:
        runs.append((start, len(sheet.row_el)))
    return runs


def _zebra_fill(sheet, r):
    zebra = sheet.appearance["zebra"]
    if zebra["on"] and r in sheet.zebra_rows:
        return zebra["color"]
    return None


def _fit_rows(ws, sheet, nrows):
    """Row heights from the text in each cell. Excel's AutoFit does not grow wrapped rows reliably,
    so the height is set from the line count. Starts at the heading row so long headings get height."""
    app = sheet.appearance
    pt = app["font"]["sizeMm"] * _PT_PER_MM
    line_pt = pt * 1.35
    wrap = bool(app["wrap"])
    widths = [float(_get(_range(ws, "%s1" % col_letter(ci + 1)), "ColumnWidth"))
              for ci in range(sheet.ncols)]
    for r in range(2, nrows + 1):
        el = "heading" if r == 2 else sheet.row_el[r - 1]
        if el is None:
            continue                                  # blank rows keep Excel's default height
        bold = bool(app["elements"][el]["bold"])
        values = sheet.values[r - 1]
        if r in sheet.merged_rows:                    # full-row text: measured against the whole table
            cells = [(sum(widths), values[0])]
        else:
            cells = list(zip(widths, values))
        lines = 1
        if wrap:
            for w, v in cells:
                if v is None or v == u"":
                    continue
                cpl = max(1, int(w * 11.0 / pt / (1.1 if bold else 1.0)))
                lines = max(lines, count_lines(u"%s" % v, cpl))
        _put(_get(ws, "Rows", r), "RowHeight", max(pt * 1.6, lines * line_pt))


def _readback(ws, sheet, last):
    """What Excel actually holds for each element, written to the log so the formatting can be checked."""
    out, seen = [], set()
    for r in range(1, len(sheet.row_el) + 1):
        el = sheet.row_el[r - 1]
        if el is None or el in seen:
            continue
        seen.add(el)
        rng = _range(ws, "A%d:%s%d" % (r, last, r))
        f = _get(rng, "Font")
        out.append(u"%s: %s %.1fpt bold=%s italic=%s underline=%s wrap=%s" % (
            el, _get(f, "Name"), float(_get(f, "Size")), _get(f, "Bold"),
            _get(f, "Italic"), _get(f, "Underline"), _get(rng, "WrapText")))
    if sheet.zebra_rows:
        z = _range(ws, "A%d" % sheet.zebra_rows[0])
        out.append(u"zebra row colour (BGR): %s" % _get(_get(z, "Interior"), "Color"))
    return out


# ------------------------------------------------------------------------------------------ workbook
def _open_workbook(app, path):
    """Returns (workbook, is_new_file)."""
    wbs = _get(app, "Workbooks")
    if not os.path.exists(path):
        return _call(wbs, "Add"), True
    wb = _call(wbs, "Open", path)
    if bool(_get(wb, "ReadOnly")):
        raise Exception("The Excel file is open somewhere else (read-only). "
                        "Close it in Excel and run again: " + path)
    return wb, False


def _tab(wb, sheet_name, new_file):
    """The worksheet named sheet_name, created if missing (first sheet of a new file is reused)."""
    sheets = _get(wb, "Worksheets")
    count = int(_get(sheets, "Count"))
    for i in range(1, count + 1):
        s = _get(sheets, "Item", i)
        if (u"%s" % _get(s, "Name")).strip().lower() == sheet_name.strip().lower():
            return s
    if new_file:
        ws = _get(sheets, "Item", 1)
    else:
        last_ws = _get(sheets, "Item", count)
        ws = _call(sheets, "Add", Missing.Value, last_ws)
    _put(ws, "Name", sheet_name)
    return ws


def _write_values(ws, sheet, nrows, ncols):
    arr = Array.CreateInstance(System.Object, nrows, ncols)
    for i, r in enumerate(sheet.values):
        for j, v in enumerate(r):
            if v is None or v == "":
                continue
            arr[i, j] = v
    target = _get(ws, "Range", _get(ws, "Cells", 1, 1), _get(ws, "Cells", nrows, ncols))
    _put(target, "Value2", arr)


def _apply_column_formats(ws, sheet, nrows):
    """Number formats, data-row alignment and fixed widths, per column."""
    for ci in range(sheet.ncols):
        L = col_letter(ci + 1)
        if sheet.numfmts[ci] != u"General":
            _put(_range(ws, "%s3:%s%d" % (L, L, nrows)), "NumberFormat", sheet.numfmts[ci])
        _put(_range(ws, "%s3:%s%d" % (L, L, nrows)), "HorizontalAlignment", _align(sheet.aligns[ci]))
        if sheet.vertical[ci]:
            _put(_range(ws, "%s2" % L), "Orientation", 90)
        if sheet.widths[ci]:
            _put(_range(ws, "%s1" % L), "ColumnWidth", sheet.widths[ci] * _CHARS_PER_MM)


def _apply_row_styles(ws, sheet, last):
    """Font, bold, italic, underline, colours and backgrounds per row. Element rows also get their
    element alignment. Data rows keep the field alignment set in _apply_column_formats."""
    app = sheet.appearance
    for r in range(1, sheet.nrows + 1):
        el = sheet.row_el[r - 1]
        if el is None:
            continue
        e = app["elements"][el]
        rng = _range(ws, "A%d:%s%d" % (r, last, r))
        f = _get(rng, "Font")
        _put(f, "Bold", bool(e["bold"]))
        _put(f, "Italic", bool(e["italic"]))
        _put(f, "Underline", 2 if e["underline"] else -4142)
        _put(f, "Color", _bgr(e["color"]))
        fill = e["background"] or _zebra_fill(sheet, r)
        if fill:
            _put(_get(rng, "Interior"), "Color", _bgr(fill))
        if el != "data":
            _put(rng, "HorizontalAlignment", _align(e.get("align")))


def _apply_borders(ws, sheet, last):
    lc = sheet.appearance["lines"]
    idx = []
    if lc["inner"]:
        idx += list(_INSIDE_IDX)
    if lc["outer"]:
        idx += list(_EDGE_IDX)
    if not idx:
        return
    for a, b in _line_runs(sheet):
        bd = _get(_range(ws, "A%d:%s%d" % (a, last, b)), "Borders")
        for i in idx:
            item = _get(bd, "Item", i)
            _put(item, "LineStyle", 1)
            _put(item, "Weight", 2)
            _put(item, "Color", _bgr(lc["color"]))


def _merge_rows(ws, sheet, last):
    """Full-row text (group header, summary header) merged across the table, aligned per element.
    The title row is merged too and centred."""
    app = sheet.appearance
    for r in sheet.merged_rows:
        rng = _range(ws, "A%d:%s%d" % (r, last, r))
        _call(rng, "Merge")
        el = sheet.row_el[r - 1]
        align = "center" if el == "title" else app["elements"][el].get("align")
        _put(rng, "HorizontalAlignment", _align(align))


def _apply_wrap_and_heights(ws, sheet, nrows, last):
    body = _range(ws, "A2:%s%d" % (last, nrows))
    if sheet.appearance["wrap"]:
        _put(body, "WrapText", True)
    _fit_rows(ws, sheet, nrows)


def _freeze_and_grid(app, wb, sheet):
    try:
        _call(wb, "Activate")
        win = _get(app, "ActiveWindow")
        _put(win, "DisplayGridlines", bool(sheet.appearance["excel"]["gridlines"]))
        _put(win, "FreezePanes", False)
        if sheet.appearance["excel"]["freezeHeading"]:
            _put(win, "SplitColumn", 0)
            _put(win, "SplitRow", 2)
            _put(win, "FreezePanes", True)
    except Exception:
        pass                # no window when Excel runs hidden: the formatting still applies


def _save(wb, path, new_file):
    if new_file:
        _call(wb, "SaveAs", path)
    else:
        _call(wb, "Save")


# ------------------------------------------------------------------------------------------ public
def write_table(path, sheet_name, sheet):
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        raise Exception("Folder not found: " + folder)

    xl_type = Type.GetTypeFromProgID("Excel.Application")
    if xl_type is None:
        raise Exception("Excel is not installed or not registered for COM (Excel.Application not found)")
    try:
        app = Activator.CreateInstance.Overloads[Type](xl_type)
    except Exception:
        app = Activator.CreateInstance(xl_type)

    wb = None
    try:
        _put(app, "Visible", False)
        _put(app, "DisplayAlerts", False)
        wb, new_file = _open_workbook(app, path)
        ws = _tab(wb, sheet_name, new_file)

        _call(_get(ws, "Cells"), "UnMerge")
        _call(_get(ws, "Cells"), "Clear")

        nrows, ncols = sheet.nrows, sheet.ncols
        last = col_letter(ncols)
        _write_values(ws, sheet, nrows, ncols)

        font = _get(_range(ws, "A1:%s%d" % (last, nrows)), "Font")
        _put(font, "Name", sheet.appearance["font"]["family"])
        _put(font, "Size", round(sheet.appearance["font"]["sizeMm"] * _PT_PER_MM, 1))

        if nrows > 2:
            for r, (cell, formula) in enumerate(sorted(sheet.formulas.items())):
                _put(_get(ws, "Cells", cell[0], cell[1]), "Formula", formula)
            _apply_column_formats(ws, sheet, nrows)

            for ci in range(sheet.ncols):          # auto columns fit their text; fixed widths stay
                if not sheet.widths[ci]:
                    L = col_letter(ci + 1)
                    _call(_get(_range(ws, "%s2:%s%d" % (L, L, nrows)), "Columns"), "AutoFit")

        _apply_row_styles(ws, sheet, last)
        _apply_borders(ws, sheet, last)
        _apply_wrap_and_heights(ws, sheet, nrows, last)
        _merge_rows(ws, sheet, last)
        _freeze_and_grid(app, wb, sheet)

        probe = _readback(ws, sheet, last)
        _save(wb, path, new_file)
        return u"Written %d rows x %d columns to tab '%s' in %s (%d live formulas)\n%s" % (
            nrows, ncols, sheet_name, path, len(sheet.formulas), u"\n".join(probe))
    finally:
        try:
            if wb is not None:
                _call(wb, "Close", False)
        finally:
            try:
                _call(app, "Quit")
            finally:
                try:
                    Marshal.FinalReleaseComObject(app)
                except Exception:
                    pass