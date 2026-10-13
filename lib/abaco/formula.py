# -*- coding: utf-8 -*-
"""Formula language, version 1 (Phase 5): tokenizer, parser, unit and type checker.

Pure Python: no Revit, no WPF. Runs on IronPython 2.7 and CPython 3.
Evaluation (per row, live) is in evaluate.py.

Grammar (version 1: one expression; no chains, no blocks):

  expr    := or
  or      := and ( OR and )*
  and     := cmp ( AND cmp )*
  cmp     := add ( ( = | != | < | > | <= | >= ) add )?      (no chaining)
  add     := mul ( ( + | - ) mul )*
  mul     := pow ( ( * | / | % ) pow )*
  pow     := unary ( ^ pow )?                              (right-associative)
  unary   := - unary | postfix
  postfix := primary [ unit ]
  primary := number | text | TRUE | FALSE | field | call | ( expr )
  call    := NAME ( expr ( , expr )* )
  field   := { key }

Keywords, function names, TRUE and FALSE are case-insensitive.
Units m, m2, m², m3, m³ are case-insensitive. A unit follows a number, a count field, or a bracket.
Text literals use double quotes; "" inside a text is one quote.
Numbers use a dot and have no exponent.
"""
import re
import difflib

R_SYNTAX = u"syntax"
R_UNIT = u"unit"
R_TYPE = u"type"
R_REF = u"ref"
R_DIV0 = u"div0"
R_SQRT = u"sqrt_neg"
R_CONVERT = u"convert"          # reserved for v2 conversions

# name -> (min args, max args; None = no maximum)
FUNCTIONS = {
    u"MIN": (2, None), u"MAX": (2, None),
    u"SQRT": (1, 1), u"ROOT": (2, 2), u"ABS": (1, 1),
    u"INT": (1, 1), u"FLOAT": (1, 1), u"STRING": (1, 1),
    u"LEN": (1, 1), u"IF": (3, 3), u"SENSITIVE": (1, 1),
}
KEYWORDS = set([u"AND", u"OR", u"ELIF", u"ELSE", u"TRUE", u"FALSE"]) | set(FUNCTIONS.keys())
UNITS = {u"m": 1, u"m2": 2, u"m\u00b2": 2, u"m3": 3, u"m\u00b3": 3}
SUFFIX = {1: u"m", 2: u"m\u00b2", 3: u"m\u00b3"}
CMP_OPS = (u"=", u"!=", u"<", u">", u"<=", u">=")
UNIT_FIX = u"both sides need the same unit; a count becomes a length with a unit, for example {Count} m"

_NUMBER = re.compile(u"[0-9]+(?:\\.[0-9]+)?")
_WORD = re.compile(u"[A-Za-z0-9_\u00b2\u00b3]+")
_IDENT = re.compile(u"[A-Za-z_][A-Za-z0-9_]*$")
_OPS = [u"!=", u"<=", u">=", u"==", u"<>", u"=", u"<", u">",
        u"+", u"-", u"*", u"/", u"%", u"^", u"(", u")", u","]
_FIELD_RE = re.compile(u"\\{([^{}]*)\\}")
_CAPS_SCAN = re.compile(u'"(?:[^"]|"")*"|\\{[^{}]*\\}|[A-Za-z_][A-Za-z0-9_]*')


# ------------------------------------------------------------------------------------------- errors
class FormulaError(Exception):
    def __init__(self, pos, reason, message, fix=u""):
        Exception.__init__(self, message)
        self.pos = pos
        self.reason = reason
        self.message = message
        self.fix = fix


class Tok(object):
    def __init__(self, kind, value, pos, raw=u""):
        self.kind = kind    # num | text | field | name | unit | op | end
        self.value = value
        self.pos = pos
        self.raw = raw


class Node(object):
    def __init__(self, kind, pos, **kw):
        self.kind = kind    # num | text | bool | field | call | bin | neg | unitize
        self.pos = pos
        self.__dict__.update(kw)


