# -*- coding: utf-8 -*-
"""Draw a TableLayout as drafting views (and sheets on the first run). Call inside a transaction.

One Revit text type per appearance element (font, size, bold, italic, underline). Lines use the
<Thin Lines> style. Text colour and cell backgrounds are not drawn in Revit yet (see notes).
"""
import re
import math
import clr
clr.AddReference("RevitAPI")
import Autodesk.Revit.DB as DB

from abaco.layout import MM
from System.Collections.Generic import List

_ALIGN = {"left": DB.HorizontalTextAlignment.Left,
          "center": DB.HorizontalTextAlignment.Center,
          "right": DB.HorizontalTextAlignment.Right}
ELEMENTS = ("title", "heading", "header", "summaryHeader", "summary", "data")
NOTES = []


def _unique(base, existing):
    n, cand = 1, base
    while cand in existing:
        n += 1
        cand = u"%s (%d)" % (base, n)
    return cand


def _text_type(doc, app, element):
    e = app["elements"][element]
    fam = app["font"]["family"]
    size = float(app["font"]["sizeMm"])
    flags = u"".join(lbl for key, lbl in (("bold", u"B"), ("italic", u"I"), ("underline", u"U")) if e[key])
    name = u"Abaco %s %s %.1fmm" % (fam, flags or u"Plain", size)
    for t in DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType):
        if t.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() == name:
            return t
    base = DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType).FirstElement()
    t = base.Duplicate(name)
    t.get_Parameter(DB.BuiltInParameter.TEXT_FONT).Set(fam)
    t.get_Parameter(DB.BuiltInParameter.TEXT_SIZE).Set(size * MM)
    t.get_Parameter(DB.BuiltInParameter.TEXT_STYLE_BOLD).Set(1 if e["bold"] else 0)
    t.get_Parameter(DB.BuiltInParameter.TEXT_STYLE_ITALIC).Set(1 if e["italic"] else 0)
    got = t.get_Parameter(DB.BuiltInParameter.TEXT_STYLE_ITALIC).AsInteger()
    if got != (1 if e["italic"] else 0):
        NOTES.append(u"Text type '%s': italic flag not stored (read back %s)." % (name, got))
    t.get_Parameter(DB.BuiltInParameter.TEXT_STYLE_UNDERLINE).Set(1 if e["underline"] else 0)
    t.get_Parameter(DB.BuiltInParameter.TEXT_BACKGROUND).Set(1)       # transparent
    t.get_Parameter(DB.BuiltInParameter.TEXT_BOX_VISIBILITY).Set(0)
    return t


def _thin_style(doc):
    for gs in DB.FilteredElementCollector(doc).OfClass(DB.GraphicsStyle):
        if gs.Name == u"<Thin Lines>":
            return gs
    return None


def _clear_view(doc, view):
    ids = []
    for cls in (DB.TextNote, DB.CurveElement, DB.FilledRegion):
        for e in DB.FilteredElementCollector(doc, view.Id).OfClass(cls):
            ids.append(e.Id)
    if ids:
        doc.Delete(_ids(ids))


def _ids(ids):
    from System.Collections.Generic import List
    out = List[DB.ElementId]()
    for i in ids:
        out.Add(i)
    return out


def _origin_x(x, w, align):
    if w is None:
        return x
    if align == "center":
        return x + w / 2.0
    if align == "right":
        return x + w
    return x



