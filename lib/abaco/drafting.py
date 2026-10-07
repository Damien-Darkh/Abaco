# -*- coding: utf-8 -*-
"""Draw a TableLayout as drafting views (+ sheets on the first run).

Phase 3: text alignment (explicit box width), 90 degree vertical headings, bold type for
titles, headings and total rows. Reads the text tuples produced by layout.build_layout:
    (kind, text, x, y, width_or_None, align, rotation_deg)
Must be called inside an open Revit transaction.
"""
import re
import math
import clr
clr.AddReference("RevitAPI")
import Autodesk.Revit.DB as DB
from System.Collections.Generic import List

from abaco.layout import MM

_BOLD_KINDS = ("title", "head", "total")
_ALIGN = {"left": DB.HorizontalTextAlignment.Left,
          "center": DB.HorizontalTextAlignment.Center,
          "right": DB.HorizontalTextAlignment.Right}


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


def _clamp_width(doc, type_id, w_ft):
    """Revit rejects text-note widths outside the type's allowed range."""
    try:
        lo = DB.TextNote.GetMinimumAllowedWidth(doc, type_id)
        hi = DB.TextNote.GetMaximumAllowedWidth(doc, type_id)
        return min(max(w_ft, lo), hi)
    except Exception:
        return w_ft


def _origin_x(x, w, align):
    """Revit anchors a text note at the edge that matches its alignment (left edge, middle, right edge).
    layout gives the LEFT edge of the box and its width, so centre / right notes need the origin moved."""
    if w is None:
        return x
    if align == "center":
        return x + w / 2.0
    if align == "right":
        return x + w
    return x


def _draw(doc, view, page, t_norm, t_bold):
    for (x0, y0, x1, y1) in page.lines:
        doc.Create.NewDetailCurve(
            view, DB.Line.CreateBound(DB.XYZ(x0 * MM, y0 * MM, 0), DB.XYZ(x1 * MM, y1 * MM, 0)))
    for kind, txt, x, y, w, align, rot in page.texts:
        tid = t_bold.Id if kind in _BOLD_KINDS else t_norm.Id
        opts = DB.TextNoteOptions(tid)
        opts.HorizontalAlignment = _ALIGN.get(align, DB.HorizontalTextAlignment.Left)
        if rot:
            opts.Rotation = math.radians(rot)         # radians; 90 reads bottom to top
        pos = DB.XYZ(_origin_x(x, w, align) * MM, y * MM, 0)
        if w is not None and not rot:
            DB.TextNote.Create(doc, view.Id, pos, _clamp_width(doc, tid, w * MM), txt, opts)
        else:
            DB.TextNote.Create(doc, view.Id, pos, txt, opts)


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
