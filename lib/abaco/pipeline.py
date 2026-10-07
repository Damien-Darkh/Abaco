# -*- coding: utf-8 -*-
"""Phase 2 pipeline: RecordSet + settings -> table. Pure Python, no Revit imports.

Stages (each one a plain function, tested on its own):
  1 select_columns     settings.fields            -> ordered ColumnSpec list
  2 build_rows         records                    -> Rows (grouped or itemized, layers expanded)
  3 apply_varies       grouped rows               -> element values merged, or the word "Varies"
  4 sort_and_block     rows, settings.sort        -> blocks (a new block where a gap-flagged key changes)
  5 add_calculations   blocks                     -> + total / min / max rows, optional grand totals
  6 format_cells       blocks                     -> numbers rounded per column
  7 split outputs      Table                      -> excel_table / revit_table (column subsets)

Default settings per template (layered / curtain / simple) reproduce the v1 table row for row.
The values of every field the settings use must be loaded first: revit_reader.ensure_values(doc, rs,
required_keys(settings)).
"""
import re

from abaco.records import (
    K_TYPE_MARK, K_TYPE_NAME, K_FAMILY, K_LEVEL, K_WIDTH, K_HEIGHT, K_LENGTH, K_AREA, K_ELEMENT_ID, K_COUNT,
    K_LAYER_ORDER, K_LAYER_MATERIAL, K_LAYER_THICKNESS, K_LAYER_FUNCTION, K_LAYER_AREA)

try:
    _STR = (basestring,)
except NameError:
    _STR = (str,)
try:
    _NUM = (int, long, float)
except NameError:
    _NUM = (int, float)

CALC_MODES = ("none", "total", "min", "max", "minmax")
DEFAULT_LABELS = {"varies": u"Varies", "total": u"Total", "min": u"Min", "max": u"Max",
                  "grand": u"Grand total", "no_layers": u"(no layers)"}

# decimals that reproduce v1; other fields fall back on the kind
_KEY_DECIMALS = {K_LAYER_THICKNESS: 4, K_WIDTH: 3, K_HEIGHT: 3, K_LENGTH: 2, K_AREA: 2, K_LAYER_AREA: 2}
_KIND_DECIMALS = {"length": 3, "area": 2, "volume": 3, "number": 3}

ROW_DATA, ROW_TOTAL, ROW_MIN, ROW_MAX = "data", "total", "min", "max"
ROW_GTOTAL, ROW_GMIN, ROW_GMAX = "gtotal", "gmin", "gmax"
CALC_ROW_KINDS = (ROW_TOTAL, ROW_MIN, ROW_MAX, ROW_GTOTAL, ROW_GMIN, ROW_GMAX)


# ------------------------------------------------------------------------------------------- settings
def field_setting(key, **kw):
    d = {"key": key, "include": True, "heading": None, "align": "left", "orientation": "horizontal",
         "widthMm": None, "hiddenInRevit": False, "showInExcel": True, "calc": "none", "decimals": None}
    d.update(kw)
    return d


def sort_setting(key, direction="asc", gap=False):
    return {"key": key, "dir": direction, "gap": gap}


def detect_shape(rs, mode):
    """'curtain' | 'layered' | 'simple' - same decision as v1 (any layered type makes the table layered)."""
    if mode == "curtain":
        return "curtain"
    for e in rs.elements_in_mode(False):
        if rs.types[e.type_id].is_layered:
            return "layered"
    return "simple"


def default_settings(rs, mode="standard", title=u""):
    """Template defaults = the v1 table (fields, sort, blocks, columns hidden in Revit)."""
    shape = detect_shape(rs, mode)
    if shape == "layered":
        keys = [K_TYPE_MARK, K_TYPE_NAME, K_LAYER_ORDER, K_LAYER_MATERIAL, K_LAYER_THICKNESS,
                K_LAYER_FUNCTION, K_LAYER_AREA, K_AREA, K_LEVEL]       # K_AREA = "Wall Area" of the group
        sort = [sort_setting(K_LEVEL, gap=True), sort_setting(K_TYPE_MARK, gap=True),
                sort_setting(K_TYPE_NAME)]
    elif shape == "curtain":
        keys = [K_TYPE_MARK, K_TYPE_NAME, K_COUNT, K_LENGTH, K_HEIGHT, K_AREA, K_LEVEL]
        sort = [sort_setting(K_LEVEL, gap=True), sort_setting(K_TYPE_MARK, gap=True),
                sort_setting(K_TYPE_NAME), sort_setting(K_HEIGHT)]
    else:
        keys = [K_TYPE_MARK, K_FAMILY, K_TYPE_NAME, K_WIDTH, K_HEIGHT, K_COUNT, K_LEVEL]
        sort = [sort_setting(K_LEVEL, gap=True), sort_setting(K_TYPE_MARK, gap=True),
                sort_setting(K_FAMILY), sort_setting(K_TYPE_NAME),
                sort_setting(K_WIDTH), sort_setting(K_HEIGHT)]
    hidden = set([K_LAYER_ORDER, K_LAYER_FUNCTION])          # v1 default: "Wall Type Name;Order;Function"
    f = rs.field(K_TYPE_NAME)
    if f is not None and f.label == u"Wall Type Name":
        hidden.add(K_TYPE_NAME)
    is_walls = f is not None and f.label == u"Wall Type Name"
    fields = []
    for k in keys:
        extra = {}
        if k == K_AREA and shape == "layered" and is_walls:
            extra["heading"] = u"Wall Area (m\u00b2)"                # v1 heading
        fields.append(field_setting(k, hiddenInRevit=(k in hidden), **extra))
    return {"category": rs.category_id, "mode": mode, "title": title,
            "fields": fields,
            "sort": sort, "itemize": False, "grandTotals": False, "labels": dict(DEFAULT_LABELS)}