# ---------------------------------------------------------------------------------------------- types
class Ty(object):
    """kind: num | text | bool. exp: length exponent of a number (m=1, m2=2, m3=3, count=0)."""

    def __init__(self, kind, exp=0, count=False):
        self.kind = kind
        self.exp = exp
        self.count = bool(count) and exp == 0


def num(exp, count=False):
    return Ty(u"num", exp, count)


def unit_text(ty):
    if ty.kind == u"text":
        return u"text"
    if ty.kind == u"bool":
        return u"TRUE or FALSE"
    if ty.exp == 0:
        return u"count" if ty.count else u"unitless"
    return SUFFIX.get(ty.exp, u"m^%d" % ty.exp)


def ty_of_field(kind):
    """Field kind -> type. Units follow v1: length m, area m2, volume m3, integer count."""
    if kind == u"length":
        return num(1)
    if kind == u"area":
        return num(2)
    if kind == u"volume":
        return num(3)
    if kind == u"integer":
        return num(0, True)
    if kind == u"number":
        return num(0)
    if kind == u"yesno":
        return Ty(u"bool")
    return Ty(u"text")          # text and elementid


def field_kind(ty):
    """Field kind and base unit label for a checked result type. Units are base units (m, m2, m3),
    so the label of a dimensioned result is its base unit; None when there is no dimension."""
    if ty.kind == u"text":
        return u"text", None
    if ty.kind == u"bool":
        return u"yesno", None
    if ty.exp == 0:
        return (u"integer" if ty.count else u"number"), None
    known = {1: (u"length", u"m"), 2: (u"area", u"m\u00b2"), 3: (u"volume", u"m\u00b3")}
    return known.get(ty.exp) or (u"number", None)


# ---------------------------------------------------------------------------------------- tokenizer
def _describe(t):
    if t.kind == u"end":
        return u"the end of the formula"
    if t.kind == u"num":
        return u"the number %s" % t.raw
    if t.kind == u"text":
        return u"a text"
    if t.kind == u"field":
        return u"the field {%s}" % t.value
    if t.kind == u"unit":
        return u"the unit %s" % t.raw
    return u"'%s'" % t.raw


def _tokenize(text):
    toks = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == u'"':
            start = i
            i += 1
            buf = []
            while True:
                if i >= n:
                    raise FormulaError(start, R_SYNTAX, u"the text is not closed",
                                       u'add " at the end of the text')
                if text[i] == u'"':
                    if i + 1 < n and text[i + 1] == u'"':
                        buf.append(u'"')
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(text[i])
                i += 1
            toks.append(Tok(u"text", u"".join(buf), start))
            continue
        if c == u"{":
            end = text.find(u"}", i + 1)
            if end < 0:
                raise FormulaError(i, R_SYNTAX, u"the field is not closed", u"add } after the field name")
            key = text[i + 1:end]
            if not key.strip() or u"{" in key:
                raise FormulaError(i, R_SYNTAX, u"empty or nested field",
                                   u"write the field name between { and }")
            toks.append(Tok(u"field", key, i))
            i = end + 1
            continue
        if c in u"0123456789":
            m = _NUMBER.match(text, i)
            toks.append(Tok(u"num", float(m.group(0)), i, m.group(0)))
            i = m.end()
            continue
        m = _WORD.match(text, i)
        if m:
            word = m.group(0)
            low = word.lower()
            if low in UNITS:
                toks.append(Tok(u"unit", UNITS[low], i, word))
            elif _IDENT.match(word):
                toks.append(Tok(u"name", word.upper(), i, word))
            else:
                raise FormulaError(i, R_SYNTAX, u"unknown word '%s'" % word,
                                   u"field names go between braces, for example {Width (m)}")
            i = m.end()
            continue
        op = None
        for cand in _OPS:
            if text.startswith(cand, i):
                op = cand
                break
        if op is None:
            raise FormulaError(i, R_SYNTAX, u"unexpected character '%s'" % c)
        if op in (u"==", u"<>"):
            raise FormulaError(i, R_SYNTAX, u"'%s' is not an operator here" % op,
                               u"use = for equal and != for not equal")
        toks.append(Tok(u"op", op, i, op))
        i += len(op)
    toks.append(Tok(u"end", None, n))
    return toks


