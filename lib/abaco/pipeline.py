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
    K_LAYER_ORDER, K_LAYER_MATERIAL, K_LAYER_THICKNESS, K_LAYER_FUNCTION, K_LAYER_AREA, K_IS_CURTAIN)

from abaco import appearance as AP

try:
    _STR = (basestring,)
except NameError:
    _STR = (str,)

_NUM = (int, float)
try:
    _NUM = _NUM + (type(2 ** 64),)      # long on Python 2 / IronPython 2.7, int on Python 3
except Exception:
    pass

CALC_MODES = ("none", "total", "min", "max", "minmax")
DEFAULT_LABELS = {"varies": u"Varies", "total": u"Total", "min": u"Min", "max": u"Max",
                  "grand": u"Grand total", "no_layers": u"(no layers)", "summary": u"Summary"}

# decimals that reproduce v1; other fields fall back on the kind
_KEY_DECIMALS = {K_LAYER_THICKNESS: 4, K_WIDTH: 3, K_HEIGHT: 3, K_LENGTH: 2, K_AREA: 2, K_LAYER_AREA: 2}
_KIND_DECIMALS = {"length": 3, "area": 2, "volume": 3, "number": 3}

ROW_DATA, ROW_TOTAL, ROW_MIN, ROW_MAX = "data", "total", "min", "max"
ROW_GTOTAL, ROW_GMIN, ROW_GMAX = "gtotal", "gmin", "gmax"
CALC_ROW_KINDS = (ROW_TOTAL, ROW_MIN, ROW_MAX, ROW_GTOTAL, ROW_GMIN, ROW_GMAX)
ROW_BLANK, ROW_HEADER = "blank", "header"

ROW_SUMHEAD = "sumhead"             # "Summary" header row at the bottom of the table


_KIND_EL = {ROW_DATA: "data", ROW_HEADER: "header", ROW_SUMHEAD: "summaryHeader",
            ROW_TOTAL: "summary", ROW_MIN: "summary", ROW_MAX: "summary",
            ROW_GTOTAL: "summary", ROW_GMIN: "summary", ROW_GMAX: "summary"}


# ------------------------------------------------------------------------------------------- settings
def field_setting(key, **kw):
    d = {"key": key, "include": True, "heading": None, "align": "left", "orientation": "horizontal",
         "widthMm": None, "hiddenInRevit": False, "showInExcel": True, "calc": "none", "decimals": None}
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

def default_settings(rs, table_type="schedule", title=u""):
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
        hidden.add(K_TYPE_NAME)                            # v1 default hidden columns
    fields = []
    for k in keys:
        extra = {}
        if k == K_AREA and ttype == "takeoff" and walls:
            extra["heading"] = u"Wall Area (m\u00b2)"      # v1 heading
        fields.append(field_setting(k, hiddenInRevit=(k in hidden), **extra))
    levels = ([sort_setting(k, gap=True, footer=(i == len(group) - 1)) for i, k in enumerate(group)]
              + [sort_setting(k) for k in sort])
    return {"category": rs.category_id, "tableType": ttype, "title": title, "fields": fields,
            "levels": levels, "grandTotals": False, "itemize": False, "labels": dict(DEFAULT_LABELS), "appearance": AP.preset("bw")}


def required_keys(settings):
    keys = [f["key"] for f in settings.get("fields", [])]
    keys += [s["key"] for s in settings.get("levels", []) if s.get("key")]
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
    def __init__(self, kind, cells, gid=0, lorder=0, els=None, label=None, members=None):
        self.kind = kind
        self.cells = cells          # field key -> value (None = empty)
        self.gid = gid              # group (or element, when itemized) sequence number
        self.lorder = lorder        # layer order, the last implicit sort key
        self.els = els or []        # ElementRecords behind this row (data rows)
        self.label = label          # text for total/min/max rows, and the value of a header row
        self.members = members or []  # data rows that a footer adds up


class Table(object):
    def __init__(self, title, columns, blocks, appearance=None):
        self.title = title
        self.columns = columns
        self.blocks = blocks                       # list of lists of Row
        self.appearance = appearance or AP.preset("bw")

    def select(self, keep):
        return Table(self.title, [c for c in self.columns if keep(c)], self.blocks, self.appearance)

    def n_data_rows(self):
        return sum(1 for b in self.blocks for r in b if r.kind == ROW_DATA)

    def headings(self):
        mode = AP.case_of(self.appearance, "heading")
        return [AP.apply_case(c.heading, mode) for c in self.columns]

    def _line(self, r):
        n = len(self.columns)
        app = self.appearance
        if r.kind in (ROW_HEADER, ROW_SUMHEAD):   # full-row text, always in the first cell
            line = [u""] * n
            line[0] = AP.apply_case(r.label or u"", AP.case_of(app, _KIND_EL[r.kind]))
            return line
        mode = AP.case_of(app, _KIND_EL.get(r.kind, "data"))
        line = []
        for c in self.columns:
            v = r.cells.get(c.key)
            if v is None:
                v = u""
            elif AP.is_text(v):
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

