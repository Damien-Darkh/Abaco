# -*- coding: utf-8 -*-
"""Formula evaluator (Phase 5): evaluates a checked tree for ONE row. Pure Python, no Revit, no WPF.

    ast = formula.check(stored_text, rs.fields, labels).ast       # stored form: {@KEY}, see below
    value = evaluate(ast, get, kind_of)

    get(key)      the row's raw cell value for a field key: a number, text, bool or None (no value).
                  Raise KeyError when the row does not carry the field at all (-> #ERROR, reason ref).
    kind_of(key)  the field's record kind ("length", "yesno", ...). Optional: without it the value's own
                  Python type decides, and Yes/No text stays text.

The formula must be in STORED form (keys between braces, formula.to_stored()): the tree keeps the name
exactly as written and evaluate() passes it to get().

A value is: float | text | bool | NONE | Err(reason, message). Errors are returned, never raised, so one
bad row cannot stop the table. Rules are those of phase5.md section 7:
    NONE in, NONE out (arithmetic, functions, = != < > <= >=); an error wins over NONE.
    AND / OR: FALSE AND x and x AND FALSE are FALSE, TRUE OR x and x OR TRUE are TRUE, whatever x is (NONE
    included); otherwise NONE wins. An error wins over everything and is never hidden by the other side.
    IF is lazy and gives NONE for a NONE condition.  / and % by zero: div0.  SQRT / even ROOT of a negative: sqrt_neg.
    = and != use a tolerance of 1e-6; ordering is exact.  % takes the sign of the divisor (Python).
    INT rounds half away from zero (text: its length).  STRING keeps a literal's typed text (2.00 -> "2.00"),
    otherwise the shortest text that reads back to the same float (2.0 -> "2").
Two details the spec leaves open, decided here:
    reason "range"  a result that is not a finite number (overflow, ...).  "type" a row value of the wrong
                    type (for example text in a number field). The pipeline should hand NONE for a "Varies" cell.
    0 ^ negative is div0, a negative base with a fractional exponent is sqrt_neg (no real result).

Also here: topological_order() (calculated fields that use each other, circular reference refused with the
loop shown), calculate_row(), to_cell() (#NONE #ERROR #TRUE #FALSE) and dry_run().

Common-subset Python (IronPython 2.7 / 3.4 / CPython 3): no f-strings.
"""
import math
from decimal import Decimal

from abaco import formula as F

try:
    _STR = (basestring,)
except NameError:
    _STR = (str,)
try:
    _NUMTYPES = (int, long, float)
except NameError:
    _NUMTYPES = (int, float)

R_RANGE = u"range"
TOLERANCE = 1e-6                        # = and != on numbers (same as filters)
_NUMERIC_KINDS = ("number", "integer", "length", "area", "volume")


class _NoneValue(object):
    def __repr__(self):
        return "NONE"


NONE = _NoneValue()

class _VariesValue(object):
    def __repr__(self):
        return "VARIES"


VARIES = _VariesValue()      # the elements of a grouped row differ: the result is "Varies", not a value

class Err(object):
    """A calculation error with a reason code (formula.R_* or R_RANGE) and a message."""

    def __init__(self, reason, message):
        self.reason = reason
        self.message = message

    def __repr__(self):
        return "Err(%s: %s)" % (self.reason, self.message)


def is_error(v):
    return isinstance(v, Err)


def is_none(v):
    return v is NONE

def is_varies(v):
    return v is VARIES


def to_cell(v, varies_label=u"Varies"):
    """Value -> what the table cell shows. Numbers stay numbers, the pipeline formats them.
    varies_label is the table's configurable 'Varies' word (labels["varies"])."""
    if isinstance(v, Err):
        return u"#ERROR"
    if v is NONE:
        return u"#NONE"
    if v is VARIES:
        return varies_label
    if v is True:
        return u"#TRUE"
    if v is False:
        return u"#FALSE"
    return v


# ------------------------------------------------------------------------------------------- helpers
def _prop(*vals):
    """The first error, else NONE, else VARIES, else None (all values usable)."""
    for v in vals:
        if isinstance(v, Err):
            return v
    for v in vals:
        if v is NONE:
            return NONE
    for v in vals:
        if v is VARIES:
            return VARIES
    return None

def _isnum(v):
    return isinstance(v, float)


def _type_err(msg):
    return Err(F.R_TYPE, msg)


def _fin(r):
    if math.isnan(r) or math.isinf(r):
        return Err(R_RANGE, u"the result is not a finite number (too large)")
    return r


