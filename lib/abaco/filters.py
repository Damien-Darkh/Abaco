# -*- coding: utf-8 -*-
"""Filter stage (pipeline stage 1b). Pure Python: NO Revit imports, NO WPF.

Settings (JSON-ready, saved with the table settings in Phase 5):
    {"match": "all" | "any",
     "conditions": [ {"key": "<field key>", "op": "<code>", "value": u"<text>"}, ... ]}

The stage runs on ElementRecords BEFORE grouping, so counts, totals and Varies only see the matching
elements. Only element- and type-scope fields can be filtered (layer and calculated fields cannot).

A condition is in one of three states:
    ok          used for filtering
    incomplete  value still empty (the user is typing): skipped silently
    error       cannot be used (field gone, bad number, ...): skipped and reported

Common-subset Python (IronPython 2.7 / 3.4 / CPython 3): no f-strings.
"""
import copy
import re

MATCH_ALL = "all"
MATCH_ANY = "any"

NUMERIC_KINDS = ("number", "integer", "length", "area", "volume")
FILTERABLE_SCOPES = ("element", "type")

_TEXT_OPS = [("eq", u"equals"), ("ne", u"does not equal"),
             ("contains", u"contains"), ("not_contains", u"does not contain"),
             ("begins", u"begins with"), ("not_begins", u"does not begin with"),
             ("ends", u"ends with"), ("not_ends", u"does not end with")]
_NUM_OPS = [("eq", u"equals"), ("ne", u"does not equal"),
            ("gt", u"is greater than"), ("ge", u"is greater than or equal to"),
            ("lt", u"is less than"), ("le", u"is less than or equal to")]
_YESNO_OPS = [("eq", u"equals"), ("ne", u"does not equal")]
_EMPTY_OPS = [("has_value", u"has a value"), ("no_value", u"has no value")]

_EPS = 1e-6


# ------------------------------------------------------------------------------------------ operators
def operators_for(kind):
    """[(code, label)] valid for a field kind."""
    if kind in NUMERIC_KINDS:
        base = _NUM_OPS
    elif kind == "yesno":
        base = _YESNO_OPS
    else:
        base = _TEXT_OPS
    return list(base) + list(_EMPTY_OPS)


def needs_value(op):
    return op not in ("has_value", "no_value")


def parse_number(s):
    """'1,25' and '1.25' -> 1.25; None when it is not a number."""
    try:
        return float((u"%s" % s).strip().replace(u",", u"."))
    except (ValueError, TypeError):
        return None


def _norm(v):
    return re.sub(r"\s+", u" ", u"" if v is None else (u"%s" % v)).strip().lower()


# ------------------------------------------------------------------------------------------- matching
def matches(op, kind, raw, value):
    """True when the record value `raw` satisfies the condition. Text: case-insensitive, spaces collapsed."""
    if op == "has_value":
        return not (raw is None or _norm(raw) == u"")
    if op == "no_value":
        return raw is None or _norm(raw) == u""

    if kind in NUMERIC_KINDS:
        if raw is None:
            return op == "ne"                       # a missing number is "not equal" to anything
        b = parse_number(value)
        if b is None:
            return False
        a = float(raw)
        if op == "eq":
            return abs(a - b) < _EPS
        if op == "ne":
            return abs(a - b) >= _EPS
        if op == "gt":
            return a > b + _EPS
        if op == "ge":
            return a >= b - _EPS
        if op == "lt":
            return a < b - _EPS
        if op == "le":
            return a <= b + _EPS
        return False

    a, b = _norm(raw), _norm(value)
    if op == "eq":
        return a == b
    if op == "ne":
        return a != b
    if op == "contains":
        return b in a
    if op == "not_contains":
        return b not in a
    if op == "begins":
        return a.startswith(b)
    if op == "not_begins":
        return not a.startswith(b)
    if op == "ends":
        return a.endswith(b)
    if op == "not_ends":
        return not a.endswith(b)
    return False


