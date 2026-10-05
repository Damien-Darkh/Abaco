# -*- coding: utf-8 -*-
"""Revit elements -> list of rows (title row, header row, data rows, blank spacer rows).

Port of the Dynamo "export" Python node (4ebf70). Three table shapes:
  * curtain walls          : Type Mark | Name | Count | Length | Height | Area | Base Constraint
  * layered types          : Type Mark | Name | Order | Material | Thickness | Function | Material Area | Level
                             (walls, floors, roofs, ceilings)
  * everything else        : Type Mark | Family | Name | Width | Height | Count | Level (doors, windows, ...)
"""
import clr
clr.AddReference("RevitAPI")
import Autodesk.Revit.DB as DB

SQFT_TO_SQM = 0.09290304
FT_TO_M = 0.3048


def eid_val(eid):
    try:
        return eid.Value          # Revit 2024+
    except AttributeError:
        return eid.IntegerValue   # older versions


def _bip(name):
    return getattr(DB.BuiltInParameter, name, None)


def _param(obj, *names):
    """First parameter that exists and has a value (BuiltInParameter names, then plain names)."""
    for nme in names:
        b = _bip(nme)
        p = obj.get_Parameter(b) if b is not None else obj.LookupParameter(nme)
        if p is not None and p.HasValue:
            return p
    return None


def _as_text(p):
    if p is None:
        return u""
    return p.AsString() or p.AsValueString() or u""


def _length_m(el, typ, names):
    for obj in (el, typ):
        if obj is None:
            continue
        p = _param(obj, *names)
        if p is not None and p.StorageType == DB.StorageType.Double:
            return round(p.AsDouble() * FT_TO_M, 3)
    return None


def _level_name(doc, el):
    # walls: base constraint; everything else: its level
    if hasattr(el, "WallType"):
        p = el.get_Parameter(DB.BuiltInParameter.WALL_BASE_CONSTRAINT)
        if p is not None and p.HasValue:
            lv = doc.GetElement(p.AsElementId())
            if lv:
                return lv.Name
    try:
        lid = el.LevelId
        if lid is not None and eid_val(lid) > 0:
            lv = doc.GetElement(lid)
            if lv:
                return lv.Name
    except Exception:
        pass
    p = _param(el, "SCHEDULE_LEVEL_PARAM", "FAMILY_LEVEL_PARAM", "INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM")
    if p is not None and p.StorageType == DB.StorageType.ElementId:
        lv = doc.GetElement(p.AsElementId())
        if lv:
            return lv.Name
    return u""


def _area_m2(el):
    p = el.get_Parameter(DB.BuiltInParameter.HOST_AREA_COMPUTED)
    if p is not None and p.HasValue:
        return p.AsDouble() * SQFT_TO_SQM
    return None


def _compound(typ):
    f = getattr(typ, "GetCompoundStructure", None)
    return f() if f is not None else None


def _is_curtain(typ):
    try:
        return typ.Kind == DB.WallKind.Curtain
    except Exception:
        return False


def _type_mark(typ):
    return _as_text(_param(typ, "ALL_MODEL_TYPE_MARK", "Type Mark")).strip()


def _type_name(typ):
    return _as_text(typ.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM))


def _fam_name(typ):
    return getattr(typ, "FamilyName", "") or ""