def _shortest(x):
    """Shortest text that reads back to the same float, in plain notation (never 1e-05 or 1e+22);
    whole numbers without '.0'."""
    if x == 0:
        return u"0"
    s = format(Decimal(repr(x)), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return u"%s" % s


def _from_raw(raw, kind, key):
    """A cell's raw value -> evaluator value."""
    if raw is None or raw is NONE:
        return NONE
    if isinstance(raw, Err):
        return raw
    if raw is None or raw is NONE:
        return NONE
    if isinstance(raw, Err):
        return raw
    if raw is VARIES:
        return VARIES
    if kind == "yesno":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, _STR):
            t = raw.strip().lower()
            if t == u"yes":
                return True
            if t == u"no":
                return False
        return NONE                                   # any other text: NONE (phase5.md 7.7)
    numeric = kind in _NUMERIC_KINDS
    if numeric or (kind is None and isinstance(raw, _NUMTYPES) and not isinstance(raw, bool)):
        if isinstance(raw, bool) or not isinstance(raw, _NUMTYPES):
            return _type_err(u"{%s} should hold a number but holds %s" % (key, u"text" if isinstance(raw, _STR) else u"another kind of value"))
        return float(raw)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, _STR):
        return raw
    return _type_err(u"{%s} holds a value that formulas cannot use" % key)


def _is_sens(node):
    return node.kind == u"call" and node.name == u"SENSITIVE" and len(node.args) == 1


def _literal_text(node):
    """The typed text of a number literal (2.00), with a minus sign or a unit suffix; else None."""
    if node.kind == u"num":
        return node.text
    if node.kind == u"unitize":
        return _literal_text(node.arg)
    if node.kind == u"neg":
        t = _literal_text(node.arg)
        return None if t is None else u"-" + t
    return None


