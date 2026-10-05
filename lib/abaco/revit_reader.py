# -*- coding: utf-8 -*-
"""Revit -> records (Phase 1). The ONLY module of the data layer that touches the Revit API.

  list_model_categories(doc)          categories that have elements
  read_category(doc, category, log)   one pass over the model: core values + field catalogue
  ensure_values(doc, rs, keys, log)   fill in values of extra catalogue fields on demand (cached)

Why on demand: reading every parameter of every element is slow on big models. The catalogue (names, kinds,
scopes) is cheap and complete; the values of a field are read the first time the user uses it.

Revit 2024-2027 safe: ElementId.Value, ForgeTypeId units (UnitTypeId / SpecTypeId), ElementId(Int64).
Common-subset Python (IronPython 2.7 / 3.4 / CPython 3): no f-strings.
"""
import re
import clr
clr.AddReference("RevitAPI")
import Autodesk.Revit.DB as DB
from System import Guid

from abaco.records import (
    Field, Layer, TypeRecord, ElementRecord, RecordSet, core_fields,
    K_TYPE_MARK, K_TYPE_NAME, K_FAMILY, K_LEVEL, K_WIDTH, K_HEIGHT, K_LENGTH, K_AREA, K_ELEMENT_ID,
    M2)

try:
    _long = long            # IronPython 2.7: a long binds to ElementId(Int64)
except NameError:
    _long = int

_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")

# parameters already covered by a core field: kept out of the catalogue to avoid duplicates
_SKIP_KEYS = set(["ALL_MODEL_TYPE_MARK", "SYMBOL_NAME_PARAM", "WALL_BASE_CONSTRAINT", "FAMILY_LEVEL_PARAM",
                  "SCHEDULE_LEVEL_PARAM", "INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM"])

_WIDTH_NAMES = ["WINDOW_WIDTH", "DOOR_WIDTH", "FAMILY_WIDTH_PARAM", "Width"]
_HEIGHT_NAMES = ["WINDOW_HEIGHT", "DOOR_HEIGHT", "FAMILY_HEIGHT_PARAM", "WALL_USER_HEIGHT_PARAM", "Height"]
_CURTAIN_HEIGHT_NAMES = ["WALL_USER_HEIGHT_PARAM"]

_UNITS = {"length": u"m", "area": M2, "volume": u"m\u00b3"}


# ------------------------------------------------------------------------------------------ small helpers
def eid_val(eid):
    return int(eid.Value)                       # Revit 2024+ (never IntegerValue)


def make_id(n):
    return DB.ElementId(_long(n))


def convert(value, kind):
    """Internal units -> metres / m2 / m3 (ForgeTypeId API)."""
    if kind == "length":
        return DB.UnitUtils.ConvertFromInternalUnits(value, DB.UnitTypeId.Meters)
    if kind == "area":
        return DB.UnitUtils.ConvertFromInternalUnits(value, DB.UnitTypeId.SquareMeters)
    if kind == "volume":
        return DB.UnitUtils.ConvertFromInternalUnits(value, DB.UnitTypeId.CubicMeters)
    return value


def elements_filter(doc, cat):
    return (DB.FilteredElementCollector(doc)
            .WherePasses(DB.ElementCategoryFilter(cat.Id))
            .WhereElementIsNotElementType())


def list_model_categories(doc):
    """Model categories that have elements in this project: [(name, count, Category)], sorted by name."""
    items = []
    for cat in doc.Settings.Categories:
        try:
            if cat.CategoryType != DB.CategoryType.Model:
                continue
            n = elements_filter(doc, cat).GetElementCount()
        except Exception:
            continue
        if n:
            items.append((cat.Name, n, cat))
    items.sort(key=lambda t: t[0].lower())
    return items


def _bip(name):
    return getattr(DB.BuiltInParameter, name, None)


def _param(obj, *names):
    """First parameter that exists and has a value (BuiltInParameter names, then plain names). Same as v1."""
    for nme in names:
        b = _bip(nme)
        p = obj.get_Parameter(b) if b is not None else obj.LookupParameter(nme)
        if p is not None and p.HasValue:
            return p
    return None


def _text(p):
    if p is None:
        return None
    s = (p.AsString() or p.AsValueString() or u"").strip()
    return s or None


