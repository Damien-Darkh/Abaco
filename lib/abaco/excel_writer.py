# -*- coding: utf-8 -*-
"""Write a table to one tab of an .xlsx through Excel COM (late binding, one Excel instance).

Port of the Dynamo Excel node (2622c8): open or create the workbook -> wipe the tab ->
write the table -> merge/format the title -> save -> close.
"""
import os
import System
from System import Type, Activator, Array
from System.Reflection import BindingFlags, Missing
from System.Runtime.InteropServices import Marshal


def _args(a):
    return Array[System.Object](list(a))


def _get(o, name, *a):
    return o.GetType().InvokeMember(name, BindingFlags.GetProperty, None, o, _args(a))


def _put(o, name, value):
    o.GetType().InvokeMember(name, BindingFlags.SetProperty, None, o, _args([value]))


def _call(o, name, *a):
    return o.GetType().InvokeMember(name, BindingFlags.InvokeMethod, None, o, _args(a))


def col_letter(n):
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def write_table(path, sheet_name, data):
    nrows = len(data)
    ncols = max(len(r) for r in data) if nrows else 1

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

        # 2. write the table in one go
        arr = Array.CreateInstance(System.Object, nrows, ncols)
        for i, r in enumerate(data):
            for j, v in enumerate(r):
                if v is None or v == "":
                    continue
                arr[i, j] = v
        rng = _get(ws, "Range", _get(ws, "Cells", 1, 1), _get(ws, "Cells", nrows, ncols))
        _put(rng, "Value2", arr)

        # 3. formatting: headings bold, columns fitted, title merged and centred over the table
        last_col = col_letter(ncols)
        if nrows > 1:
            _call(_get(_get(ws, "Range", "A2:%s%d" % (last_col, nrows)), "Columns"), "AutoFit")
            _put(_get(_get(ws, "Range", "A2:%s2" % last_col), "Font"), "Bold", True)
        title = _get(ws, "Range", "A1:%s1" % last_col)
        _call(title, "Merge")
        _put(title, "HorizontalAlignment", -4108)      # xlCenter
        font = _get(title, "Font")
        _put(font, "Bold", True)
        _put(font, "Size", 14)

        if new_file:
            _call(wb, "SaveAs", path)
        else:
            _call(wb, "Save")
        return u"Written %d rows x %d columns to tab '%s' in %s" % (nrows, ncols, sheet_name, path)
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