# --------------------------------------------------------------------------------------------- evaluator
class _Eval(object):
    def __init__(self, get, kind_of, computed):
        self.get = get
        self.kind_of = kind_of
        self.computed = computed

    def run(self, node):
        return getattr(self, "n_" + node.kind)(node)

    # ---- leaves
    def n_num(self, node):
        return float(node.value)

    def n_text(self, node):
        return node.value

    def n_bool(self, node):
        return node.value

    def n_unitize(self, node):
        return self.run(node.arg)                     # the unit only matters to the checker

    def n_field(self, node):
        key = node.key
        if key in self.computed:
            return self.computed[key]
        try:
            raw = self.get(key)
        except KeyError:
            return Err(F.R_REF, u"this row has no value for {%s}" % key)
        return _from_raw(raw, self.kind_of(key) if self.kind_of else None, key)

    def n_neg(self, node):
        v = self.run(node.arg)
        p = _prop(v)
        if p is not None:
            return p
        if not _isnum(v):
            return _type_err(u"'-' needs a number")
        return -v

    # ---- operators
    def n_bin(self, node):
        op = node.op
        if op == u"AND":
            return self.and_or(node, False)
        if op == u"OR":
            return self.and_or(node, True)
        if op in F.CMP_OPS:
            return self.compare(node)
        l, r = self.run(node.left), self.run(node.right)
        p = _prop(l, r)
        if p is not None:
            return p
        if op == u"+" and isinstance(l, _STR) and isinstance(r, _STR):
            return l + r
        if not (_isnum(l) and _isnum(r)):
            return _type_err(u"'%s' needs two numbers" % op)
        if op == u"+":
            return _fin(l + r)
        if op == u"-":
            return _fin(l - r)
        if op == u"*":
            return _fin(l * r)
        if op == u"/":
            if r == 0:
                return Err(F.R_DIV0, u"division by zero")
            return _fin(l / r)
        if op == u"%":
            if r == 0:
                return Err(F.R_DIV0, u"remainder of a division by zero")
            return _fin(l % r)
        return self.power(l, r)

    def power(self, x, y):
        if x == 0 and y < 0:
            return Err(F.R_DIV0, u"zero raised to a negative power")
        if x < 0 and y != math.floor(y):
            return Err(F.R_SQRT, u"a negative number raised to a fraction has no real value")
        try:
            return _fin(x ** y)
        except OverflowError:
            return Err(R_RANGE, u"the result is too large")

    def and_or(self, node, is_or):
        """AND (is_or False) / OR (True). The deciding value (FALSE for AND, TRUE for OR) wins on either side,
        even against NONE or VARIES. On the left it also stops the right side from being evaluated."""
        decider = is_or
        word = u"OR" if is_or else u"AND"
        l = self.run(node.left)
        if l is decider:
            return decider
        if isinstance(l, Err):
            return l
        if l is not NONE and l is not VARIES and not isinstance(l, bool):
            return _type_err(u"%s needs TRUE or FALSE on both sides" % word)
        r = self.run(node.right)
        if isinstance(r, Err):
            return r                                  # an error wins over NONE and VARIES
        if r is not NONE and r is not VARIES and not isinstance(r, bool):
            return _type_err(u"%s needs TRUE or FALSE on both sides" % word)
        if r is decider:
            return decider
        if l is NONE or r is NONE:
            return NONE
        if l is VARIES or r is VARIES:
            return VARIES
        return r

    def compare(self, node):
        lnode, rnode, sens = node.left, node.right, False
        if _is_sens(lnode):
            lnode, sens = lnode.args[0], True
        if _is_sens(rnode):
            rnode, sens = rnode.args[0], True
        l, r = self.run(lnode), self.run(rnode)
        p = _prop(l, r)
        if p is not None:
            return p
        op = node.op
        if isinstance(l, bool) or isinstance(r, bool):
            if not (isinstance(l, bool) and isinstance(r, bool)):
                return _type_err(u"cannot compare a true/false value with something else")
            if op == u"=":
                return l == r
            if op == u"!=":
                return l != r
            return _type_err(u"TRUE and FALSE only compare with = and !=")
        if _isnum(l) and _isnum(r):
            if op == u"=":
                return abs(l - r) < TOLERANCE
            if op == u"!=":
                return not abs(l - r) < TOLERANCE
        elif isinstance(l, _STR) and isinstance(r, _STR):
            if not sens:
                l, r = l.lower(), r.lower()
        else:
            return _type_err(u"cannot compare a number with text")
        return {u"=": l == r, u"!=": l != r, u"<": l < r, u">": l > r, u"<=": l <= r, u">=": l >= r}[op]

    # ---- functions
    def n_call(self, node):
        name = node.name
        if name == u"IF":
            return self.f_if(node)
        if name == u"STRING":
            return self.f_string(node)
        if name == u"HASVALUE":
            return self.f_hasvalue(node)
        args = [self.run(a) for a in node.args]
        p = _prop(*args)
        if p is not None:
            return p
        fn = getattr(self, "f_" + name.lower(), None)
        if fn is None:
            return Err(F.R_SYNTAX, u"%s cannot be used here" % name)
        return fn(args)

    def f_if(self, node):
        cond = node.args[0]
        c = self.field_condition(cond) if cond.kind == u"field" else self.run(cond)
        if isinstance(c, Err) or c is NONE or c is VARIES:
            return c
        if not isinstance(c, bool):
            return _type_err(u"the condition of IF must be TRUE or FALSE")
        return self.run(node.args[1] if c else node.args[2])     # lazy: the other branch is never evaluated

    def field_condition(self, node):
        """A bare field as the IF condition. A Yes/No field gives its value. Any other field is TRUE when
        it has a value and FALSE when it is empty. Errors and VARIES pass through."""
        v = self.run(node)
        if isinstance(v, Err) or v is VARIES:
            return v
        if self.kind_of and self.kind_of(node.key) == "yesno":
            return v                                   # an empty Yes/No stays NONE
        if v is NONE:
            return False
        if isinstance(v, _STR) and v == u"":
            return False
        return True

    def f_string(self, node):
        lit = _literal_text(node.args[0])
        if lit is not None:
            return lit
        v = self.run(node.args[0])
        if isinstance(v, Err) or v is NONE or v is VARIES or isinstance(v, _STR):
            return v
        if isinstance(v, bool):
            return u"TRUE" if v else u"FALSE"
        return _shortest(v)

    def f_hasvalue(self, node):
        v = self.run(node.args[0])
        if isinstance(v, Err):
            return v                       # an error stays an error, it is not an empty value
        if v is NONE:
            return False
        if v is VARIES:
            return VARIES
        if isinstance(v, _STR) and v == u"":
            return False
        return True

    @staticmethod
    def _numbers(args, name):
        if not all(_isnum(a) for a in args):
            return _type_err(u"%s needs numbers" % name)
        return None

    def f_min(self, args):
        return self._numbers(args, u"MIN") or min(args)

    def f_max(self, args):
        return self._numbers(args, u"MAX") or max(args)

    def f_abs(self, args):
        return self._numbers(args, u"ABS") or abs(args[0])

    def f_sqrt(self, args):
        bad = self._numbers(args, u"SQRT")
        if bad:
            return bad
        if args[0] < 0:
            return Err(F.R_SQRT, u"square root of a negative number")
        return math.sqrt(args[0])

    def f_root(self, args):
        bad = self._numbers(args, u"ROOT")
        if bad:
            return bad
        x, n = args
        if n < 1 or n != math.floor(n):
            return _type_err(u"the degree of ROOT must be a whole number from 1 upwards")
        n = int(n)
        if x < 0 and n % 2 == 0:
            return Err(F.R_SQRT, u"even root of a negative number")
        r = abs(x) ** (1.0 / n)
        k = float(round(r))
        if k ** n == abs(x):                          # 64 ^ (1/3) is 3.9999999999999996 in floating point
            r = k
        return -r if x < 0 else r

    def f_int(self, args):
        x = args[0]
        if isinstance(x, _STR):
            return float(len(x))                      # a text gives its length
        if not _isnum(x):
            return _type_err(u"INT needs a number or a text")
        a = abs(x)
        f = math.floor(a)
        r = f + 1.0 if a - f >= 0.5 else f            # half away from zero; a - f is exact, unlike a + 0.5
        return (r if x >= 0 else -r) + 0.0            # no -0.0

    def f_float(self, args):
        x = args[0]
        if isinstance(x, _STR):
            return float(len(x))
        if not _isnum(x):
            return _type_err(u"FLOAT needs a number or a text")
        return x