# ------------------------------------------------------------------------------------------- parser
class _Parser(object):
    def __init__(self, toks):
        self.toks = toks
        self.i = 0

    def peek(self):
        return self.toks[self.i]

    def take(self):
        t = self.toks[self.i]
        if t.kind != u"end":
            self.i += 1
        return t

    @staticmethod
    def is_op(t, *ops):
        return t.kind == u"op" and t.value in ops

    @staticmethod
    def is_kw(t, kw):
        return t.kind == u"name" and t.value == kw

    @staticmethod
    def fail(t, msg, fix=u""):
        raise FormulaError(t.pos, R_SYNTAX, msg, fix)

    def parse(self):
        if self.peek().kind == u"end":
            self.fail(self.peek(), u"the formula is empty", u"type an expression, for example {Width} * {Height}")
        node = self.expr()
        t = self.peek()
        if t.kind != u"end":
            self.fail(t, u"unexpected %s" % _describe(t), u"check the operators and brackets around it")
        return node

    def expr(self):
        return self.or_()

    def or_(self):
        node = self.and_()
        while self.is_kw(self.peek(), u"OR"):
            t = self.take()
            node = Node(u"bin", t.pos, op=u"OR", left=node, right=self.and_())
        return node

    def and_(self):
        node = self.cmp()
        while self.is_kw(self.peek(), u"AND"):
            t = self.take()
            node = Node(u"bin", t.pos, op=u"AND", left=node, right=self.cmp())
        return node

    def cmp(self):
        node = self.add()
        t = self.peek()
        if t.kind == u"op" and t.value in CMP_OPS:
            self.take()
            node = Node(u"bin", t.pos, op=t.value, left=node, right=self.add())
            t2 = self.peek()
            if t2.kind == u"op" and t2.value in CMP_OPS:
                self.fail(t2, u"comparisons cannot be chained",
                          u"join two comparisons with AND, for example {Width} > 1 AND {Height} > 2")
        return node

    def add(self):
        node = self.mul()
        while self.is_op(self.peek(), u"+", u"-"):
            t = self.take()
            node = Node(u"bin", t.pos, op=t.value, left=node, right=self.mul())
        return node

    def mul(self):
        node = self.pow_()
        while self.is_op(self.peek(), u"*", u"/", u"%"):
            t = self.take()
            node = Node(u"bin", t.pos, op=t.value, left=node, right=self.pow_())
        return node

    def pow_(self):
        base = self.unary()
        t = self.peek()
        if self.is_op(t, u"^"):
            self.take()
            return Node(u"bin", t.pos, op=u"^", left=base, right=self.pow_())
        return base

    def unary(self):
        t = self.peek()
        if self.is_op(t, u"-"):
            self.take()
            return Node(u"neg", t.pos, arg=self.unary())
        return self.postfix()

    def postfix(self):
        node = self.primary()
        t = self.peek()
        if t.kind == u"unit":
            self.take()
            return Node(u"unitize", t.pos, arg=node, exp=t.value)
        return node

    def primary(self):
        t = self.take()
        if t.kind == u"num":
            return Node(u"num", t.pos, value=t.value, text=t.raw)
        if t.kind == u"text":
            return Node(u"text", t.pos, value=t.value)
        if t.kind == u"field":
            return Node(u"field", t.pos, key=t.value)
        if t.kind == u"unit":
            self.fail(t, u"the unit %s has no number or count in front of it" % t.raw,
                      u"put it after a number or a count field, for example 2 m or {Count} m")
        if t.kind == u"name":
            if t.value in (u"ELIF", u"ELSE"):
                self.fail(t, u"%s chains come in version 2" % t.value,
                          u"use IF(condition, true value, false value) and nest it for more cases")
            if t.value == u"LEN":
                self.fail(t, u"LEN is not available until version 2",
                          u"count the rows or characters another way for now")
            if t.value in (u"TRUE", u"FALSE"):
                return Node(u"bool", t.pos, value=(t.value == u"TRUE"))
            if self.is_op(self.peek(), u"("):
                if t.value in FUNCTIONS:
                    return self.call(t)
                names = u", ".join(sorted(FUNCTIONS.keys()))
                self.fail(t, u"unknown function %s" % t.raw, u"the functions are: %s" % names)
            if t.value in FUNCTIONS:
                self.fail(t, u"%s needs brackets, for example %s(...)" % (t.raw, t.raw.upper()))
            self.fail(t, u"unknown name '%s'" % t.raw, u"field names go between braces, for example {%s}" % t.raw)
        if self.is_op(t, u"("):
            node = self.expr()
            close = self.peek()
            if not self.is_op(close, u")"):
                self.fail(close, u"missing ) for the ( at position %d" % (t.pos + 1),
                          u"add ) to close the bracket")
            self.take()
            return node
        self.fail(t, u"unexpected %s" % _describe(t), u"write a number, a text, a field in {}, or a function")

    def call(self, name_tok):
        self.take()                                  # the (
        args = []
        if not self.is_op(self.peek(), u")"):
            args.append(self.expr())
            while self.is_op(self.peek(), u","):
                self.take()
                args.append(self.expr())
        close = self.peek()
        if not self.is_op(close, u")"):
            self.fail(close, u"expected , or ) in %s(...)" % name_tok.value, u"add ) to close the function")
        self.take()
        return Node(u"call", name_tok.pos, name=name_tok.value, args=args)


