# -*- coding: utf-8 -*-
"""Filter stage. Pure Python: NO Revit imports, NO WPF.

Two passes, chosen by the scope of each condition:
  model conditions (element and type fields)  run on ElementRecords BEFORE grouping
  calculated conditions (formula fields)      run on the pipeline rows AFTER grouping, on row values

Match all (AND): both passes apply, so the result is the same as one AND over everything.
Match any (OR): model conditions or calculated conditions only. A mix is refused: the two passes cannot
be combined as OR yet, so the calculated conditions are skipped and reported.

Settings (JSON-ready, saved with the table settings in Phase 9):
    {"match": "all" | "any",
     "conditions": [ {"key": "<field key>", "op": "<code>", "value": u"<text>"}, ... ]}

A condition is in one of three states:
    ok          used for filtering
    incomplete  value still empty (the user is typing): skipped silently
    error       cannot be used (field gone, bad number, ...): skipped and reported

Common-subset Python (IronPython 2.7 / 3.4 / CPython 3): no f-strings.
"""
import re

from abaco import evaluate as EV
from abaco import units as U

MATCH_ALL = "all"
MATCH_ANY = "any"
FORMULA_SCOPE = "formula"

NUMERIC_KINDS = ("number", "integer", "length", "area", "volume")
FILTERABLE_SCOPES = ("element", "type", FORMULA_SCOPE)

MIXED_OR_MSG = u"Any (OR) cannot mix model and calculated conditions yet: this condition was skipped"

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
    """True when the value `raw` satisfies the condition. Text: case-insensitive, spaces collapsed."""
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


def _row_matches(op, kind, raw, value):
    """Same as matches(), for a calculated value from a pipeline row (NONE, errors and booleans)."""
    if raw is EV.NONE:
        raw = None
    elif isinstance(raw, EV.Err):
        return False                                # an error matches no condition
    elif isinstance(raw, bool):
        raw = u"Yes" if raw else u"No"
    return matches(op, kind, raw, value)


# ---------------------------------------------------------------------------------------------- state
def status(cond, field, loaded_keys=None):
    """('ok'|'incomplete'|'error', message). Pass rs.loaded_keys for model fields, None for calculated ones."""
    if field is None:
        return "error", u"field not found in this project"
    if field.scope not in FILTERABLE_SCOPES:
        return "error", u"'%s' is a layer or group field and cannot be filtered" % field.label
    op = cond.get("op")
    if op not in [c for c, _ in operators_for(field.kind)]:
        return "error", u"'%s' does not support this condition" % field.label
    if needs_value(op):
        raw = cond.get("value")
        if raw is None or (u"%s" % raw).strip() == u"":
            return "incomplete", u""
        if field.kind in NUMERIC_KINDS and parse_number(raw) is None:
            return "error", u"enter a number"
    if loaded_keys is not None and field.scope != FORMULA_SCOPE and field.key not in loaded_keys:
        return "error", u"values of '%s' are not loaded yet" % field.label
    return "ok", u""


def needed_keys(settings):
    """Field keys to pass to revit_reader.ensure_values() BEFORE apply_filters()."""
    return [c["key"] for c in normalize_settings(settings)["conditions"] if c.get("key")]


# ---------------------------------------------------------------------------------------------- settings
def default_settings():
    return {"match": MATCH_ALL, "conditions": []}


def normalize_settings(d):
    """Always returns a valid settings dict. Missing/old/corrupt input gives defaults (Phase 9 rule)."""
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


def split(rs, settings):
    s = normalize_settings(settings)
    model_idx, calc_idx, dropped = [], [], {}
    for i, c in enumerate(s["conditions"]):
        f = rs.field(c["key"]) if c["key"] else None
        if f is not None and f.scope == FORMULA_SCOPE:
            calc_idx.append(i)
        else:
            model_idx.append(i)
    if calc_idx and s["match"] == MATCH_ANY:
        live = [i for i in model_idx
                if status(s["conditions"][i], rs.field(s["conditions"][i]["key"]),
                          rs.loaded_keys)[0] == "ok"]
        if live:
            for i in calc_idx:
                dropped[i] = MIXED_OR_MSG
            calc_idx = []
    return model_idx, calc_idx, dropped