def _color(hexcolor):
    h = hexcolor.lstrip("#")
    return DB.Color(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _line_style(doc, hexcolor, cache, thin):
    """A line style with the appearance's line colour (black keeps the default thin style)."""
    if not hexcolor or hexcolor.upper() in ("#000000", "000000"):
        return thin
    key = hexcolor.upper()
    if key in cache:
        return cache[key]
    lines_cat = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
    name = u"Abaco %s" % key.lstrip("#")
    sub = None
    if lines_cat.SubCategories.Contains(name):
        sub = lines_cat.SubCategories.get_Item(name)
    if sub is None:
        sub = doc.Settings.Categories.NewSubcategory(lines_cat, name)
    sub.LineColor = _color(key)
    gs = sub.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
    cache[key] = gs
    return gs


def _type_name(t):
    p = t.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    return p.AsString() if p is not None else u""


def _solid_pattern(doc):
    for p in DB.FilteredElementCollector(doc).OfClass(DB.FillPatternElement):
        if p.GetFillPattern().IsSolidFill:
            return p
    return None


def _fill_type(doc, hexcolor, cache):
    """A filled region type with a solid colour, reused across runs."""
    key = hexcolor.upper()
    if key in cache:
        return cache[key]
    name = u"Abaco fill %s" % key.lstrip("#")
    t = None
    for ft in DB.FilteredElementCollector(doc).OfClass(DB.FilledRegionType):
        if _type_name(ft) == name:
            t = ft
            break
    if t is None:
        pat = _solid_pattern(doc)
        if pat is None:
            raise Exception("No solid fill pattern in the project")
        base = DB.FilteredElementCollector(doc).OfClass(DB.FilledRegionType).FirstElement()
        t = base.Duplicate(name)
        t.ForegroundPatternId = pat.Id
        t.ForegroundPatternColor = _color(key)
    cache[key] = t.Id
    return t.Id


def _band(doc, view, page_band, type_id):
    """A row background as a filled region. page_band uses the layout's y (down = positive)."""
    x0, y0, x1, y1, _ = page_band
    if y1 - y0 < 1e-6:
        return
    pts = [(x0, -y0), (x1, -y0), (x1, -y1), (x0, -y1)]
    loop = DB.CurveLoop()
    for i in range(4):
        a, b = pts[i], pts[(i + 1) % 4]
        loop.Append(DB.Line.CreateBound(DB.XYZ(a[0] * MM, a[1] * MM, 0), DB.XYZ(b[0] * MM, b[1] * MM, 0)))
    loops = List[DB.CurveLoop]()
    loops.Add(loop)
    DB.FilledRegion.Create(doc, type_id, view.Id, loops)


def _draw(doc, view, page, types, thin, app, caches):
    import sys
    step = ["start"]
    try:
        step[0] = "bands"
        for band in page.bands:
            if band[4]:
                _band(doc, view, band, _fill_type(doc, band[4], caches["fill"]))

        step[0] = "lines"
        line_gs = _line_style(doc, app["lines"]["color"], caches["lines"], thin)
        for (x0, y0, x1, y1) in page.lines:
            dc = doc.Create.NewDetailCurve(view, DB.Line.CreateBound(DB.XYZ(x0 * MM, y0 * MM, 0),
                                                                      DB.XYZ(x1 * MM, y1 * MM, 0)))
            if line_gs is not None:
                try:
                    dc.LineStyle = line_gs
                except Exception:
                    pass

        step[0] = "texts"
        for el, txt, x, y, w, align, rot in page.texts:
            t = types[el]
            opts = DB.TextNoteOptions(t.Id)
            opts.HorizontalAlignment = _ALIGN.get(align, DB.HorizontalTextAlignment.Left)
            if rot:
                opts.Rotation = math.radians(rot)
            pos = DB.XYZ(_origin_x(x, w, align) * MM, y * MM, 0)
            DB.TextNote.Create(doc, view.Id, pos, txt.replace(u"\n", u"\r"), opts)
    except Exception as ex:
        tb = sys.exc_info()[2]
        line = tb.tb_next.tb_lineno if tb and tb.tb_next else "?"
        raise Exception("drafting step '%s' failed at line %s: %s" % (step[0], line, ex))


def build_tables(doc, layout, view_name, number_prefix=None, title_block=None):
    """Creates or updates one drafting view per page of the layout. No sheets and no viewports.

    Views are named '<view_name> table N'. Running again updates the views with that name in place.
    Views left over from a longer table are emptied and reported. number_prefix and title_block are
    accepted for compatibility with older callers and are ignored.
    """
    report = []
    app = layout.appearance
    types = dict((el, _text_type(doc, app, el)) for el in ELEMENTS)
    del NOTES[:]
    thin = _thin_style(doc)
    caches = {"lines": {}, "fill": {}}

    vft = None
    for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType):
        if v.ViewFamily == DB.ViewFamily.Drafting:
            vft = v
            break
    if vft is None:
        raise Exception("No drafting view type in the project")

    view_names = set(v.Name for v in DB.FilteredElementCollector(doc).OfClass(DB.View))

    pat = re.compile(u"^" + re.escape(view_name) + r" table (\d+)$")
    existing = {}
    for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewDrafting):
        m = pat.match(v.Name)
        if m:
            existing[int(m.group(1))] = v

    total = len(layout.pages)
    for pi, page in enumerate(layout.pages):
        n = pi + 1
        if n in existing:
            view = existing[n]
            _clear_view(doc, view)
            _draw(doc, view, page, types, thin, app, caches)
            report.append(u"UPDATED view '%s' (%d rows)." % (view.Name, page.nrows))
            continue
        view = DB.ViewDrafting.Create(doc, vft.Id)
        view.Name = _unique(u"%s table %d" % (view_name, n), view_names)
        view_names.add(view.Name)
        view.Scale = 1
        _draw(doc, view, page, types, thin, app, caches)
        report.append(u"CREATED view '%s' (%d rows)." % (view.Name, page.nrows))

    for n, view in sorted(existing.items()):
        if n > total:
            _clear_view(doc, view)
            report.append(u"EMPTY: view '%s' is no longer needed. Delete it if you like." % view.Name)

    report.extend(NOTES)
    return report