def required_keys(settings):
    """Field keys whose values must be loaded (revit_reader.ensure_values) before building."""
    keys = [f["key"] for f in settings.get("fields", [])]
    keys += [s["key"] for s in settings.get("sort", [])]
    return keys


def _norm_heading(v):
    return re.sub(r"\s+", " ", _s(v) if v else u"").strip().lower()


def apply_hidden_headings(rs, settings, text):
    """Set hiddenInRevit from a ';' or ',' separated list of headings (the v1 'hidden columns' box).
    A field matches by its heading in the settings or by its catalogue label, case-insensitive.
    Everything not listed is shown. Type Mark is never hidden."""
    wanted = set(_norm_heading(x) for x in re.split(r"[;,]", _s(text) if text else u"") if x.strip())
    for st in settings.get("fields", []):
        f = rs.field(st["key"])
        names = set([_norm_heading(st.get("heading"))])
        if f is not None:
            names.add(_norm_heading(f.label))
        names.discard(u"")
        st["hiddenInRevit"] = bool(wanted & names) and st["key"] != K_TYPE_MARK
    return settings


# ----------------------------------------------------------------------------------------------- model
class ColumnSpec(object):
    def __init__(self, field, st):
        self.key = field.key
        self.field = field
        self.heading = st.get("heading") or field.label
        self.align = st.get("align") or "left"
        self.orientation = st.get("orientation") or "horizontal"
        self.width_mm = st.get("widthMm")
        self.hidden_in_revit = bool(st.get("hiddenInRevit"))
        self.show_in_excel = st.get("showInExcel", True)
        self.calc = st.get("calc") or "none"
        dec = st.get("decimals")
        if dec is None:
            dec = _KEY_DECIMALS.get(field.key, _KIND_DECIMALS.get(field.kind))
        self.decimals = dec


class Row(object):
    def __init__(self, kind, cells, gid=0, lorder=0, els=None, label=None):
        self.kind = kind
        self.cells = cells          # field key -> value (None = empty)
        self.gid = gid              # group (or element, when itemized) sequence number
        self.lorder = lorder        # layer order, the last implicit sort key
        self.els = els or []        # ElementRecords behind this row (data rows)
        self.label = label          # text for total/min/max rows


class Table(object):
    def __init__(self, title, columns, blocks):
        self.title = title
        self.columns = columns
        self.blocks = blocks        # list of lists of Row

    def select(self, keep):
        """Same rows, only the columns for which keep(column) is true (hidden / Excel split)."""
        return Table(self.title, [c for c in self.columns if keep(c)], self.blocks)

    def n_data_rows(self):
        return sum(1 for b in self.blocks for r in b if r.kind == ROW_DATA)

    def _label_index(self):
        """Column that carries the 'Total' / 'Min' / 'Max' label: the first one without a calculation."""
        calc_keys = set(c.key for c in self.columns if c.calc != "none")
        for i, c in enumerate(self.columns):
            if c.key not in calc_keys:
                return i
        return None

    def _line(self, r, label_idx):
        line = [(u"" if r.cells.get(c.key) is None else r.cells.get(c.key)) for c in self.columns]
        if r.kind in CALC_ROW_KINDS and label_idx is not None:
            line[label_idx] = r.label or u""
        return line

    def rendered_blocks(self):
        """Blocks of (row kind, [cell per column]) with the total labels already in place.
        Used by the Revit layout (and so by the preview). None -> u''."""
        li = self._label_index()
        return [[(r.kind, self._line(r, li)) for r in block] for block in self.blocks]

    def to_matrix(self):
        """v1 layout: title row, heading row, blocks separated by one blank row. None -> u''."""
        n = len(self.columns)
        li = self._label_index()
        m = [[self.title] + [u""] * (n - 1), [c.heading for c in self.columns]]
        for bi, block in enumerate(self.blocks):
            if bi:
                m.append([u""] * n)
            for r in block:
                m.append(self._line(r, li))
        return m