def _fmt(v, dec):
    return (u"%.*f" % (dec, v)) if dec is not None else format(v, ".15g")


def _row_calc_value(els, key, mode, dec):
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
    return u"%s \u2013 %s" % (_fmt(lo, dec), _fmt(hi, dec))


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
def _sv(v):
    return round(v, 3) if isinstance(v, float) else v


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
    # instance fields used as a group level split the rows (no "Varies" inside a group)
    return (e.type_id, e.get(K_LEVEL), wh[0], wh[1]) + tuple(_sv(e.get(k)) for k in split)


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
                    cells[key] = _r3(ges[0].get(K_WIDTH))
                elif key == K_HEIGHT and not itemize and (tr.is_curtain or not tr.is_layered):
                    cells[key] = _r3(ges[0].get(K_HEIGHT))
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
    calc = dict((c.key, c.calc) for c in cols)
    dec = dict((c.key, c.decimals) for c in cols)
    todo = [k for k in keys if rs.field(k) is not None and rs.field(k).scope == "element"]
    cache = {}
    for r in rows:
        for k in todo:
            mode = calc.get(k, "none")
            if mode != "none":
                ck = (r.gid, k, mode)
                if ck not in cache:
                    cache[ck] = _row_calc_value(r.els, k, mode, dec.get(k))
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
    """Value that decides a new block. A blank Type Mark counts as 'this type' (v1: types without a mark
    are separated by name), a shared Type Mark keeps its types in one block."""
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


def _header_text(r, lv):
    v = r.cells.get(lv["key"])
    return u"(none)" if v is None or v == u"" else u"%s" % v


def _footer(seg, cols, labels, mode):
    out = _calc_rows(seg, cols, False, labels, override=mode)
    for x in out:
        x.members = seg
    return out


def _seg_items(seg, levels, i, cols, labels):
    """Rows of one segment of level i, in Revit order: header, children, footer, gap."""
    lv = levels[i]
    out = []
    if lv.get("header"):
        out.append(Row(ROW_HEADER, {}, label=_header_text(seg[0], lv)))
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
    if scope == "layer":
        return [r.cells.get(c.key) for r in rows]
    seen, out = set(), []
    for r in rows:
        if r.gid not in seen:
            seen.add(r.gid)
            out.append(r.cells.get(c.key))
    return out


def _calc_rows(rows, cols, grand, labels, override=None):
    """Total / min / max rows for `rows`. override: footer mode of one level (None or 'field' = each
    field's own Calculation)."""
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
        if not cells:
            continue
        if grand:
            label = labels[name]
        else:
            label = labels[name]
        out.append(Row(kind, cells, label=label))
    return out


def build_blocks(rows, levels, cols, labels, itemize, expanded, grand):
    levels = list(levels)
    if itemize and expanded:           # one block per element, its layers repeated
        levels.insert(0, {"key": None, "_gid": True, "header": False, "footer": False, "gap": False})
    rows = _sort_rows(rows, levels)
    if levels:
        blocks = [_seg_items(seg, levels, 0, cols, labels) for seg in _segments(rows, levels[0])]
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
    labels = dict(DEFAULT_LABELS)
    labels.update(settings.get("labels") or {})
    itemize = bool(settings.get("itemize"))
    ttype = effective_type(rs, settings)
    appearance = AP.normalize(settings.get("appearance"))

    cols, warns = select_columns(rs, settings, ttype)
    if settings.get("tableType") == "takeoff" and ttype != "takeoff":
        warns.insert(0, u"Material takeoff needs layered types: showing a schedule instead.")
    allowed = set(c.key for c in cols)                    # Sort & group only use fields of the Fields tab
    levels = _levels(rs, settings.get("levels") or [], ttype, u"Level", warns, allowed)

    keys = [c.key for c in cols]
    split = [s["key"] for s in levels if rs.field(s["key"]).scope == "element"]

    rows, expanded = build_rows(rs, settings, keys, ttype, labels, split)
    rows = apply_varies(rs, rows, keys, itemize, labels, cols)
    blocks = build_blocks(rows, levels, cols, labels, itemize, expanded, bool(settings.get("grandTotals")))
    blocks = format_cells(blocks, cols)

    if itemize and expanded and len(rows) > 500:
        warns.append(u"Itemized layered table: %d rows." % len(rows))
    title = settings.get("title")
    title = title if (title and _s(title).strip()) else (u"Abaco " + rs.category_name).strip()
    return Result(Table(title, cols, blocks, appearance), warns)