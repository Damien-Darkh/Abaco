# -*- coding: utf-8 -*-
"""Pipeline (Phase 2): records + settings -> table. Pure Python, no Revit imports.

Stages:
  0   check_calc_modes     unknown calculation modes are refused
  1   select_columns       settings.fields -> ColumnSpec list (unit and decimals resolved here)
  2   build_rows           records -> Rows (grouped or itemized, layers expanded), base units
  3   apply_varies         element values merged, or 'Varies', or a calculated value
  3b  apply_formulas       custom (formula) fields, per row, base units
  4   sort and blocks      levels -> blocks, base units
  5   footers and summary  total / min / max rows, base units
  6   format_cells         markers only (#NONE #ERROR #TRUE #FALSE)
  7   Table._line          base -> display unit. The only conversion point.

Values are base units (m, m2, m3, rad) everywhere except Table._line output.
The values of every field the settings use must be loaded first: revit_reader.ensure_values().
"""
import re

from abaco.records import (
    Field, K_TYPE_MARK, K_TYPE_NAME, K_FAMILY, K_LEVEL, K_WIDTH, K_HEIGHT, K_LENGTH, K_AREA, K_ELEMENT_ID,
    K_COUNT, K_LAYER_ORDER, K_LAYER_MATERIAL, K_LAYER_THICKNESS, K_LAYER_FUNCTION, K_LAYER_AREA, K_IS_CURTAIN)

from abaco import appearance as AP
from abaco import evaluate as EV
from abaco import filters
from abaco import formula as FM
from abaco import units as U

try:
    _STR = (basestring,)
except NameError:
    _STR = (str,)

_NUM = (int, float)
try:
    _NUM = _NUM + (type(2 ** 64),)      # long on Python 2 / IronPython 2.7
except Exception:
    pass

CALC_MODES = ("none", "total", "min", "max", "minmax")
DEFAULT_LABELS = {"varies": u"Varies", "total": u"Total", "min": u"Min", "max": u"Max",
                  "grand": u"Grand total", "no_layers": u"(no layers)", "summary": u"Summary"}

NUMERIC_KINDS = ("number", "integer", "length", "area", "volume", "angle", "currency")
ROW_DATA, ROW_TOTAL, ROW_MIN, ROW_MAX = "data", "total", "min", "max"
ROW_GTOTAL, ROW_GMIN, ROW_GMAX = "gtotal", "gmin", "gmax"
CALC_ROW_KINDS = (ROW_TOTAL, ROW_MIN, ROW_MAX, ROW_GTOTAL, ROW_GMIN, ROW_GMAX)
ROW_BLANK, ROW_HEADER = "blank", "header"
ROW_SUMHEAD = "sumhead"                 # "Summary" header row at the bottom of the table

_MARKERS = (u"#NONE", u"#ERROR", u"#TRUE", u"#FALSE")
_KIND_EL = {ROW_DATA: "data", ROW_HEADER: "header", ROW_SUMHEAD: "summaryHeader",
            ROW_TOTAL: "summary", ROW_MIN: "summary", ROW_MAX: "summary",
            ROW_GTOTAL: "summary", ROW_GMIN: "summary", ROW_GMAX: "summary"}


# ------------------------------------------------------------------------------------------- settings
def field_setting(key, **kw):
    d = {"key": key, "include": True, "heading": None, "tag": None,
         "unit": None, "decimals": None,
         "align": "left", "widthMm": None, "hiddenInRevit": False, "showInExcel": True,
         "calc": "none"}
    d.update(kw)
    return d


TABLE_TYPES = ("schedule", "takeoff")


def is_walls(rs):
    return rs.has_field(K_IS_CURTAIN)


def effective_type(rs, settings):
    """'takeoff' needs layered types (walls, floors, roofs, ceilings); otherwise it is a schedule."""
    if settings.get("tableType") == "takeoff" and rs.has_layered:
        return "takeoff"
    return "schedule"


def sort_setting(key, direction="asc", header=False, footer=False, gap=False, footer_calc="field"):
    return {"key": key, "dir": direction, "header": bool(header), "footer": bool(footer),
            "gap": bool(gap), "footerCalc": footer_calc}