# ------------------------------------------------------------------------------------ parameter identity
def _param_key(p):
    """Stable key: shared -> GUID, built-in -> enum name, project -> 'id:<n>'. Never the display name."""
    d = p.Definition
    if d is None:
        return None
    if p.IsShared:
        return p.GUID.ToString()
    if isinstance(d, DB.InternalDefinition):
        bip = d.BuiltInParameter
        if bip != DB.BuiltInParameter.INVALID:
            return bip.ToString()
        n = eid_val(d.Id)
        if n != -1:
            return u"id:%d" % n
    return u"name:%s" % d.Name          # last resort (localised): flagged by the catalogue note


def _find_param(obj, key):
    try:
        if key.startswith(u"id:"):
            n = int(key[3:])
            for p in obj.Parameters:
                d = p.Definition
                if isinstance(d, DB.InternalDefinition) and eid_val(d.Id) == n:
                    return p
            return None
        if key.startswith(u"name:"):
            return obj.LookupParameter(key[5:])
        if _GUID_RE.match(key):
            return obj.get_Parameter(Guid(key))
        b = _bip(key)
        return obj.get_Parameter(b) if b is not None else None
    except Exception:
        return None


def _kind_of(p):
    """Field kind from the parameter's storage type and spec; None = not usable as a column."""
    st = p.StorageType
    if st == DB.StorageType.String:
        return "text"
    if st == DB.StorageType.ElementId:
        return "elementid"
    spec = None
    try:
        spec = p.Definition.GetDataType()
    except Exception:
        pass
    if st == DB.StorageType.Integer:
        if spec is not None and spec.Equals(DB.SpecTypeId.Boolean.YesNo):
            return "yesno"
        s = p.AsValueString()               # enumerations (e.g. Function = Exterior) read as text
        if s and not re.match(r"^\s*-?\d+\s*$", s):
            return "text"
        return "integer"
    if st == DB.StorageType.Double:
        if spec is not None:
            if spec.Equals(DB.SpecTypeId.Length):
                return "length"
            if spec.Equals(DB.SpecTypeId.Area):
                return "area"
            if spec.Equals(DB.SpecTypeId.Volume):
                return "volume"
        return "number"                     # other specs (angle, ...): raw internal value
    return None


def _read_param(doc, p, kind):
    if p is None or not p.HasValue:
        return None
    if kind == "text":
        return _text(p)
    if kind == "yesno":
        return u"Yes" if p.AsInteger() else u"No"
    if kind == "integer":
        return p.AsInteger()
    if kind in ("length", "area", "volume"):
        return convert(p.AsDouble(), kind)
    if kind == "number":
        return p.AsDouble()
    if kind == "elementid":
        eid = p.AsElementId()
        if eid is None or eid_val(eid) < 0:
            return None
        e = doc.GetElement(eid)
        nm = getattr(e, "Name", None) if e is not None else None
        return nm or None
    return None


# ------------------------------------------------------------------------------ v1 core values (ported)
def _length(el, typ, names):
    for obj in (el, typ):
        if obj is None:
            continue
        p = _param(obj, *names)
        if p is not None and p.StorageType == DB.StorageType.Double:
            return convert(p.AsDouble(), "length")
    return None


def _level_name(doc, el):
    # walls: base constraint; everything else: its level (same order of attempts as v1)
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
    return None


def _compound(typ):
    try:
        f = getattr(typ, "GetCompoundStructure", None)
        return f() if f is not None else None
    except Exception:
        return None


def _is_curtain(typ):
    try:
        return typ.Kind == DB.WallKind.Curtain
    except Exception:
        return False


def _type_record(doc, typ, type_id):
    p_name = typ.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    values = {
        K_TYPE_MARK: _text(_param(typ, "ALL_MODEL_TYPE_MARK", "Type Mark")),
        K_TYPE_NAME: _text(p_name),
        K_FAMILY: (getattr(typ, "FamilyName", "") or None),
    }
    layers = None
    cs = _compound(typ)
    if cs is not None:
        layers = []
        for idx, layer in enumerate(cs.GetLayers()):
            mid = eid_val(layer.MaterialId)
            name, mat_id = u"None / Air", None
            if mid >= 0:
                mat = doc.GetElement(layer.MaterialId)
                if mat:
                    name = mat.Name
                mat_id = mid
            layers.append(Layer(idx + 1, mat_id, name, convert(layer.Width, "length"), u"%s" % layer.Function))
    return TypeRecord(type_id, values, layers, _is_curtain(typ))