# ------------------------------------------------------------------------------------------------ stage
class FilterResult(object):
    def __init__(self, kept, total, errors, n_active, n_incomplete, n_calc=0):
        self.kept = kept                    # ElementRecords that pass the model conditions
        self.total = total                  # elements before filtering
        self.errors = errors                # one text per condition ('' = none); same order as the settings
        self.n_active = n_active            # model conditions in use
        self.n_incomplete = n_incomplete
        self.n_calc = n_calc                # calculated conditions in use (applied to rows later)

    @property
    def matched(self):
        return len(self.kept)

    @property
    def warnings(self):
        return [u"Filter %d skipped: %s" % (i + 1, e) for i, e in enumerate(self.errors) if e]

    def summary(self):
        if not self.n_active and not self.n_calc:
            s = u"No filter applied: %d elements." % self.total
        elif not self.n_active:
            s = u"%d elements; %d calculated condition(s) apply to the rows after grouping." % (
                self.total, self.n_calc)
        else:
            s = u"%d of %d elements match." % (self.matched, self.total)
            if self.n_calc:
                s += u" %d calculated condition(s) apply after grouping." % self.n_calc
        if self.n_incomplete:
            s += u" %d condition(s) waiting for a value." % self.n_incomplete
        return s


def apply_filters(rs, elements, settings, allowed=None):
    """Model pass: filters ElementRecords before grouping. Calculated conditions are checked here too
    (for the messages), and run later by apply_row_filters(). allowed: keys of the Fields tab."""
    s = normalize_settings(settings)
    model_idx, calc_idx, dropped = split(rs, s)
    errors = [u""] * len(s["conditions"])
    active, n_incomplete = [], 0

    for i in model_idx:
        c = s["conditions"][i]
        f = rs.field(c["key"]) if c["key"] else None
        if f is not None and allowed is not None and f.key not in allowed:
            errors[i] = u"field is not in the Fields tab"
            continue
        state, msg = status(c, f, rs.loaded_keys)
        errors[i] = msg if state == "error" else u""
        if state == "ok":
            active.append((c, f))
        elif state == "incomplete":
            n_incomplete += 1

    for i, msg in dropped.items():
        if not errors[i]:
            errors[i] = msg

    n_calc = 0
    for i in calc_idx:
        c = s["conditions"][i]
        f = rs.field(c["key"])
        if allowed is not None and f.key not in allowed:
            errors[i] = u"field is not in the Fields tab"
            continue
        state, msg = status(c, f, None)
        errors[i] = msg if state == "error" else u""
        if state == "ok":
            n_calc += 1
        elif state == "incomplete":
            n_incomplete += 1

    elements = list(elements)
    if not active:
        return FilterResult(elements, len(elements), errors, 0, n_incomplete, n_calc)
    match_all = s["match"] != MATCH_ANY
    kept = []
    for er in elements:
        res = [matches(c["op"], f.kind, rs.value(er, f.key), c["value"]) for c, f in active]
        if (all(res) if match_all else any(res)):
            kept.append(er)
    return FilterResult(kept, len(elements), errors, len(active), n_incomplete, n_calc)


def apply_row_filters(rs, rows, settings, allowed=None):
    """Calculated pass: keeps the pipeline rows that pass the calculated conditions. Call it after the
    calculated values are set on every row and before the blocks are built, so footers and summaries
    only add up the rows that remain."""
    s = normalize_settings(settings)
    _, calc_idx, _ = split(rs, s)
    active = []
    for i in calc_idx:
        c = s["conditions"][i]
        f = rs.field(c["key"])
        if allowed is not None and f.key not in allowed:
            continue
        if status(c, f, None)[0] == "ok":
            active.append((c, f))
    if not active:
        return rows
    match_all = s["match"] != MATCH_ANY
    kept = []
    for r in rows:
        res = [_row_matches(c["op"], f.kind, r.cells.get(f.key), c["value"]) for c, f in active]
        if (all(res) if match_all else any(res)):
            kept.append(r)
    return kept


def suggestion_text(value, kind, decimals=None):
    """Text offered in the Value suggestions for a model value.

    Numbers use units.format_text with the field's decimals and no currency symbol, so the text reads back
    through parse_number(). The value is in base units (m, m2, m3, rad), the same units the condition
    compares in, so a suggestion never needs converting.
    """
    if value is None or value == u"":
        return u""
    if kind in NUMERIC_KINDS and isinstance(value, (int, float)) and not isinstance(value, bool):
        return U.format_text(float(value), decimals)
    return u"%s" % value


def value_unit(field):
    """Unit a numeric condition is typed in, for the Value hint: 'm' for a length, '' when none."""
    if field is None or field.dim is None:
        return u""
    return U.BASE_UNIT.get(field.dim) or u""


def filtered_view(rs, kept):
    """A RecordSet that shares everything with `rs` (catalogue, types, loaded flags) but whose
    elements are only the ones that passed the model filter. The original is never modified."""
    from abaco.records import RecordSet
    v = RecordSet.__new__(RecordSet)
    v.__dict__.update(rs.__dict__)
    v.elements = list(kept)
    return v