def default_settings(rs, table_type="schedule", title=u"", custom=None):
    ttype = effective_type(rs, {"tableType": table_type})
    walls = is_walls(rs)
    if ttype == "takeoff":
        keys = [K_TYPE_MARK, K_TYPE_NAME, K_LAYER_ORDER, K_LAYER_MATERIAL, K_LAYER_THICKNESS,
                K_LAYER_FUNCTION, K_LAYER_AREA, K_AREA, K_LEVEL]
        group, sort = [K_LEVEL, K_TYPE_MARK], [K_TYPE_NAME]
    elif walls:
        keys = [K_TYPE_MARK, K_TYPE_NAME, K_COUNT, K_LENGTH, K_HEIGHT, K_AREA, K_LEVEL]
        group, sort = [K_LEVEL, K_TYPE_MARK], [K_TYPE_NAME, K_HEIGHT]
    elif rs.has_layered:                                   # floors, roofs, ceilings
        keys = [K_TYPE_MARK, K_TYPE_NAME, K_COUNT, K_AREA, K_LEVEL]
        group, sort = [K_LEVEL, K_TYPE_MARK], [K_TYPE_NAME]
    else:
        keys = [K_TYPE_MARK, K_FAMILY, K_TYPE_NAME, K_WIDTH, K_HEIGHT, K_COUNT, K_LEVEL]
        group, sort = [K_LEVEL, K_TYPE_MARK], [K_FAMILY, K_TYPE_NAME, K_WIDTH, K_HEIGHT]
    hidden = set()
    if ttype == "takeoff":
        hidden |= set([K_LAYER_ORDER, K_LAYER_FUNCTION])
    if walls:
        hidden.add(K_TYPE_NAME)
    fields = []
    for k in keys:
        extra = {}
        if k == K_AREA and ttype == "takeoff" and walls:
            extra["heading"] = u"Wall Area"                # bare name; the unit suffix is added at output
        fields.append(field_setting(k, hiddenInRevit=(k in hidden), **extra))
    levels = ([sort_setting(k, gap=True, footer=(i == len(group) - 1)) for i, k in enumerate(group)]
              + [sort_setting(k) for k in sort])
    return {"category": rs.category_id, "tableType": ttype, "title": title, "fields": fields,
            "levels": levels, "grandTotals": False, "itemize": False, "labels": dict(DEFAULT_LABELS),
            "appearance": AP.preset("bw"),
            "custom": [dict(d) for d in (custom or []) if isinstance(d, dict)]}


def required_keys(settings):
    keys = [f["key"] for f in settings.get("fields", [])]
    keys += [s["key"] for s in settings.get("levels", []) if s.get("key")]
    return keys


def check_calc_modes(settings):
    """Unknown calculation modes are refused, not ignored: a dropped footer is silently wrong."""
    bad = []
    for f in settings.get("fields", []):
        mode = f.get("calc") or "none"
        if mode not in CALC_MODES:
            bad.append(u"'%s' has unknown calculation '%s'" % (f.get("key"), mode))
    if bad:
        raise ValueError(u"; ".join(bad) + u". Allowed: " + u", ".join(CALC_MODES))


def _norm_heading(v):
    return re.sub(r"\s+", " ", _s(v) if v else u"").strip().lower()


def apply_hidden_headings(rs, settings, text):
    """Set hiddenInRevit from a ';' or ',' separated list (the v1 'hidden columns' box).
    A field matches by its heading override, its bare label, or its label with any allowed unit
    ('Width (m)'). Everything not listed is shown. Type Mark is never hidden."""
    wanted = set(_norm_heading(x) for x in re.split(r"[;,]", _s(text) if text else u"") if x.strip())
    for st in settings.get("fields", []):
        f = rs.field(st["key"])
        names = set([_norm_heading(st.get("heading"))])
        if f is not None:
            names.add(_norm_heading(f.label))
            if f.dim:
                for unit in U.allowed_units(f.dim):
                    names.add(_norm_heading(u"%s (%s)" % (f.label, unit)))
        names.discard(u"")
        st["hiddenInRevit"] = bool(wanted & names) and st["key"] != K_TYPE_MARK
    return settings


# ----------------------------------------------------------------------------------------------- model
def project_default(rs, dim):
    """(unit, decimals) of the project for a dimension: Revit's Project Units, else the metric defaults."""
    p = rs.project.get(dim)
    if p:
        return p
    return U.DEFAULT_UNIT.get(dim), U.DEFAULT_DECIMALS.get(dim)