def _element_values(doc, el, typ, is_curtain):
    v = {}
    v[K_ELEMENT_ID] = eid_val(el.Id)
    v[K_LEVEL] = _level_name(doc, el) or None
    v[K_WIDTH] = _length(el, typ, _WIDTH_NAMES)
    v[K_HEIGHT] = _length(el, typ, _CURTAIN_HEIGHT_NAMES if is_curtain else _HEIGHT_NAMES)
    p = el.get_Parameter(DB.BuiltInParameter.HOST_AREA_COMPUTED)
    v[K_AREA] = convert(p.AsDouble(), "area") if (p is not None and p.HasValue) else None
    p = el.get_Parameter(DB.BuiltInParameter.CURVE_ELEM_LENGTH)
    v[K_LENGTH] = convert(p.AsDouble(), "length") if (p is not None and p.HasValue) else None
    return v


def _material_areas(el, tr):
    """Per-material area of one element (same quantity as 'Material: Area' in Revit), m2."""
    out = {}
    for mid in tr.material_ids():
        try:
            a = el.GetMaterialArea(make_id(mid), False)
        except Exception:
            a = 0.0
        out[mid] = convert(a, "area")
    return out


# ------------------------------------------------------------------------------------------- catalogue
def _scan_params(obj, scope, rs):
    for p in obj.Parameters:
        try:
            key = _param_key(p)
            if key is None or key in _SKIP_KEYS or rs.has_field(key):
                continue
            kind = _kind_of(p)
            if kind is None:
                continue
            label = p.Definition.Name
            if not label:
                continue
            if key.startswith(u"name:"):
                rs.notes.append(u"Parameter '%s' has no stable id; its key depends on the Revit language." % label)
            rs.add_field(Field(key, label, scope, kind, _UNITS.get(kind)))
        except Exception:
            continue


# ---------------------------------------------------------------------------------------------- public
def read_category(doc, category, log=None):
    """Scan the model once. Returns a RecordSet with core values filled in and the full field catalogue."""
    log = log or (lambda m: None)
    is_walls = eid_val(category.Id) == int(DB.BuiltInCategory.OST_Walls)
    rs = RecordSet(eid_val(category.Id), category.Name)
    for f in core_fields(is_walls):
        rs.add_field(f)
        rs.loaded_keys.add(f.key)

    type_objs, reps = {}, {}
    n = 0
    for el in elements_filter(doc, category):
        type_id = el.GetTypeId()
        typ = doc.GetElement(type_id)
        if typ is None:
            continue
        tkey = eid_val(type_id)
        tr = rs.types.get(tkey)
        if tr is None:
            tr = _type_record(doc, typ, tkey)
            rs.add_type(tr)
            type_objs[tkey] = typ
            reps[tkey] = el
        er = ElementRecord(eid_val(el.Id), tkey, _element_values(doc, el, typ, tr.is_curtain))
        if tr.is_layered:
            er.material_areas = _material_areas(el, tr)
        rs.add_element(er)
        n += 1
        if n % 200 == 0:
            log(u"Reading model... %d elements" % n)

    # catalogue: every used type, plus one representative instance per type
    for tkey, typ in type_objs.items():
        _scan_params(typ, "type", rs)
    for tkey, el in reps.items():
        _scan_params(el, "element", rs)
    return rs


def ensure_values(doc, rs, keys, log=None):
    """Fill in the values of catalogue fields not read yet. Returns the keys that cannot be read."""
    log = log or (lambda m: None)
    missing = []
    for key in keys:
        if key in rs.loaded_keys:
            continue
        f = rs.field(key)
        if f is None:
            missing.append(key)
            continue
        if f.scope in ("layer", "group"):
            continue                                    # computed by the pipeline, nothing to read
        if f.scope == "type":
            for tid, tr in rs.types.items():
                obj = doc.GetElement(make_id(tid))
                tr.values[key] = _read_param(doc, _find_param(obj, key), f.kind) if obj is not None else None
        else:
            for er in rs.elements:
                obj = doc.GetElement(make_id(er.element_id))
                er.values[key] = _read_param(doc, _find_param(obj, key), f.kind) if obj is not None else None
        rs.loaded_keys.add(key)
        log(u"Read values of '%s'." % f.label)
    return missing
