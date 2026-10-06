# -*- coding: utf-8 -*-
"""Write a sheet model (abaco.sheet.Sheet) to one tab of an .xlsx through Excel COM
(late binding, one Excel instance).

Open or create the workbook -> wipe the tab -> write values -> formulas, number formats, alignment,
vertical headings, bold rows -> fit columns -> merge/format the title -> save -> close.
Range.Formula and Range.NumberFormat are locale independent (English names), so this also works on an
Italian-language Excel.
"""
import os
import System
from System import Type, Activator, Array
from System.Reflection import BindingFlags, Missing
from System.Runtime.InteropServices import Marshal

from abaco.sheet import col_letter

_ALIGN = {"left": -4131, "center": -4108, "right": -4152}     # xlLeft, xlCenter, xlRight


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


def write_table(path, sheet_name, sheet):
    nrows = sheet.nrows
    ncols = sheet.ncols
    data = sheet.values

    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        raise Exception("Folder not found: " + folder)

    xl_type = Type.GetTypeFromProgID("Excel.Application")
    if xl_type is None:
        raise Exception("Excel is not installed or not registered for COM (Excel.Application not found)")
    try:
        app = Activator.CreateInstance.Overloads[Type](xl_type)   # parameterless overload (COM types)
    except Exception:
        app = Activator.CreateInstance(xl_type)

    wb = None
    try:
        _put(app, "Visible", False)
        _put(app, "DisplayAlerts", False)
        wbs = _get(app, "Workbooks")
        new_file = not os.path.exists(path)
        if new_file:
            wb = _call(wbs, "Add")
        else:
            wb = _call(wbs, "Open", path)
            if bool(_get(wb, "ReadOnly")):
                raise Exception("The Excel file is open somewhere else (read-only). "
                                "Close it in Excel and run again: " + path)

        sheets = _get(wb, "Worksheets")
        ws = None
        for i in range(1, int(_get(sheets, "Count")) + 1):
            s = _get(sheets, "Item", i)
            if (u"%s" % _get(s, "Name")).strip().lower() == sheet_name.strip().lower():
                ws = s
                break
        if ws is None:
            if new_file:
                ws = _get(sheets, "Item", 1)
            else:
                last = _get(sheets, "Item", int(_get(sheets, "Count")))
                ws = _call(sheets, "Add", Missing.Value, last)
            _put(ws, "Name", sheet_name)

        # 1. wipe the tab completely: values, formatting, merged cells -> no leftovers from earlier runs
        cells = _get(ws, "Cells")
        _call(cells, "UnMerge")
        _call(cells, "Clear")

        # 2. write the values in one go
        arr = Array.CreateInstance(System.Object, nrows, ncols)
        for i, r in enumerate(data):
            for j, v in enumerate(r):
                if v is None or v == "":
                    continue
                arr[i, j] = v
        rng = _get(ws, "Range", _get(ws, "Cells", 1, 1), _get(ws, "Cells", nrows, ncols))
        _put(rng, "Value2", arr)

        last_col = col_letter(ncols)
        if nrows > 2:
            # 3. formulas: total / min / max rows stay live
            for (r, c), f in sheet.formulas.items():
                _put(_get(ws, "Cells", r, c), "Formula", f)

            # 4. per column: number format and alignment (headings included)
            for ci in range(ncols):
                letter = col_letter(ci + 1)
                fmt = sheet.numfmts[ci]
                if fmt != u"General":
                    _put(_range(ws, "%s3:%s%d" % (letter, letter, nrows)), "NumberFormat", fmt)
                _put(_range(ws, "%s2:%s%d" % (letter, letter, nrows)), "HorizontalAlignment",
                     _ALIGN.get(sheet.aligns[ci], -4131))
                if sheet.vertical[ci]:
                    _put(_range(ws, "%s2" % letter), "Orientation", 90)

            # 5. bold: headings and total rows
            for r in sheet.bold_rows:
                _put(_get(_range(ws, "A%d:%s%d" % (r, last_col, r)), "Font"), "Bold", True)

            # 6. fit the columns (title row excluded)
            _call(_get(_range(ws, "A2:%s%d" % (last_col, nrows)), "Columns"), "AutoFit")

        # 7. title merged and centred over the table
        title = _range(ws, "A1:%s1" % last_col)
        _call(title, "Merge")
        _put(title, "HorizontalAlignment", -4108)      # xlCenter
        font = _get(title, "Font")
        _put(font, "Bold", True)
        _put(font, "Size", 14)

        if new_file:
            _call(wb, "SaveAs", path)
        else:
            _call(wb, "Save")
        return u"Written %d rows x %d columns to tab '%s' in %s (%d live formulas)" % (
            nrows, ncols, sheet_name, path, len(sheet.formulas))
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