class ColumnSpec(object):
    """One column. unit and decimals are resolved here: the field's override, else the project default.
    Non-dimensioned fields have unit None; their decimals come from the override (number kind: 3)."""

    def __init__(self, field, st, rs):
        self.key = field.key
        self.field = field
        self.dim = field.dim
        if self.dim:
            if field.scope == "formula":
                self.unit = st.get("unit") or field.base_unit          # unit the formula computes in
                _, p_dec = project_default(rs, self.dim)
            else:
                p_unit, p_dec = project_default(rs, self.dim)
                self.unit = st.get("unit") or p_unit
            self.decimals = st["decimals"] if st.get("decimals") is not None else p_dec
        else:
            self.unit = None
            if st.get("decimals") is not None:
                self.decimals = st["decimals"]
            else:
                self.decimals = 3 if field.kind == "number" else None
        self.prefix = self.unit if self.dim == "currency" else u""
        name = st.get("heading") or field.label
        self.heading = name + (u" (%s)" % st["tag"] if st.get("tag") else u"") + U.heading_suffix(self.dim, self.unit)
        self.align = st.get("align") or "left"
        self.width_mm = st.get("widthMm")
        self.hidden_in_revit = bool(st.get("hiddenInRevit"))
        self.show_in_excel = st.get("showInExcel", True)
        self.calc = st.get("calc") or "none"


class Row(object):
    def __init__(self, kind, cells, gid=0, lorder=0, els=None, label=None, members=None):
        self.kind = kind
        self.cells = cells          # field key -> base-unit value (None = empty)
        self.gid = gid
        self.lorder = lorder
        self.els = els or []
        self.label = label
        self.members = members or []


class Table(object):
    def __init__(self, title, columns, blocks, appearance=None):
        self.title = title
        self.columns = columns
        self.blocks = blocks                       # list of lists of Row, base units
        self.appearance = appearance or AP.preset("bw")

    def select(self, keep):
        return Table(self.title, [c for c in self.columns if keep(c)], self.blocks, self.appearance)

    def n_data_rows(self):
        return sum(1 for b in self.blocks for r in b if r.kind == ROW_DATA)

    def headings(self):
        mode = AP.case_of(self.appearance, "heading")
        return [AP.apply_case(c.heading, mode) for c in self.columns]

    def _line(self, r):
        """One output row. The only place base values become display values."""
        n = len(self.columns)
        app = self.appearance
        if r.kind in (ROW_HEADER, ROW_SUMHEAD):
            line = [u""] * n
            line[0] = AP.apply_case(r.label or u"", AP.case_of(app, _KIND_EL[r.kind]))
            return line
        mode = AP.case_of(app, _KIND_EL.get(r.kind, "data"))
        line = []
        for c in self.columns:
            v = r.cells.get(c.key)
            if v is None:
                v = u""
            elif c.dim and _is_num(v):
                v = U.to_display(v, c.dim, c.unit)
            elif AP.is_text(v) and v not in _MARKERS:
                v = AP.apply_case(v, mode)
            line.append(v)
        if r.kind in CALC_ROW_KINDS:              # label goes in the first column without a value
            label = AP.apply_case(r.label or u"", mode)
            for i, c in enumerate(self.columns):
                if r.cells.get(c.key) is None:
                    line[i] = label
                    break
            else:
                line[0] = label
        return line

    def rendered_blocks(self):
        return [[(r.kind, self._line(r)) for r in block] for block in self.blocks]

    def to_matrix(self):
        m = [[self.title] + [u""] * (len(self.columns) - 1), self.headings()]
        for block in self.rendered_blocks():
            for _, line in block:
                m.append(line)
        return m


class Result(object):
    def __init__(self, table, warnings):
        self.table = table                                              # every selected column
        self.warnings = warnings
        self.appearance = table.appearance
        self.excel = table.select(lambda c: bool(c.show_in_excel))       # stage 7
        self.revit = table.select(lambda c: not c.hidden_in_revit)


# --------------------------------------------------------------------------------------------- helpers
def _is_num(v):
    return isinstance(v, _NUM) and not isinstance(v, bool)


def _s(v):
    return v if isinstance(v, _STR) else u"%s" % v


def sort_value(v):
    """Empty first, numbers in numeric order, text case-insensitive.
    Formula values: NONE sorts with the empty cells, TRUE after FALSE, errors last."""
    if v is EV.NONE:
        return (0, 0, u"")
    if v is EV.VARIES:
        return (2, 1, u"")
    if isinstance(v, EV.Err):
        return (3, 0, u"")
    if isinstance(v, bool):
        return (1, int(v), u"")
    if v is None or v == u"":
        return (0, 0, u"")
    if _is_num(v):
        return (1, v, u"")
    return (2, 0, _s(v).lower())