def parse(text):
    """-> expression tree. Raises FormulaError on the first syntax error."""
    return _Parser(_tokenize(text)).parse()


# ----------------------------------------------------------------------------------- literal helpers
def _lit(node):
    """Value of a literal (with minus sign and unit suffix allowed), else None."""
    if node.kind == u"num":
        return node.value
    if node.kind == u"unitize":
        return _lit(node.arg)
    if node.kind == u"neg":
        v = _lit(node.arg)
        return None if v is None else -v
    return None


def _is_zero(node):
    v = _lit(node)
    return v is not None and v == 0


def _int_lit(node):
    """Whole-number literal without a unit (exponents and root degrees), else None."""
    if node.kind == u"unitize":
        return None
    v = _lit(node)
    if v is None or v != int(v):
        return None
    return int(v)


def _is_sensitive(node):
    return node.kind == u"call" and node.name == u"SENSITIVE"


def _arity_text(lo, hi):
    if hi is None:
        return u"at least %d argument(s)" % lo
    if lo == hi:
        return u"%d argument(s)" % lo
    return u"%d to %d arguments" % (lo, hi)


# ------------------------------------------------------------------------------------------ checker
class Checked(object):
    def __init__(self):
        self.ast = None
        self.ty = None
        self.errors = []
        self.refs = set()           # field keys the formula uses

    @property
    def ok(self):
        return not self.errors