# ---------------------------------------------------------------------------------------------- public
def evaluate(node, get, kind_of=None, computed=None):
    """Value of a checked formula for one row. `computed` {key: value} holds already calculated fields."""
    return _Eval(get, kind_of, computed if computed is not None else {}).run(node)


def topological_order(deps, label_of=None):
    """deps {key: iterable of keys it refers to}; keys that are not in deps (model fields) are ignored.
    Returns the keys with every dependency before its user. Raises formula.FormulaError (reason ref) with
    the full loop when two calculated fields depend on each other, directly or through others."""
    label_of = label_of or {}
    order, state = [], {}

    def visit(key, path):
        if state.get(key) == 2:
            return
        if state.get(key) == 1:
            loop = path[path.index(key):] + [key]
            names = u" -> ".join(u"{%s}" % label_of.get(k, k) for k in loop)
            err = F.FormulaError(0, F.R_REF, u"circular reference: %s" % names,
                                 u"remove one of the references so the formulas no longer depend on each other")
            err.loop = loop                           # the keys of the loop, for callers that want to cut it
            raise err
        state[key] = 1
        for d in sorted(deps.get(key, ())):
            if d in deps:
                visit(d, path + [key])
        state[key] = 2
        order.append(key)

    for k in sorted(deps):
        visit(k, [])
    return order


def calculate_row(formulas, order, get, kind_of=None):
    """Calculated fields of one row. formulas {key: checked tree}, order from topological_order().
    Returns {key: value}; a field whose formula fails holds its Err, so the fields that use it fail too."""
    computed = {}
    for key in order:
        computed[key] = evaluate(formulas[key], get, kind_of, computed)
    return computed


class DryRun(object):
    def __init__(self):
        self.total = 0
        self.errors = 0
        self.none = 0
        self.by_reason = {}             # reason -> number of rows
        self.examples = []              # [(row id, reason, message)], at most max_examples
        self.varies = 0

    @property
    def ok(self):
        return self.errors == 0

    def summary(self, label):
        if not self.errors:
            return u"{%s}: no errors in %d rows (%d without a value)." % (label, self.total, self.none)
        reasons = u", ".join(u"%s: %d" % (k, self.by_reason[k]) for k in sorted(self.by_reason))
        eg = u"; ".join(u"%s: %s" % (i, m) for i, _, m in self.examples)
        return u"{%s}: %d of %d rows give #ERROR (%s). e.g. %s" % (label, self.errors, self.total, reasons, eg)


def dry_run(node, rows, kind_of=None, max_examples=3):
    """Evaluate a formula over rows [(row id, get)] and count what goes wrong, by reason."""
    res = DryRun()
    for row_id, get in rows:
        res.total += 1
        v = evaluate(node, get, kind_of)
        if v is NONE:
            res.none += 1
        elif v is VARIES:
            res.varies += 1
        elif isinstance(v, Err):
            res.errors += 1
            res.by_reason[v.reason] = res.by_reason.get(v.reason, 0) + 1
            if len(res.examples) < max_examples:
                res.examples.append((row_id, v.reason, v.message))
    return res