def _r3(v):
    return None if v is None else round(v, 3)


def _same(a, b):
    if a is None or b is None:
        return a is None and b is None
    if _is_num(a) and _is_num(b):
        return abs(a - b) < 1e-6
    return a == b


def _merge(vals, varies):
    first = vals[0]
    for v in vals[1:]:
        if not _same(first, v):
            return varies
    return first


def _sum(vals):
    nums = [v for v in vals if _is_num(v)]
    return sum(nums) if nums else None


def _disp(v, col):
    """Base value -> display value for a column (numbers of dimensioned columns only)."""
    if col is not None and col.dim and _is_num(v):
        return U.to_display(v, col.dim, col.unit)
    return v


def _show(v, col):
    """Display text of one number in a column, with its decimals (used for range text)."""
    return U.format_text(_disp(v, col), col.decimals if col is not None else None,
                         col.prefix if col is not None else u"")


def _row_calc_value(els, key, mode, col):
    """The one value a merged cell shows when its column has a calculation."""
    nums = [v for v in (e.get(key) for e in els) if _is_num(v)]
    if not nums:
        return None
    if mode == "total":
        return sum(nums)
    if mode == "min":
        return min(nums)
    if mode == "max":
        return max(nums)
    lo, hi = min(nums), max(nums)                  # minmax
    if abs(hi - lo) < 1e-9:
        return lo
    return u"%s \u2013 %s" % (_show(lo, col), _show(hi, col))


# --------------------------------------------------------------------------------------------- stage 1
def select_columns(rs, settings, ttype=None):
    ttype = ttype or effective_type(rs, settings)
    cols, warns = [], []
    for st in settings.get("fields", []):
        if not st.get("include", True):
            continue
        f = rs.field(st["key"])
        if f is None:
            warns.append(u"Field '%s' not found in this project: skipped." % (st.get("heading") or st["key"]))
            continue
        if f.scope == "layer" and ttype != "takeoff":
            warns.append(u"'%s' is a layer field, only available in a Material takeoff: skipped." % f.label)
            continue
        cols.append(ColumnSpec(f, _fill(st), rs))
    if settings.get("itemize") and not any(c.key == K_ELEMENT_ID for c in cols):
        f = rs.field(K_ELEMENT_ID)
        if f is not None:
            cols.insert(0, ColumnSpec(f, field_setting(K_ELEMENT_ID), rs))
    if not cols:
        raise ValueError("No fields selected.")
    return cols, warns


def _fill(st):
    d = field_setting(st["key"])
    d.update(st)
    return d


# --------------------------------------------------------------------------------------------- stage 2
def _group_key(rs, e, itemize, idx, split):
    if itemize:
        return idx
    tr = rs.types[e.type_id]
    if tr.is_curtain:
        wh = (None, _r3(e.get(K_HEIGHT)))
    elif tr.is_layered:
        wh = (None, None)
    else:
        wh = (_r3(e.get(K_WIDTH)), _r3(e.get(K_HEIGHT)))
    return (e.type_id, e.get(K_LEVEL), wh[0], wh[1]) + tuple(_r3(e.get(k)) if _is_num(e.get(k)) else e.get(k)
                                                              for k in split)


def build_rows(rs, settings, keys, ttype, labels, split=()):
    itemize = bool(settings.get("itemize"))
    groups, order = {}, []
    for i, e in enumerate(rs.elements):
        k = _group_key(rs, e, itemize, i, split)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(e)

    fields = [(k, rs.field(k)) for k in keys]
    fields = [(k, f) for k, f in fields if f is not None]
    expanded = (ttype == "takeoff") and any(f.scope == "layer" for k, f in fields)

    rows = []
    for gid, k in enumerate(order):
        ges = groups[k]
        tr = rs.types[ges[0].type_id]
        layers = list(tr.layers) if (expanded and tr.is_layered) else [None]
        for lay in layers:
            cells = {}
            for key, f in fields:
                if f.scope == "type":
                    cells[key] = tr.get(key)
                elif f.scope == "group":
                    cells[key] = len(ges)
                elif f.scope == "layer":
                    cells[key] = _layer_cell(key, lay, ges, labels)
                elif f.aggregate == "sum":
                    cells[key] = _sum([e.get(key) for e in ges])
                elif key == K_LEVEL:
                    cells[key] = ges[0].get(K_LEVEL) or None
                elif key == K_WIDTH and not itemize and not tr.is_curtain and not tr.is_layered:
                    cells[key] = ges[0].get(K_WIDTH)
                elif key == K_HEIGHT and not itemize and (tr.is_curtain or not tr.is_layered):
                    cells[key] = ges[0].get(K_HEIGHT)
            rows.append(Row(ROW_DATA, cells, gid, lay.order if lay is not None else 0, ges))
    return rows, expanded