class Result(object):
    def __init__(self, table, warnings):
        self.table = table                                              # every selected column
        self.warnings = warnings
        self.excel = table.select(lambda c: bool(c.show_in_excel))       # stage 7
        self.revit = table.select(lambda c: not c.hidden_in_revit)


# --------------------------------------------------------------------------------------------- helpers
def _is_num(v):
    return isinstance(v, _NUM) and not isinstance(v, bool)


def _s(v):
    return v if isinstance(v, _STR) else u"%s" % v


def sort_value(v):
    """Empty first, numbers in numeric order, text case-insensitive (same as v1)."""
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


# --------------------------------------------------------------------------------------------- stage 1
def select_columns(rs, settings):
    """Included fields in settings order. Itemize adds Element Id as first column. -> (columns, warnings)."""
    cols, warns = [], []
    for st in settings.get("fields", []):
        if not st.get("include", True):
            continue
        f = rs.field(st["key"])
        if f is None:
            warns.append(u"Field '%s' not found in this project: skipped." % (st.get("heading") or st["key"]))
            continue
        cols.append(ColumnSpec(f, _fill(st)))
    if settings.get("itemize") and not any(c.key == K_ELEMENT_ID for c in cols):
        f = rs.field(K_ELEMENT_ID)
        if f is not None:
            cols.insert(0, ColumnSpec(f, field_setting(K_ELEMENT_ID)))
    if not cols:
        raise ValueError("No fields selected.")
    return cols, warns


def _fill(st):
    d = field_setting(st["key"])
    d.update(st)
    return d


# --------------------------------------------------------------------------------------------- stage 2
def _group_key(rs, e, curtain, itemize, idx):
    if itemize:
        return idx
    tr = rs.types[e.type_id]
    if curtain:
        wh = (None, _r3(e.get(K_HEIGHT)))
    elif tr.is_layered:
        wh = (None, None)
    else:
        wh = (_r3(e.get(K_WIDTH)), _r3(e.get(K_HEIGHT)))
    return (e.type_id, e.get(K_LEVEL), wh[0], wh[1])


def build_rows(rs, settings, keys, shape, labels):
    """records -> rows. Returns (rows, expanded). Only invariant values are filled here; element-scope
    values that can differ inside a group are left empty for stage 3."""
    curtain = (settings.get("mode") == "curtain")
    itemize = bool(settings.get("itemize"))
    els = rs.elements_in_mode(curtain)

    groups, order = {}, []
    for i, e in enumerate(els):
        k = _group_key(rs, e, curtain, itemize, i)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(e)

    fields = [(k, rs.field(k)) for k in keys]
    fields = [(k, f) for k, f in fields if f is not None]
    expanded = any(f.scope == "layer" for k, f in fields)

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
                    cells[key] = _layer_cell(key, lay, ges, shape, labels)
                elif f.aggregate == "sum":
                    cells[key] = _sum([e.get(key) for e in ges])
                elif key == K_LEVEL:
                    cells[key] = ges[0].get(K_LEVEL) or None
                elif key == K_WIDTH and not itemize and not curtain and not tr.is_layered:
                    cells[key] = _r3(ges[0].get(K_WIDTH))
                elif key == K_HEIGHT and not itemize and (curtain or not tr.is_layered):
                    cells[key] = _r3(ges[0].get(K_HEIGHT))
            rows.append(Row(ROW_DATA, cells, gid, lay.order if lay is not None else 0, ges))
    return rows, expanded


def _layer_cell(key, lay, ges, shape, labels):
    if lay is None:
        if key == K_LAYER_MATERIAL and shape == "layered":
            return labels["no_layers"]           # stacked walls etc.
        return None
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
def apply_varies(rs, rows, keys, itemize, labels):
    """Element-scope values left open by stage 2: one value per row, or 'Varies' when the elements differ."""
    cache = {}
    todo = []
    for k in keys:
        f = rs.field(k)
        if f is not None and f.scope == "element":
            todo.append(k)
    for r in rows:
        for k in todo:
            if k in r.cells:
                continue
            ck = (r.gid, k)
            if ck not in cache:
                vals = [(e.element_id if k == K_ELEMENT_ID else e.get(k)) for e in r.els]
                cache[ck] = vals[0] if itemize else _merge(vals, labels["varies"])
            r.cells[k] = cache[ck]
    return rows