def build_table(doc, elements, title_in, curtain_mode):
    """elements: Revit elements (instances). curtain_mode True = curtain walls only,
    False = everything except curtain walls. Returns list of rows."""
    elements = [e for e in elements if e is not None]

    # ------------------------------------------------ collect: one group per type + level (+ size)
    groups = {}
    for el in elements:
        if isinstance(el, DB.ElementType):
            typ, inst = el, None
        else:
            typ, inst = doc.GetElement(el.GetTypeId()), el
            if typ is None:
                continue
        if _is_curtain(typ) != curtain_mode:
            continue                      # curtain walls have their own export (mode switch)
        level = _level_name(doc, inst) if inst is not None else u""
        cs = _compound(typ)
        w = h = None
        if curtain_mode:
            h = _length_m(inst, typ, ["WALL_USER_HEIGHT_PARAM"])
        elif cs is None:
            w = _length_m(inst, typ, ["WINDOW_WIDTH", "DOOR_WIDTH", "FAMILY_WIDTH_PARAM", "Width"])
            h = _length_m(inst, typ, ["WINDOW_HEIGHT", "DOOR_HEIGHT", "FAMILY_HEIGHT_PARAM",
                                      "WALL_USER_HEIGHT_PARAM", "Height"])
        key = (eid_val(typ.Id), level, w, h)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"type": typ, "level": level, "w": w, "h": h, "count": 0,
                               "area": 0.0, "has_area": False, "length": 0.0, "mat": {}}
        if inst is None:
            continue
        g["count"] += 1
        a = _area_m2(inst)
        if a is not None:
            g["area"] += a
            g["has_area"] = True
        if curtain_mode:
            lp = inst.get_Parameter(DB.BuiltInParameter.CURVE_ELEM_LENGTH)
            if lp is not None and lp.HasValue:
                g["length"] += lp.AsDouble() * FT_TO_M
        if cs is not None:
            # material area per layer material (same as the "Material: Area" quantity in Revit)
            for layer in cs.GetLayers():
                mid = layer.MaterialId
                v = eid_val(mid)
                if v < 0:
                    continue
                try:
                    ma = inst.GetMaterialArea(mid, False)
                except Exception:
                    ma = 0.0
                g["mat"][v] = g["mat"].get(v, 0.0) + ma

    num = lambda x: x if x is not None else u""
    all_walls = all(isinstance(g["type"], DB.WallType) for g in groups.values()) if groups else True
    level_header = u"Base Constraint" if (all_walls or curtain_mode) else u"Level"

    rows = []
    if curtain_mode:
        headers = [u"Type Mark", u"Wall Type Name", u"Count", u"Total Length (m)", u"Height (m)",
                   u"Area (m\u00b2)", u"Base Constraint"]
        name_cols = [1]
        for g in groups.values():
            typ = g["type"]
            rows.append([_type_mark(typ), _type_name(typ), g["count"], round(g["length"], 2), num(g["h"]),
                         round(g["area"], 2) if g["has_area"] else u"", g["level"]])

        def sort_key(r):
            return (r[6].lower(), r[0].lower(), r[1].lower(), r[4] if r[4] != u"" else -1)

    elif any(_compound(g["type"]) is not None for g in groups.values()):
        headers = [u"Type Mark", u"Wall Type Name" if all_walls else u"Type Name", u"Order", u"Material",
                   u"Thickness (m)", u"Function", u"Material Area (m²)", u"Wall Area (m²)", level_header]

        name_cols = [1]
        for g in groups.values():
            typ = g["type"]
            mark, name = _type_mark(typ), _type_name(typ)
            cs = _compound(typ)
            if cs is None:
                rows.append([mark, name, u"", u"(no layers)", u"", u"", u"", g["level"]])  # e.g. stacked walls
                continue
            for idx, layer in enumerate(cs.GetLayers()):
                v = eid_val(layer.MaterialId)
                mat_name, mat_area = u"None / Air", u""
                if v >= 0:
                    mat = doc.GetElement(layer.MaterialId)
                    if mat:
                        mat_name = mat.Name
                    if v in g["mat"]:
                        mat_area = round(g["mat"][v] * SQFT_TO_SQM, 2)
                rows.append([mark, name, idx + 1, mat_name, round(layer.Width * FT_TO_M, 4),
                        u"%s" % layer.Function,
                        mat_area,
                        round(g["area"], 2) if g["has_area"] else u"",
                        g["level"]])

        def sort_key(r):
            return (r[7].lower(), r[0].lower(), r[1].lower(), r[2] if isinstance(r[2], int) else 0)

    else:
        headers = [u"Type Mark", u"Family", u"Type Name", u"Width (m)", u"Height (m)", u"Count", level_header]
        name_cols = [1, 2]
        for g in groups.values():
            typ = g["type"]
            rows.append([_type_mark(typ), _fam_name(typ), _type_name(typ), num(g["w"]), num(g["h"]),
                         g["count"], g["level"]])

        def sort_key(r):
            return (r[6].lower(), r[0].lower(), r[1].lower(), r[2].lower(),
                    r[3] if r[3] != u"" else -1, r[4] if r[4] != u"" else -1)

    LV = len(headers) - 1            # last column = base constraint / level

    # nested sort: level A-Z, then Type Mark A-Z, then order / size smallest-largest
    rows.sort(key=sort_key)

    category = u""
    for e_ in elements:
        if getattr(e_, "Category", None) is not None:
            category = e_.Category.Name
            break
    title = title_in if (title_in and u"%s" % title_in.strip()) else (u"Abaco " + category).strip()

    table_data = [[title] + [u""] * LV,      # title row (merged by the Excel / Revit writers)
                  headers]

    prev = None
    for r in rows:
        # new group = new Type Mark within the same level/base constraint
        # (if Type Mark is blank, each type name counts as its own group)
        key = (r[LV], r[0]) if r[0] else tuple([r[LV], r[0]] + [r[c] for c in name_cols])
        if prev is not None and key != prev:
            table_data.append([u""] * len(headers))        # blank spacer row
        table_data.append(r)
        prev = key

    return table_data