def _layer_cell(key, lay, ges, labels):
    if lay is None:
        return labels["no_layers"] if key == K_LAYER_MATERIAL else None
    if key == K_LAYER_ORDER:
        return lay.order
    if key == K_LAYER_MATERIAL:
        return lay.material
    if key == K_LAYER_THICKNESS:
        return lay.thickness
    if key == K_LAYER_FUNCTION:
        return lay.function
    if key == K_LAYER_AREA:
        if lay.material_id is None:
            return None
        return _sum([e.material_areas[lay.material_id] for e in ges if lay.material_id in e.material_areas])
    return None


# --------------------------------------------------------------------------------------------- stage 3
def apply_varies(rs, rows, keys, itemize, labels, cols):
    """Element-scope values left open by stage 2. A column with a calculation shows the calculated value
    of its elements; otherwise one value per row, or 'Varies' when the elements differ."""
    colmap = dict((c.key, c) for c in cols)
    todo = [k for k in keys if rs.field(k) is not None and rs.field(k).scope == "element"]
    cache = {}
    for r in rows:
        for k in todo:
            mode = colmap[k].calc if k in colmap else "none"
            if mode != "none":
                ck = (r.gid, k, mode)
                if ck not in cache:
                    cache[ck] = _row_calc_value(r.els, k, mode, colmap.get(k))
                r.cells[k] = cache[ck]
            elif k not in r.cells:
                ck = (r.gid, k)
                if ck not in cache:
                    vals = [(e.element_id if k == K_ELEMENT_ID else e.get(k)) for e in r.els]
                    cache[ck] = vals[0] if itemize else _merge(vals, labels["varies"])
                r.cells[k] = cache[ck]
    return rows


# --------------------------------------------------------------------------------------------- stage 4
def _gap_sig(r, key):
    """Value that decides a new block. A blank Type Mark counts as its own type (v1: types without a mark
    are separated by name); a shared Type Mark keeps its types in one block."""
    v = r.cells.get(key)
    if key == K_TYPE_MARK and (v is None or v == u"") and r.els:
        return ("type", r.els[0].type_id)
    return sort_value(v)


def _lv(r, lv):
    if lv.get("_gid"):
        return r.gid
    return _gap_sig(r, lv["key"])


def _segments(rows, lv):
    """Consecutive runs of rows with the same value of one level (rows are already sorted)."""
    segs, prev = [], None
    for r in rows:
        v = _lv(r, lv)
        if not segs or v != prev:
            segs.append([])
            prev = v
        segs[-1].append(r)
    return segs


def _sort_rows(rows, levels):
    rows = sorted(rows, key=lambda r: (r.gid, r.lorder))     # fixed: element order, then layer order
    for s in reversed(levels):                                 # last level first: stable sorts stack up
        if s.get("key") is None:
            continue
        k = s["key"]
        rows = sorted(rows, key=lambda r, k=k: sort_value(r.cells.get(k)), reverse=(s.get("dir") == "desc"))
    return rows


def _header_text(r, lv, cols=(), labels=None):
    v = r.cells.get(lv["key"])
    if v is EV.NONE or v is EV.VARIES or isinstance(v, (EV.Err, bool)):
        return EV.to_cell(v, (labels or {}).get("varies", u"Varies"))
    col = None
    for c in cols:
        if c.key == lv["key"]:
            col = c
            break
    if col is not None and col.dim and _is_num(v):
        return U.format_text(_disp(v, col), col.decimals, col.prefix)
    if isinstance(v, float):
        return u"%s" % format(v, ".15g")
    return u"(none)" if v is None or v == u"" else u"%s" % v


def _footer(seg, cols, labels, mode):
    out = _calc_rows(seg, cols, False, labels, override=mode)
    for x in out:
        x.members = seg
    return out