# ---------------------------------------------------------------------------------------------- state
def status(cond, field, loaded_keys=None):
    """('ok'|'incomplete'|'error', message). `loaded_keys`: pass rs.loaded_keys to catch unread fields."""
    if field is None:
        return "error", u"field not found in this project"
    if field.scope not in FILTERABLE_SCOPES:
        return "error", u"'%s' is a layer/calculated field and cannot be filtered" % field.label
    op = cond.get("op")
    if op not in [c for c, _ in operators_for(field.kind)]:
        return "error", u"'%s' does not support this condition" % field.label
    if needs_value(op):
        raw = cond.get("value")
        if raw is None or (u"%s" % raw).strip() == u"":
            return "incomplete", u""
        if field.kind in NUMERIC_KINDS and parse_number(raw) is None:
            return "error", u"enter a number"
    if loaded_keys is not None and field.key not in loaded_keys:
        return "error", u"values of '%s' are not loaded yet" % field.label
    return "ok", u""


def needed_keys(settings):
    """Field keys to pass to revit_reader.ensure_values() BEFORE apply_filters()."""
    return [c["key"] for c in normalize_settings(settings)["conditions"] if c.get("key")]


# ---------------------------------------------------------------------------------------------- settings
def default_settings():
    return {"match": MATCH_ALL, "conditions": []}


def normalize_settings(d):
    """Always returns a valid settings dict. Missing/old/corrupt input gives defaults (Phase 5 rule)."""
    out = default_settings()
    if not isinstance(d, dict):
        return out
    if d.get("match") == MATCH_ANY:
        out["match"] = MATCH_ANY
    conds = d.get("conditions")
    if isinstance(conds, (list, tuple)):
        for c in conds:
            if not isinstance(c, dict):
                continue
            v = c.get("value")
            out["conditions"].append({
                "key": c.get("key") or u"",
                "op": c.get("op") or u"",
                "value": u"" if v is None else (u"%s" % v)})
    return out


# ------------------------------------------------------------------------------------------------ stage
class FilterResult(object):
    def __init__(self, kept, total, errors, n_active, n_incomplete):
        self.kept = kept                    # ElementRecords that pass
        self.total = total                  # elements before filtering
        self.errors = errors                # one text per condition ('' = none); same order as the settings
        self.n_active = n_active
        self.n_incomplete = n_incomplete

    @property
    def matched(self):
        return len(self.kept)

    @property
    def warnings(self):
        return [u"Filter %d skipped: %s" % (i + 1, e) for i, e in enumerate(self.errors) if e]

    def summary(self):
        if not self.n_active:
            s = u"No filter applied: %d elements." % self.total
        else:
            s = u"%d of %d elements match." % (self.matched, self.total)
        if self.n_incomplete:
            s += u" %d condition(s) waiting for a value." % self.n_incomplete
        return s


def apply_filters(rs, elements, settings):
    """Filter ElementRecords. Unusable conditions are skipped and reported in FilterResult.errors."""
    settings = normalize_settings(settings)
    match_all = settings["match"] != MATCH_ANY
    elements = list(elements)
    active, errors, incomplete = [], [], 0
    for c in settings["conditions"]:
        f = rs.field(c["key"]) if c["key"] else None
        state, msg = status(c, f, rs.loaded_keys)
        errors.append(msg if state == "error" else u"")
        if state == "ok":
            active.append((c, f))
        elif state == "incomplete":
            incomplete += 1
    if not active:
        return FilterResult(elements, len(elements), errors, 0, incomplete)
    kept = []
    for er in elements:
        res = [matches(c["op"], f.kind, rs.value(er, f.key), c["value"]) for c, f in active]
        if (all(res) if match_all else any(res)):
            kept.append(er)
    return FilterResult(kept, len(elements), errors, len(active), incomplete)


def filtered_view(rs, kept):
    """A RecordSet that only holds the kept elements. Types, field catalogue and loaded_keys are SHARED with
    `rs` (shallow copy), so the pipeline runs unchanged on it and values read later are cached on the real
    records. Call revit_reader.ensure_values() on the full `rs` first (values of excluded elements too)."""
    view = copy.copy(rs)
    view.elements = list(kept)
    return view