class _Checker(object):
    def __init__(self, fields, label_of):
        self.fields = dict((f.key, f) for f in fields)
        self.label_of = dict(label_of or {})
        self.key_of = dict((lab, k) for k, lab in self.label_of.items())
        self.errors = []
        self.refs = set()

    # ---- helpers
    def err(self, pos, reason, msg, fix=u""):
        self.errors.append(FormulaError(pos, reason, msg, fix))
        return None

    def resolve(self, name):
        if name in self.fields:
            return self.fields[name]
        k = self.key_of.get(name)
        return self.fields.get(k) if k is not None else None

    def suggest(self, name):
        pool = {}
        for k, f in self.fields.items():
            pool[self.label_of.get(k, k)] = self.label_of.get(k, k)
            pool.setdefault(k, self.label_of.get(k, k))
        match = difflib.get_close_matches(name, list(pool.keys()), 1, 0.5)
        return pool[match[0]] if match else None

    def _need_number(self, node, name):
        return self.err(node.pos, R_TYPE, u"%s needs numbers" % name,
                        u"use a number, a count, or a length, area or volume field")

    def t(self, node):
        return getattr(self, u"_" + node.kind)(node)

    # ---- leaves
    def _num(self, n):
        return num(0)

    def _text(self, n):
        return Ty(u"text")

    def _bool(self, n):
        return Ty(u"bool")

    def _field(self, n):
        f = self.resolve(n.key)
        if f is None:
            guess = self.suggest(n.key)
            fix = (u"did you mean {%s}?" % guess) if guess else u"check the field name; it must be a field of this table"
            return self.err(n.pos, R_REF, u"unknown field {%s}" % n.key, fix)
        self.refs.add(f.key)
        res = getattr(f, "result", None)           # a custom field carries the type of its own formula
        if res:
            return Ty(res[0], res[1], res[2])
        return ty_of_field(f.kind)

    def _unitize(self, n):
        a = self.t(n.arg)
        if a is None:
            return None
        if a.kind != u"num":
            return self.err(n.pos, R_TYPE, u"a unit only follows a number or a count field",
                            u"remove the unit")
        if a.exp != 0:
            return self.err(n.pos, R_UNIT, u"%s already has a unit" % unit_text(a),
                            u"remove the %s" % SUFFIX[n.exp])
        return num(n.exp)

    def _neg(self, n):
        x = self.t(n.arg)
        if x is None:
            return None
        if x.kind != u"num":
            return self._need_number(n, u"-")
        return num(x.exp, x.count)

    # ---- operators
    def _bin(self, n):
        if n.op in (u"AND", u"OR"):
            a = self.t(n.left)
            b = self.t(n.right)
            if a is None or b is None:
                return None
            if a.kind != u"bool" or b.kind != u"bool":
                return self.err(n.pos, R_TYPE, u"%s needs TRUE or FALSE on both sides" % n.op,
                                u"compare the values, for example {Width} > 0")
            return Ty(u"bool")
        if n.op in CMP_OPS:
            return self._cmp(n)
        if n.op == u"^":
            return self._power(n)
        return self._arith(n)

    def _cmp(self, n):
        l, r = n.left, n.right
        sens = False
        if _is_sensitive(l) and len(l.args) == 1:
            l = l.args[0]
            sens = True
        if _is_sensitive(r) and len(r.args) == 1:
            r = r.args[0]
            sens = True
        n.case_sensitive = sens
        if sens and n.op not in (u"=", u"!="):
            return self.err(n.pos, R_TYPE, u"SENSITIVE only works with = and !=",
                            u"use = or != with SENSITIVE, or remove it")
        a = self.t(l)
        b = self.t(r)
        if a is None or b is None:
            return None
        if sens and (a.kind != u"text" or b.kind != u"text"):
            return self.err(n.pos, R_TYPE, u"SENSITIVE only works on text",
                            u"remove SENSITIVE, or compare text values")
        if a.kind != b.kind:
            return self.err(n.pos, R_TYPE, u"cannot compare %s with %s" % (unit_text(a), unit_text(b)),
                            u"both sides must be the same kind of value")
        if a.kind == u"num" and a.exp != b.exp and not (_is_zero(l) or _is_zero(r)):
            return self.err(n.pos, R_UNIT, u"cannot compare %s with %s" % (unit_text(a), unit_text(b)),
                            u"both sides need the same unit")
        if a.kind == u"bool" and n.op not in (u"=", u"!="):
            return self.err(n.pos, R_TYPE, u"TRUE and FALSE only compare with = and !=",
                            u"use = or !=")
        return Ty(u"bool")

    
    def _arith(self, n):
        op = n.op
        a = self.t(n.left)
        b = self.t(n.right)
        if a is None or b is None:
            return None
        if op in (u"+", u"-") and a.kind == u"text" and b.kind == u"text":
            if op == u"-":
                return self.err(n.pos, R_TYPE, u"text cannot be subtracted", u"use + to join two texts")
            return Ty(u"text")
        if a.kind != u"num" or b.kind != u"num":
            return self.err(n.pos, R_TYPE, u"'%s' cannot work with %s and %s" % (op, unit_text(a), unit_text(b)),
                            u"use numbers on both sides; + also joins two texts")
        count = a.count or b.count
        if op in (u"/", u"%") and _is_zero(n.right):
            return self.err(n.right.pos, R_DIV0, u"division by zero",
                            u"use a divisor other than 0, or guard it with IF(...)")
        if op in (u"+", u"-", u"%") and a.exp != b.exp:
            if op != u"%" and _is_zero(n.right):
                return a
            if op != u"%" and _is_zero(n.left):
                return b
            return self.err(n.pos, R_UNIT, u"cannot combine %s and %s" % (unit_text(a), unit_text(b)), UNIT_FIX)
        if op in (u"+", u"-", u"%"):
            return num(a.exp, count)
        if op == u"*":
            return num(a.exp + b.exp, count)
        return num(a.exp - b.exp, count)            # /

    def _power(self, n):
        a = self.t(n.left)
        b = self.t(n.right)
        if a is None or b is None:
            return None
        if a.kind != u"num" or b.kind != u"num":
            return self.err(n.pos, R_TYPE, u"^ needs a number on both sides", u"for example {Width} ^ 2")
        if b.exp != 0:
            return self.err(n.right.pos, R_UNIT, u"the exponent must be a count or a plain number",
                            u"for example {Width} ^ 2")
        if a.exp == 0:
            return num(0, a.count)
        k = _int_lit(n.right)
        if k is None:
            return self.err(n.right.pos, R_UNIT,
                            u"the exponent of %s must be a whole number written in the formula" % unit_text(a),
                            u"for example {Width} ^ 2")
        return num(a.exp * k)

    # ---- functions
    def _root(self, n, x, arg, k):
        if x.kind != u"num":
            return self._need_number(n, n.name)
        v = _lit(arg)
        if v is not None and v < 0 and k % 2 == 0:
            return self.err(arg.pos, R_SQRT, u"%s of a negative number is not a real number" % n.name,
                            u"use a value of zero or more")
        if x.exp % k != 0:
            return self.err(n.pos, R_UNIT, u"%s of %s does not give a clean unit" % (n.name, unit_text(x)),
                            u"use a value whose unit exponent is a multiple of %d" % k)
        return num(x.exp // k, x.count)

    def _call(self, n):
        name = n.name
        if name == u"SENSITIVE":
            return self.err(n.pos, R_TYPE, u"SENSITIVE only works on one side of = or !=",
                            u'write SENSITIVE({Name}) = "text"')
        lo, hi = FUNCTIONS[name]
        if len(n.args) < lo or (hi is not None and len(n.args) > hi):
            return self.err(n.pos, R_SYNTAX, u"%s takes %s" % (name, _arity_text(lo, hi)),
                            u"check the number of arguments")
        ts = [self.t(a) for a in n.args]
        if any(t is None for t in ts):
            return None
        if name == u"ABS":
            x = ts[0]
            if x.kind != u"num":
                return self._need_number(n, name)
            return num(x.exp, x.count)
        if name == u"SQRT":
            return self._root(n, ts[0], n.args[0], 2)
        if name == u"ROOT":
            k = _int_lit(n.args[1])
            if k is None or k < 1:
                return self.err(n.args[1].pos, R_TYPE,
                                u"ROOT needs a whole number from 1 upwards as its second argument",
                                u"for example ROOT({Volume}, 3)")
            return self._root(n, ts[0], n.args[0], k)
        if name in (u"MIN", u"MAX"):
            for t in ts:
                if t.kind != u"num":
                    return self._need_number(n, name)
            exp = ts[0].exp
            if any(t.exp != exp for t in ts):
                return self.err(n.pos, R_UNIT,
                                u"%s needs all values in one unit: %s" % (name, u", ".join(unit_text(t) for t in ts)),
                                u"use values with the same unit")
            return num(exp, any(t.count for t in ts))
        if name in (u"INT", u"FLOAT"):
            x = ts[0]
            if x.kind == u"num":
                return num(x.exp, x.count)
            if x.kind == u"text":
                return num(0, True)                  # a text gives its length (a count)
            return self.err(n.args[0].pos, R_TYPE, u"%s needs a number or a text, not %s" % (name, unit_text(x)))
        if name == u"STRING":
            return Ty(u"text")
        if name == u"IF":
            c, a, b = ts
            if c.kind != u"bool":
                return self.err(n.args[0].pos, R_TYPE,
                                u"the condition of IF must be TRUE or FALSE, not %s" % unit_text(c),
                                u"compare the value, for example {Width} > 0")
            if a.kind != b.kind:
                return self.err(n.pos, R_TYPE,
                                u"both branches of IF need the same type: %s and %s" % (unit_text(a), unit_text(b)),
                                u"make both branches numbers, texts or booleans")
            if a.kind == u"num":
                if a.exp != b.exp:
                    return self.err(n.pos, R_UNIT,
                                    u"both branches of IF need the same unit: %s and %s" % (unit_text(a), unit_text(b)),
                                    u"use values with the same unit")
                return num(a.exp, a.count or b.count)
            return Ty(a.kind)
        return self.err(n.pos, R_SYNTAX, u"%s is not available" % name)


def check(text, fields, label_of=None):
    """Parse and check one formula.

    fields    : rs.fields (Field objects with .key and .kind)
    label_of  : rs.display_labels() (key -> label); labels are accepted inside {} as well as keys
    Returns Checked: .ok, .errors (FormulaError list), .ty (result type), .refs (field keys), .ast
    """
    res = Checked()
    try:
        res.ast = parse(text)
    except FormulaError as e:
        res.errors = [e]
        return res
    c = _Checker(fields, label_of)
    res.ty = c.t(res.ast)
    res.errors = c.errors
    res.refs = c.refs
    return res


def unit_of(ty):
    """Display unit of a checked result, for the table header and the cell format."""
    return unit_text(ty) if ty is not None else u""


# ---------------------------------------------------------------------------- keys, labels, editor
def key_ok(key):
    """A key is stored between { and }, so it may not contain braces."""
    return bool(key) and u"{" not in key and u"}" not in key


def to_stored(text, key_of_label):
    """Editor form ({Width (m)}) -> stored form ({@WIDTH}). Unknown names are left for check() to report."""
    return _FIELD_RE.sub(lambda m: u"{%s}" % key_of_label.get(m.group(1), m.group(1)), text)


def to_editor(text, label_of_key):
    """Stored form ({@WIDTH}) -> editor form ({Width (m)})."""
    return _FIELD_RE.sub(lambda m: u"{%s}" % label_of_key.get(m.group(1), m.group(1)), text)


def to_caps(text):
    """Keywords and function names in capitals. Text literals, fields in {} and units are left alone.

    The editor calls this on the word before the caret once a separator is typed (space, operator,
    bracket, comma or end), so a word that is still growing into a longer name (True_key) is untouched.
    """
    def rep(m):
        s = m.group(0)
        if s[0] in u'"{':
            return s
        return s.upper() if s.upper() in KEYWORDS else s
    return _CAPS_SCAN.sub(rep, text)