def _collapse_gaps(items):
    """Two gap rows in a row (a child gap and its parent's gap at the same boundary) become one."""
    out = []
    for r in items:
        if r.kind == ROW_BLANK and out and out[-1].kind == ROW_BLANK:
            continue
        out.append(r)
    return out


def _seg_items(seg, levels, i, cols, labels):
    """Rows of one segment of level i, in Revit order: header, children, footer, gap."""
    lv = levels[i]
    out = []
    if lv.get("header"):
        out.append(Row(ROW_HEADER, {}, label=_header_text(seg[0], lv, cols, labels)))
    if i + 1 < len(levels):
        for sub in _segments(seg, levels[i + 1]):
            out.extend(_seg_items(sub, levels, i + 1, cols, labels))
    else:
        out.extend(seg)
    if lv.get("footer"):
        out.extend(_footer(seg, cols, labels, lv.get("footerCalc") or "field"))
    if lv.get("gap"):
        out.append(Row(ROW_BLANK, {}))
    return out


# --------------------------------------------------------------------------------------------- stage 5
def _values_for(rows, c):
    """The values a footer adds up, each element and each group counted once."""
    scope = c.field.scope if c.field is not None else None
    if scope == "element":
        seen, out = set(), []
        for r in rows:
            for e in r.els:
                if e.element_id not in seen:
                    seen.add(e.element_id)
                    out.append(e.get(c.key))
        return out
    if scope == "layer" or getattr(c.field, "per_row", False):
        return [r.cells.get(c.key) for r in rows]
    seen, out = set(), []
    for r in rows:
        if r.gid not in seen:
            seen.add(r.gid)
            out.append(r.cells.get(c.key))
    return out


def _calc_rows(rows, cols, grand, labels, override=None):
    """Total / min / max rows for `rows`, in base units. override: footer mode of one level
    (None or 'field' = each field's own Calculation)."""
    sums, mins, maxs = {}, {}, {}
    for c in cols:
        mode = c.calc if override in (None, "field") else override
        if mode == "none":
            continue
        nums = [v for v in _values_for(rows, c) if _is_num(v)]
        if not nums:
            continue
        if mode == "total":
            sums[c.key] = sum(nums)
        if mode in ("min", "minmax"):
            mins[c.key] = min(nums)
        if mode in ("max", "minmax"):
            maxs[c.key] = max(nums)
    out = []
    spec = ((sums, ROW_GTOTAL if grand else ROW_TOTAL, "total"),
            (mins, ROW_GMIN if grand else ROW_MIN, "min"),
            (maxs, ROW_GMAX if grand else ROW_MAX, "max"))
    for cells, kind, name in spec:
        if cells:
            out.append(Row(kind, cells, label=labels[name]))
    return out


def build_blocks(rows, levels, cols, labels, itemize, expanded, grand):
    levels = list(levels)
    if itemize and expanded:           # one block per element, its layers repeated
        levels.insert(0, {"key": None, "_gid": True, "header": False, "footer": False, "gap": False})
    rows = _sort_rows(rows, levels)
    if levels:
        blocks = [_collapse_gaps(_seg_items(seg, levels, 0, cols, labels))
                  for seg in _segments(rows, levels[0])]
    else:
        blocks = [list(rows)] if rows else []
    if blocks and blocks[-1] and blocks[-1][-1].kind == ROW_BLANK:    # no gap after the last block
        blocks[-1] = blocks[-1][:-1]
    if grand and any(c.calc != "none" for c in cols):
        g = _calc_rows(rows, cols, True, labels)
        for x in g:
            x.members = rows
        if g:
            if blocks:
                blocks[-1].append(Row(ROW_BLANK, {}))      # blank line between the data and the summary
            blocks.append([Row(ROW_SUMHEAD, {}, label=labels["summary"])] + g)
    return blocks


# --------------------------------------------------------------------------------------------- stage 6
def format_cells(blocks, labels=None):
    """Formula markers only. Numbers stay at full precision: rounding and units happen at output."""
    varies = (labels or {}).get("varies", u"Varies")
    for b in blocks:
        for r in b:
            for k, v in list(r.cells.items()):
                if v is EV.NONE or v is EV.VARIES or isinstance(v, (EV.Err, bool)):
                    r.cells[k] = EV.to_cell(v, varies)
    return blocks


