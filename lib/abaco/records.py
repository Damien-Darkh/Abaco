# -*- coding: utf-8 -*-
"""Neutral data model for Abaco Tables (Phase 1). Pure Python: NO Revit imports.

Units: lengths in metres, areas in square metres, volumes in cubic metres, full precision (rounding is a
formatting concern, Phase 2). Missing values are None. Yes/No parameters are the text u"Yes" / u"No".

Three levels of data (see development.md 1.1):
  element  one value set per Revit element        -> ElementRecord.values
  type     one value set per element type         -> TypeRecord.values  (stored once per type)
  layer    compound-structure layers of a type    -> TypeRecord.layers  (stored once per type)
plus per-element material areas (ElementRecord.material_areas) for layered types.

Field scopes: element | type | layer | group.  "group" fields (Count) are computed by the pipeline and are
never stored in a record.
"""

SCOPES = ("element", "type", "layer", "group")
KINDS = ("text", "number", "integer", "yesno", "length", "area", "volume", "elementid")

# Stable keys of the built-in fields. Parameter fields use the BuiltInParameter name, the shared-parameter
# GUID, or "id:<ParameterElement id>" (never the localised display name). "@..." = not a parameter.
K_TYPE_MARK = "ALL_MODEL_TYPE_MARK"
K_TYPE_NAME = "SYMBOL_NAME_PARAM"
K_FAMILY = "@FAMILY"
K_LEVEL = "@LEVEL"                 # walls: base constraint; others: level (same rules as v1)
K_WIDTH = "@WIDTH"
K_HEIGHT = "@HEIGHT"
K_LENGTH = "@LENGTH"               # element curve length; the pipeline sums it per group
K_AREA = "@AREA"                   # HOST_AREA_COMPUTED; the pipeline sums it per group
K_ELEMENT_ID = "@ELEMENT_ID"
K_COUNT = "@COUNT"                 # group scope, computed
K_LAYER_ORDER = "@LAYER_ORDER"
K_LAYER_MATERIAL = "@LAYER_MATERIAL"
K_LAYER_THICKNESS = "@LAYER_THICKNESS"
K_LAYER_FUNCTION = "@LAYER_FUNCTION"
K_LAYER_AREA = "@LAYER_AREA"       # material area, taken from ElementRecord.material_areas

M2 = u"m\u00b2"


class Field(object):
    """Anything that can become a column."""

    def __init__(self, key, label, scope, kind, unit=None, aggregate=None, core=False, group=None):
        if scope not in SCOPES:
            raise ValueError("bad scope %r" % (scope,))
        if kind not in KINDS:
            raise ValueError("bad kind %r" % (kind,))
        self.key = key
        self.label = label
        self.scope = scope
        self.kind = kind
        self.unit = unit
        self.aggregate = aggregate      # "sum" = the pipeline adds this up when it groups elements
        self.core = core                # built-in field, always in the catalogue
        self.group = group              # Revit parameter group label, e.g. u"Vertical Grid" (tells twins apart)

    def to_dict(self):
        return dict(key=self.key, label=self.label, scope=self.scope, kind=self.kind,
                    unit=self.unit, aggregate=self.aggregate, core=self.core, group=self.group)

    @staticmethod
    def from_dict(d):
        return Field(d["key"], d["label"], d["scope"], d["kind"], d.get("unit"),
                     d.get("aggregate"), d.get("core", False), d.get("group"))

    def __repr__(self):
        return "Field(%r, %r, %s, %s)" % (self.key, self.label, self.scope, self.kind)


def core_fields(is_walls=False):
    """The built-in fields of v1 (always present). Labels match the v1 headings exactly."""
    return [
        Field(K_TYPE_MARK, u"Type Mark", "type", "text", core=True),
        Field(K_TYPE_NAME, u"Wall Type Name" if is_walls else u"Type Name", "type", "text", core=True),
        Field(K_FAMILY, u"Family", "type", "text", core=True),
        Field(K_LAYER_ORDER, u"Order", "layer", "integer", core=True),
        Field(K_LAYER_MATERIAL, u"Material", "layer", "text", core=True),
        Field(K_LAYER_THICKNESS, u"Thickness (m)", "layer", "length", u"m", core=True),
        Field(K_LAYER_FUNCTION, u"Function", "layer", "text", core=True),
        Field(K_LAYER_AREA, u"Material Area (%s)" % M2, "layer", "area", M2, core=True),
        Field(K_LEVEL, u"Base Constraint" if is_walls else u"Level", "element", "text", core=True),
        Field(K_WIDTH, u"Width (m)", "element", "length", u"m", core=True),
        Field(K_HEIGHT, u"Height (m)", "element", "length", u"m", core=True),
        Field(K_LENGTH, u"Total Length (m)", "element", "length", u"m", aggregate="sum", core=True),
        Field(K_AREA, u"Area (%s)" % M2, "element", "area", M2, aggregate="sum", core=True),
        Field(K_COUNT, u"Count", "group", "integer", core=True),
        Field(K_ELEMENT_ID, u"Element Id", "element", "integer", core=True),
    ]


