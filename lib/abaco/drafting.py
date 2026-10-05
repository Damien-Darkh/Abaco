# -*- coding: utf-8 -*-
"""Draw a TableLayout as drafting views (+ sheets on the first run).

Port of the second half of the Dynamo "Revit table" node (3436a1).
Must be called inside an open Revit transaction.
"""
import re
import clr
clr.AddReference("RevitAPI")
import Autodesk.Revit.DB as DB
from System.Collections.Generic import List

from abaco.layout import MM


def _unique(base, existing):
    n, cand = 1, base
    while cand in existing:
        n += 1
        cand = u"%s (%d)" % (base, n)
    return cand


def _get_text_type(doc, name, bold, text_mm):
    for t in DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType):
        if t.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() == name:
            return t
    base = DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType).FirstElement()
    t = base.Duplicate(name)
    t.get_Parameter(DB.BuiltInParameter.TEXT_SIZE).Set(text_mm * MM)
    t.get_Parameter(DB.BuiltInParameter.TEXT_STYLE_BOLD).Set(1 if bold else 0)
    t.get_Parameter(DB.BuiltInParameter.TEXT_STYLE_ITALIC).Set(0)
    t.get_Parameter(DB.BuiltInParameter.TEXT_BACKGROUND).Set(1)   # transparent
    t.get_Parameter(DB.BuiltInParameter.TEXT_BOX_VISIBILITY).Set(0)
    return t


def _clear_view(doc, view):
    ids = List[DB.ElementId]()
    for e in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.TextNote):
        ids.Add(e.Id)
    for e in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.CurveElement):
        ids.Add(e.Id)
    if ids.Count:
        doc.Delete(ids)


def _draw(doc, view, page, t_norm, t_bold):
    for (x0, y0, x1, y1) in page.lines:
        doc.Create.NewDetailCurve(
            view, DB.Line.CreateBound(DB.XYZ(x0 * MM, y0 * MM, 0), DB.XYZ(x1 * MM, y1 * MM, 0)))
    for kind, txt, x, y, w in page.texts:
        tid = t_bold.Id if kind in ("title", "head") else t_norm.Id
        opts = DB.TextNoteOptions(tid)
        if kind == "title":
            opts.HorizontalAlignment = DB.HorizontalTextAlignment.Center
            DB.TextNote.Create(doc, view.Id, DB.XYZ(x * MM, y * MM, 0), w * MM, txt, opts)
        else:
            opts.HorizontalAlignment = DB.HorizontalTextAlignment.Left
            DB.TextNote.Create(doc, view.Id, DB.XYZ(x * MM, y * MM, 0), txt, opts)


def build_tables(doc, layout, sheet_name, number_prefix, text_mm, title_block=None):
    """title_block: a FamilySymbol (or None for sheets without a title block). Returns report lines."""
    report = []
    tag = u"%.1fmm" % text_mm
    t_norm = _get_text_type(doc, u"Abaco Table %s" % tag, False, text_mm)
    t_bold = _get_text_type(doc, u"Abaco Table %s Bold" % tag, True, text_mm)

    vft = None
    for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType):
        if v.ViewFamily == DB.ViewFamily.Drafting:
            vft = v
            break
    if vft is None:
        raise Exception("No drafting view type in the project")

    view_names = set(v.Name for v in DB.FilteredElementCollector(doc).OfClass(DB.View))
    sheet_numbers = set(s.SheetNumber for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet))

    if title_block is not None:
        if not title_block.IsActive:
            title_block.Activate()
            doc.Regenerate()
        tb_id = title_block.Id
    else:
        tb_id = DB.ElementId.InvalidElementId

    # views made by an earlier run of this table: "<name> table <n>"
    pat = re.compile(u"^" + re.escape(sheet_name) + r" table (\d+)$")
    existing = {}
    for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewDrafting):
        m = pat.match(v.Name)
        if m:
            existing[int(m.group(1))] = v
    first_run = not existing

    total = len(layout.pages)
    for pi, page in enumerate(layout.pages):
        n = pi + 1
        if n in existing:
            view = existing[n]
            _clear_view(doc, view)            # old rows and formatting removed, nothing left over
            _draw(doc, view, page, t_norm, t_bold)
            report.append(u"UPDATED view '%s' (%d rows). Its sheet placement is unchanged." % (view.Name, page.nrows))
            continue
        view = DB.ViewDrafting.Create(doc, vft.Id)
        view.Name = _unique(u"%s table %d" % (sheet_name, n), view_names)
        view_names.add(view.Name)
        view.Scale = 1                        # 1:1 -> model mm = sheet mm
        _draw(doc, view, page, t_norm, t_bold)
        if first_run:
            sheet = DB.ViewSheet.Create(doc, tb_id)
            num = _unique(u"%s-%02d" % (number_prefix, n), sheet_numbers)
            sheet_numbers.add(num)
            sheet.SheetNumber = num
            sheet.Name = u"%s (%d/%d)" % (sheet_name, n, total)
            DB.Viewport.Create(doc, sheet.Id, view.Id,
                               DB.XYZ((20 + layout.table_w / 2.0) * MM,
                                      (20 + page.height / 2.0 + layout.row_h) * MM, 0))
            report.append(u"CREATED sheet %s with view '%s' (%d rows)" % (num, view.Name, page.nrows))
        else:
            report.append(u"NEW PAGE: view '%s' created because the table grew - place it on a sheet." % view.Name)

    for n, view in sorted(existing.items()):
        if n > total:
            _clear_view(doc, view)
            report.append(u"EMPTY: view '%s' is no longer needed (table shrank) - remove it from its sheet "
                          u"if you like." % view.Name)
    return report