# ------------------------------------------------------------------------------------ custom fields
class Custom(object):
    """One custom (formula) field of the table settings, parsed and checked."""

    def __init__(self, key, name, text):
        self.key, self.name, self.text = key, name, text
        self.ast = None
        self.ty = None
        self.refs = set()           # field keys the checked formula uses
        self.names = set()          # every {name} written in the formula (before checking)
        self.deps = set()           # the custom fields among them
        self.broken = None          # message when the formula cannot be calculated at all
        self.reason = FM.R_SYNTAX
        self.per_row = False


def _walk_fields(node, out):
    if node.kind == u"field":
        out.add(node.key)
    for attr in (u"left", u"right", u"arg"):
        child = getattr(node, attr, None)
        if child is not None:
            _walk_fields(child, out)
    for child in getattr(node, u"args", None) or []:
        _walk_fields(child, out)


def attach_custom(rs, settings):
    """Put the custom fields of settings["custom"] into the catalogue, with the type of their formula.

    Definitions: {"key": u"calc:1", "name": u"Wall volume", "formula": u"{@AREA} * {@HEIGHT}"}, formula in
    stored form. Safe to call on every rebuild. The dimension (length, area, volume or none) comes from the
    formula's result kind, through Field, so the Formatting tab offers units only where they apply.

    Returns (customs {key: Custom}, order [keys, dependencies first], warnings).
    A formula that cannot be calculated is kept as a text field whose cells show #ERROR.
    """
    defs = {}
    for d in settings.get("custom") or []:
        if isinstance(d, dict) and d.get("key"):
            defs[d["key"]] = d

    for f in list(rs.fields):
        if f.scope == "formula" and f.key not in defs:
            rs.remove_field(f.key)

    # 1. parse every definition; the custom fields it names are its dependencies
    customs, warns = {}, []
    for key, d in defs.items():
        c = Custom(key, d.get("name") or key, d.get("formula") or u"")
        try:
            c.ast = FM.parse(c.text)
            _walk_fields(c.ast, c.names)
        except FM.FormulaError as ex:
            c.broken, c.reason = ex.message, ex.reason
        c.deps = set(n for n in c.names if n in defs)
        customs[key] = c

    # 2. order the fields; a circular reference breaks only the fields in the loop
    cut = dict((k, set(c.deps)) for k, c in customs.items())
    while True:
        try:
            order = EV.topological_order(cut, rs.display_labels())
            break
        except FM.FormulaError as ex:
            loop = getattr(ex, "loop", None)
            if not loop:
                raise
            for k in loop:
                customs[k].broken, customs[k].reason = ex.message, FM.R_REF
                cut[k] = set()

    # 3. check each formula in dependency order, so its custom references already have their types
    for key in order:
        c = customs[key]
        if c.broken is None:
            chk = FM.check(c.text, rs.fields, rs.display_labels())
            c.refs = set(chk.refs)
            if chk.errors:
                c.broken, c.reason = chk.errors[0].message, chk.errors[0].reason
            else:
                c.ty = chk.ty
        else:
            c.refs = set(n for n in c.names if rs.field(n) is not None)

        if c.broken is not None:
            warns.append(u"Custom field '%s' cannot be calculated: %s" % (c.name, c.broken))
            kind, result = u"text", None
        else:
            kind, _unit_text = FM.field_kind(c.ty)
            result = (c.ty.kind, c.ty.exp, c.ty.count)

        c.per_row = any(
            (rs.field(r) is not None and rs.field(r).scope == "layer") or
            (r in customs and customs[r].per_row)
            for r in c.refs)

        f = Field(key, c.name, "formula", kind, result=result, formula=c.text)
        f.per_row = c.per_row
        rs.replace_field(f)

    return customs, order, warns


def _needed(cols, customs):
    """Custom fields to calculate: the ones in the table, and every custom field they use."""
    need = set(c.key for c in cols if c.key in customs)
    todo = list(need)
    while todo:
        for d in customs[todo.pop()].deps:
            if d in customs and d not in need:
                need.add(d)
                todo.append(d)
    return need