class Layer(object):
    """One layer of a compound structure (type level)."""

    def __init__(self, order, material_id, material, thickness, function):
        self.order = order                  # 1-based
        self.material_id = material_id      # int, or None for "no material"
        self.material = material            # name, u"None / Air" when there is no material
        self.thickness = thickness          # metres
        self.function = function            # text, e.g. u"Structure"

    def __repr__(self):
        return "Layer(%d, %r, %r)" % (self.order, self.material, self.thickness)


class TypeRecord(object):
    def __init__(self, type_id, values=None, layers=None, is_curtain=False):
        self.type_id = type_id
        self.values = values if values is not None else {}
        self.layers = layers                # None = no compound structure (stacked wall, door, ...)
        self.is_curtain = is_curtain

    @property
    def is_layered(self):
        return self.layers is not None

    def get(self, key, default=None):
        return self.values.get(key, default)

    def material_ids(self):
        """Distinct material ids of the layers, in layer order."""
        seen, out = set(), []
        for lay in (self.layers or []):
            if lay.material_id is not None and lay.material_id not in seen:
                seen.add(lay.material_id)
                out.append(lay.material_id)
        return out


class ElementRecord(object):
    def __init__(self, element_id, type_id, values=None, material_areas=None):
        self.element_id = element_id
        self.type_id = type_id
        self.values = values if values is not None else {}
        self.material_areas = material_areas if material_areas is not None else {}   # material id -> m2

    def get(self, key, default=None):
        return self.values.get(key, default)


class RecordSet(object):
    """Everything read from one category: field catalogue + types + elements."""

    def __init__(self, category_id, category_name):
        self.category_id = category_id
        self.category_name = category_name
        self.fields = []                    # catalogue, in discovery order (core fields first)
        self._fields = {}
        self.types = {}                     # type id -> TypeRecord
        self.elements = []                  # ElementRecord
        self.loaded_keys = set()            # field keys whose values are filled in
        self.notes = []                     # warnings from the reader

    # ---- catalogue
    def add_field(self, field):
        """Returns False (and ignores it) when the key is already in the catalogue."""
        if field.key in self._fields:
            return False
        self._fields[field.key] = field
        self.fields.append(field)
        return True

    def has_field(self, key):
        return key in self._fields

    def field(self, key):
        return self._fields.get(key)

    def display_labels(self):
        """key -> unique label. Clashes get a scope tag, then the parameter group, then the key:
        'Comments (type)', 'Spacing (type, Vertical Grid)'."""
        tags = {"element": u"instance", "type": u"type", "layer": u"layer", "group": u"calculated"}
        count = {}
        for f in self.fields:
            count[f.label] = count.get(f.label, 0) + 1
        step1 = {}
        for f in self.fields:
            step1[f.key] = f.label if count[f.label] == 1 else u"%s (%s)" % (f.label, tags[f.scope])
        count2 = {}
        for t in step1.values():
            count2[t] = count2.get(t, 0) + 1
        out, used = {}, set()
        for f in self.fields:
            t = step1[f.key]
            if count2[t] > 1 and f.group:
                t = u"%s (%s, %s)" % (f.label, tags[f.scope], f.group)
            if t in used:
                t = u"%s [%s]" % (t, f.key)
            used.add(t)
            out[f.key] = t
        return out

    # ---- data
    def add_type(self, tr):
        self.types[tr.type_id] = tr

    def add_element(self, er):
        self.elements.append(er)

    def type_of(self, er):
        return self.types[er.type_id]

    def value(self, er, key):
        """Value of an element- or type-scope field for one element."""
        f = self._fields.get(key)
        if f is not None and f.scope == "type":
            return self.types[er.type_id].values.get(key)
        if f is not None and f.scope == "element":
            return er.values.get(key)
        raise KeyError("%s is not an element or type field" % key)

    def elements_in_mode(self, curtain):
        """Walls: curtain walls only (True) or everything else (False). Other categories: use False."""
        return [e for e in self.elements if self.types[e.type_id].is_curtain == bool(curtain)]

    @property
    def has_layered(self):
        return any(t.is_layered for t in self.types.values())

    def summary_lines(self):
        n_curtain = sum(1 for e in self.elements if self.types[e.type_id].is_curtain)
        n_layered = sum(1 for t in self.types.values() if t.is_layered)
        lines = [u"%s: %d elements, %d types (%d layered), %d curtain-wall elements, %d fields in catalogue." % (
            self.category_name, len(self.elements), len(self.types), n_layered, n_curtain, len(self.fields))]
        for n in self.notes:
            lines.append(u"Note: %s" % n)
        return lines