# --------------------------------------------------------------------------------------------- stage 4
def _gap_sig(r, key):
    """Value that decides a new block. A blank Type Mark counts as 'this type' (v1: types without a mark
    are separated by name), a shared Type Mark keeps its types in one block."""
    v = r.cells.get(key)
    if key == K_TYPE_MARK and (v is None or v == u"") and r.els:
        return ("type", r.els[0].type_id)
    return sort_value(v)


def sort_and_block(rows, sort, itemize, expanded):
    """Multi-level sort (stable, asc/desc), then blocks. Implicit last keys: group, layer order."""
    rows = list(rows)
    rows.sort(key=lambda r: (r.gid, r.lorder))
    for s in reversed(sort):
        k = s["key"]
        rows.sort(key=lambda r, k=k: sort_value(r.cells.get(k)), reverse=(s.get("dir") == "desc"))
    gap_keys = [s["key"] for s in sort if s.get("gap")]
    blocks, cur, prev = [], [], None
    for r in rows:
        sig = [_gap_sig(r, k) for k in gap_keys]
        if itemize and expanded:
            sig.append(r.gid)                     # one block per element, repeating its layers
        if prev is not None and sig != prev and cur:
            blocks.append(cur)
            cur = []
        cur.append(r)
        prev = sig
    if cur:
        blocks.append(cur)
    return blocks


# --------------------------------------------------------------------------------------------- stage 5
def _calc_rows(data_rows, cols, grand, labels):
    sums, mins, maxs = {}, {}, {}
    for c in cols:
        if c.calc == "none":
            continue
        nums = [r.cells.get(c.key) for r in data_rows if _is_num(r.cells.get(c.key))]
        if not nums:
            continue
        if c.calc == "total":
            sums[c.key] = sum(nums)
        if c.calc in ("min", "minmax"):
            mins[c.key] = min(nums)
        if c.calc in ("max", "minmax"):
            maxs[c.key] = max(nums)
    out = []
    spec = ((sums, ROW_GTOTAL if grand else ROW_TOTAL, "total"),
            (mins, ROW_GMIN if grand else ROW_MIN, "min"),
            (maxs, ROW_GMAX if grand else ROW_MAX, "max"))
    for cells, kind, name in spec:
        if not cells:
            continue
        if grand:
            label = labels["grand"] if name == "total" else u"%s %s" % (labels["grand"], labels[name].lower())
        else:
            label = labels[name]
        out.append(Row(kind, cells, label=label))
    return out


def add_calculations(blocks, cols, grand_totals, labels):
    if not any(c.calc != "none" for c in cols):
        return blocks
    out = []
    for b in blocks:
        out.append(b + _calc_rows([r for r in b if r.kind == ROW_DATA], cols, False, labels))
    if grand_totals:
        all_data = [r for b in blocks for r in b if r.kind == ROW_DATA]
        g = _calc_rows(all_data, cols, True, labels)
        if g:
            out.append(g)
    return out


# --------------------------------------------------------------------------------------------- stage 6
def format_cells(blocks, cols):
    dec = dict((c.key, c.decimals) for c in cols)
    for b in blocks:
        for r in b:
            for k, v in list(r.cells.items()):
                d = dec.get(k)
                if d is not None and isinstance(v, float):
                    r.cells[k] = round(v, d)
    return blocks


# ------------------------------------------------------------------------------------------ the pipeline
def build_table(rs, settings):
    """Run stages 1-7. Returns Result(table, warnings, excel, revit)."""
    labels = dict(DEFAULT_LABELS)
    labels.update(settings.get("labels") or {})
    mode = settings.get("mode", "standard")
    itemize = bool(settings.get("itemize"))
    shape = detect_shape(rs, mode)

    cols, warns = select_columns(rs, settings)
    sort = []
    for s in settings.get("sort", []):
        if rs.field(s["key"]) is None:
            warns.append(u"Sort field '%s' not found in this project: skipped." % s["key"])
        else:
            sort.append(s)
    keys = [c.key for c in cols]
    keys += [s["key"] for s in sort if s["key"] not in keys]       # hidden / unused fields still sort

    rows, expanded = build_rows(rs, settings, keys, shape, labels)
    rows = apply_varies(rs, rows, keys, itemize, labels)
    blocks = sort_and_block(rows, sort, itemize, expanded)
    blocks = add_calculations(blocks, cols, bool(settings.get("grandTotals")), labels)
    blocks = format_cells(blocks, cols)

    if itemize and expanded and len(rows) > 500:
        warns.append(u"Itemized layered table: %d rows." % len(rows))
    title = settings.get("title")
    title = title if (title and _s(title).strip()) else (u"Abaco " + rs.category_name).strip()
    return Result(Table(title, cols, blocks), warns)