def apply_formulas(rs, rows, customs, order, labels):
    """Stage 3b: evaluate the custom fields for every row, in dependency order, in base units.
    A 'Varies' (or range) cell has no single value: the formula reads it as NONE.
    Broken formulas are reported once, by attach_custom. Returns warnings for row errors only."""
    warns = []
    if not order:
        return warns
    kinds = dict((f.key, f.kind) for f in rs.fields)
    scopes = dict((f.key, f.scope) for f in rs.fields)
    varies = labels["varies"]
    stats = dict((k, {"n": 0, "err": 0, "reasons": {}, "example": None}) for k in order)
    for r in rows:
        cells = r.cells

        def get(key, cells=cells):
            if key not in cells:
                raise KeyError(key)                        # not a field of the table: #ERROR, reason ref
            v = cells[key]
            if isinstance(v, _STR) and (kinds.get(key) in NUMERIC_KINDS or
                                        (scopes.get(key) == "element" and v == varies)):
                return EV.VARIES                           # 'Varies' or a 'min – max' text: no single value
            return v

        done = {}
        for k in order:
            c = customs[k]
            v = EV.Err(c.reason, c.broken) if c.broken else EV.evaluate(c.ast, get, kinds.get, done)
            done[k] = v
            s = stats[k]
            s["n"] += 1
            if isinstance(v, EV.Err):
                s["err"] += 1
                s["reasons"][v.reason] = s["reasons"].get(v.reason, 0) + 1
                if s["example"] is None:
                    s["example"] = v.message
        cells.update(done)
    for k in order:
        s = stats[k]
        if s["err"] and not customs[k].broken:
            reasons = u", ".join(u"%s: %d" % (a, s["reasons"][a]) for a in sorted(s["reasons"]))
            warns.append(u"Custom field '%s': %d of %d rows give #ERROR (%s). First: %s" % (
                customs[k].name, s["err"], s["n"], reasons, s["example"]))
    return warns


# ------------------------------------------------------------------------------------ the pipeline
def _levels(rs, items, ttype, what, warns, allowed):
    out = []
    for s in items:
        f = rs.field(s["key"])
        if f is None:
            warns.append(u"%s field '%s' not found in this project: skipped." % (what, s["key"]))
        elif s["key"] not in allowed:
            warns.append(u"%s field '%s' is not in the Fields tab: skipped." % (what, f.label))
        elif f.scope == "layer" and ttype != "takeoff":
            warns.append(u"%s field '%s' needs a Material takeoff: skipped." % (what, f.label))
        else:
            out.append(s)
    return out


def build_table(rs, settings):
    check_calc_modes(settings)
    labels = dict(DEFAULT_LABELS)
    labels.update(settings.get("labels") or {})
    itemize = bool(settings.get("itemize"))
    ttype = effective_type(rs, settings)
    appearance = AP.normalize(settings.get("appearance"))

    customs, c_order, c_warns = attach_custom(rs, settings)      # custom fields into the catalogue first
    cols, warns = select_columns(rs, settings, ttype)
    if settings.get("tableType") == "takeoff" and ttype != "takeoff":
        warns.insert(0, u"Material takeoff needs layered types: showing a schedule instead.")
    allowed = set(c.key for c in cols)                    # Sort & group only use fields of the Fields tab
    levels = _levels(rs, settings.get("levels") or [], ttype, u"Level", warns, allowed)

    keys = [c.key for c in cols]
    need = _needed(cols, customs)
    f_order = [k for k in c_order if k in need]
    listed = set(st["key"] for st in settings.get("fields", []))
    for k in f_order:                                     # fields a formula reads must be in the cells
        for ref in sorted(customs[k].refs):
            f = rs.field(ref)
            if (ref in listed and ref not in keys and f is not None and f.scope != "formula"
                    and (f.scope != "layer" or ttype == "takeoff")):
                keys.append(ref)
    split = [s["key"] for s in levels if rs.field(s["key"]).scope == "element"]

    rows, expanded = build_rows(rs, settings, keys, ttype, labels, split)
    rows = apply_varies(rs, rows, keys, itemize, labels, cols)
    warns = warns + c_warns + apply_formulas(rs, rows, customs, f_order, labels)
    rows = filters.apply_row_filters(rs, rows, settings.get("filter"), set(c.key for c in cols))
    blocks = build_blocks(rows, levels, cols, labels, itemize, expanded, bool(settings.get("grandTotals")))
    blocks = format_cells(blocks, labels)

    if itemize and expanded and len(rows) > 500:
        warns.append(u"Itemized layered table: %d rows." % len(rows))
    title = settings.get("title")
    title = title if (title and _s(title).strip()) else (u"Abaco " + rs.category_name).strip()
    return Result(Table(title, cols, blocks, appearance), warns)