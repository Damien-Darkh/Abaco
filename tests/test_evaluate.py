# -*- coding: utf-8 -*-
"""Formula evaluator (Phase 5). Run: python3 tests/test_evaluate.py   (no Revit needed)

Formulas are written with the labels the editor shows, converted to stored form (keys) and checked, exactly
as the editor will do, then evaluated against a row given as {key: raw value}.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from abaco.records import Field
from abaco import formula as F
from abaco import evaluate as E
from abaco.evaluate import NONE

FIELDS = [
    Field(u"@WIDTH", u"Width (m)", "element", "length"),
    Field(u"@HEIGHT", u"Height (m)", "element", "length"),
    Field(u"@AREA", u"Area (m\u00b2)", "element", "area"),
    Field(u"@VOLUME", u"Volume (m\u00b3)", "element", "volume"),
    Field(u"@COUNT", u"Count", "group", "integer"),
    Field(u"@RATIO", u"Ratio", "element", "number"),
    Field(u"@NAME", u"Type Name", "type", "text"),
    Field(u"@MARK", u"Type Mark", "type", "text"),
    Field(u"@LOAD", u"Load Bearing", "element", "yesno"),
]
LABELS = dict((f.key, f.label) for f in FIELDS)
KEY_OF = dict((f.label, f.key) for f in FIELDS)
KINDS = dict((f.key, f.kind) for f in FIELDS)

ROW = {u"@WIDTH": 2.0, u"@HEIGHT": 3.0, u"@AREA": 6.0, u"@VOLUME": 8.0, u"@COUNT": 3, u"@RATIO": 0.5,
       u"@NAME": u"Brick wall", u"@MARK": u"A1", u"@LOAD": u"Yes"}


def tree(text):
    r = F.check(F.to_stored(text, KEY_OF), FIELDS, LABELS)
    assert not r.errors, (text, [(e.reason, e.message) for e in r.errors])
    return r.ast


def run(text, **over):
    """Evaluate with ROW plus overrides given by key without '@' (width=..., count=...)."""
    row = dict(ROW)
    for k, v in over.items():
        row[u"@" + k.upper()] = v
    return E.evaluate(tree(text), lambda key: row[key], KINDS.get)


def err(v, reason):
    assert isinstance(v, E.Err), v
    assert v.reason == reason, (v.reason, v.message)


def close(a, b, tol=1e-9):
    return abs(a - b) < tol


# ----------------------------------------------------------------------------------------- arithmetic
def test_arithmetic_precedence_and_signs():
    assert run(u"1 + 2 * 3") == 7.0
    assert run(u"(1 + 2) * 3") == 9.0
    assert run(u"10 - 4 - 3") == 3.0
    assert run(u"7 / 2") == 3.5
    assert run(u"2 ^ 3 ^ 2") == 512.0                 # right-associative
    assert run(u"2 ^ -1") == 0.5
    assert run(u"-2 ^ 2") == 4.0                      # unary minus binds tighter than ^ in this grammar
    assert run(u"-{Width (m)} + 5 m") == 3.0
    assert run(u"7 % 3") == 1.0 and run(u"-7 % 3") == 2.0 and run(u"7 % -3") == -2.0
    assert run(u"{Width (m)} * {Height (m)}") == 6.0
    assert run(u"{Area (m\u00b2)} / {Count}") == 2.0
    assert all(isinstance(run(t), float) for t in (u"1 + 2", u"{Count} + 1", u"7 % 3"))


# --------------------------------------------------------------------------------- division by zero
def test_division_by_zero_is_an_error_that_propagates():
    err(run(u"{Width (m)} / {Count}", count=0), u"div0")
    err(run(u"{Count} % {Count}", count=0), u"div0")
    v = run(u"({Width (m)} / {Count} + 1 m) * 2 - {Height (m)}", count=0)
    err(v, u"div0")                                    # carried through further arithmetic
    err(run(u"ABS({Width (m)} / {Count})", count=0), u"div0")
    err(run(u"{Count} ^ -1", count=0), u"div0")        # 0 to a negative power is a division by zero


# ------------------------------------------------------------------------------------------------ NONE
def test_none_in_none_out():
    for text in (u"{Width (m)} * 2", u"-{Width (m)}", u"{Width (m)} + {Height (m)}", u"{Width (m)} / {Count}",
                 u"{Width (m)} % 2 m", u"{Width (m)} ^ 2", u"ABS({Width (m)})", u"SQRT({Area (m\u00b2)})",
                 u"MIN({Width (m)}, 1 m)", u"MAX(1 m, {Width (m)})", u"INT({Width (m)})", u"FLOAT({Width (m)})",
                 u"ROOT({Volume (m\u00b3)}, 3)"):
        assert run(text, width=None, area=None, volume=None) is NONE, text
    assert run(u"{Width (m)} = 2 m", width=None) is NONE
    assert run(u"{Width (m)} != 2 m", width=None) is NONE      # NONE, not true
    assert run(u"{Width (m)} < 2 m", width=None) is NONE
    assert run(u"{Type Name} = \"x\"", name=None) is NONE
    assert run(u"{Type Name} + \"x\"", name=None) is NONE
    assert run(u"STRING({Width (m)})", width=None) is NONE


def test_and_or_with_none():
    n = u"{Width (m)} > 1 m"                                  # NONE when Width is empty
    assert run(u"FALSE AND " + n, width=None) is False        # FALSE AND x is FALSE
    assert run(u"TRUE OR " + n, width=None) is True           # TRUE OR x is TRUE
    assert run(n + u" AND TRUE", width=None) is NONE
    assert run(u"TRUE AND " + n, width=None) is NONE
    assert run(n + u" OR FALSE", width=None) is NONE
    assert run(u"FALSE OR " + n, width=None) is NONE
    assert run(u"TRUE AND FALSE") is False and run(u"TRUE AND TRUE") is True
    assert run(u"FALSE OR FALSE") is False and run(u"FALSE OR TRUE") is True


def test_error_wins_over_none_in_both_orders():
    bad = u"{Area (m\u00b2)} / {Count} / {Width (m)}"          # m, div0 when Count is 0
    e1 = run(u"{Height (m)} + " + bad, count=0, height=None)
    e2 = run(bad + u" + {Height (m)}", count=0, height=None)
    err(e1, u"div0")
    err(e2, u"div0")
    assert run(u"{Height (m)} + " + bad, count=2, height=None) is NONE
    c = u"({Height (m)} > 1 m)"
    d = u"({Area (m\u00b2)} / {Count} > 1 m\u00b2)"
    err(run(c + u" AND " + d, count=0, height=None), u"div0")
    err(run(d + u" OR " + c, count=0, height=None), u"div0")
    err(run(u"MIN({Height (m)}, " + bad + u")", count=0, height=None), u"div0")
    err(run(u"MAX(" + bad + u", {Height (m)})", count=0, height=None), u"div0")


# -------------------------------------------------------------------------------------------- equality
def test_equality_tolerance_and_exact_ordering():
    assert run(u"{Width (m)} = 2.0000005 m") is True           # 5e-7 apart: equal
    assert run(u"{Width (m)} = 2.000002 m") is False           # 2e-6 apart: not equal
    assert run(u"{Width (m)} != 2.0000005 m") is False
    assert run(u"{Width (m)} != 2.000002 m") is True
    assert run(u"{Width (m)} < 2.0000005 m") is True           # ordering is exact
    assert run(u"{Width (m)} >= 2.0000005 m") is False
    assert run(u"{Width (m)} <= 2 m") is True and run(u"{Width (m)} > 2 m") is False
    assert run(u"{Count} >= 3") is True and run(u"{Count} < 3") is False


# ----------------------------------------------------------------------------------------------- IF
def test_if_is_lazy_and_none_condition_gives_none():
    f = u"IF({Count} != 0, {Width (m)} / {Count}, 0 m)"
    assert run(f, count=0) == 0.0                              # the division is never evaluated
    assert run(f, count=4) == 0.5
    assert run(u"IF({Width (m)} > 1 m, 1, 2)", width=None) is NONE
    err(run(u"IF({Area (m\u00b2)} / {Count} > 1 m\u00b2, 1, 2)", count=0), u"div0")
    assert run(u"IF({Load Bearing}, \"yes\", \"no\")") == u"yes"
    assert run(u"IF({Load Bearing}, 1, 2)", load=u"No") == 2.0
    assert run(u"IF({Load Bearing}, 1, 2)", load=None) is NONE
    assert run(u"IF(TRUE, {Width (m)}, {Height (m)})", width=None) is NONE   # NONE value of the chosen branch


# ------------------------------------------------------------------------------------------- MIN / MAX
def test_min_max():
    assert run(u"MIN({Width (m)}, {Height (m)}, 5 m)") == 2.0
    assert run(u"MAX({Width (m)}, {Height (m)}, 5 m)") == 5.0
    assert run(u"MIN({Count}, 7)") == 3.0
    assert run(u"MIN({Width (m)}, {Height (m)})", height=None) is NONE
    err(run(u"MIN({Width (m)}, {Area (m\u00b2)} / {Count} / {Width (m)})", count=0), u"div0")


# ------------------------------------------------------------------------------------- SQRT / ROOT
def test_sqrt_and_root():
    assert run(u"SQRT(16)") == 4.0 and run(u"SQRT({Area (m\u00b2)})") == 6.0 ** 0.5
    err(run(u"SQRT({Area (m\u00b2)})", area=-4.0), u"sqrt_neg")
    assert run(u"ROOT({Volume (m\u00b3)}, 3)") == 2.0
    assert run(u"ROOT({Volume (m\u00b3)}, 3)", volume=64.0) == 4.0       # exact, not 3.9999999999999996
    assert close(run(u"ROOT({Volume (m\u00b3)}, 3)", volume=-27.0), -3.0)  # odd root takes negatives
    err(run(u"ROOT({Area (m\u00b2)}, 2)", area=-4.0), u"sqrt_neg")
    assert run(u"ROOT({Area (m\u00b2)}, 1)", area=-4.0) == -4.0 and run(u"ROOT(81, 4)") == 3.0


# ------------------------------------------------------------------------------------------------ INT
def test_int_rounds_half_away_from_zero():
    for text, want in ((u"INT(1.9)", 2.0), (u"INT(1.4)", 1.0), (u"INT(2.5)", 3.0), (u"INT(-2.5)", -3.0),
                       (u"INT(-1.4)", -1.0), (u"INT(235.0587)", 235.0), (u"INT(0.5)", 1.0), (u"INT(0)", 0.0)):
        assert run(text) == want, text
    assert str(run(u"INT(-0.2)")) == "0.0"                      # never -0.0
    assert run(u"INT({Width (m)} * 1.25)") == 3.0 and run(u"INT({Area (m\u00b2)} / {Count})") == 2.0


def test_int_and_float_of_text_give_its_length():
    assert run(u"INT(\"Building\")") == 8.0
    assert run(u"INT({Type Name})") == 10.0
    assert run(u"FLOAT(\"Building\")") == 8.0 and isinstance(run(u"FLOAT(\"Building\")"), float)
    assert run(u"FLOAT(2)") == 2.0 and run(u"FLOAT({Width (m)})") == 2.0
    assert run(u"INT(\"\")") == 0.0


# --------------------------------------------------------------------------------------------- STRING
def test_string_forms():
    assert run(u"STRING(2.00)") == u"2.00"                      # a literal keeps its typed text
    assert run(u"STRING(6458494846.6544584546464872)") == u"6458494846.6544584546464872"
    assert run(u"STRING(-2.50)") == u"-2.50" and run(u"STRING(2.00 m)") == u"2.00"
    assert run(u"STRING({Width (m)})") == u"2"                  # field 2.0 reads back as 2
    assert run(u"STRING({Ratio})") == u"0.5"
    assert run(u"STRING(0.1 + 0.2)") == u"0.30000000000000004"
    assert run(u"STRING({Count} * 1.5)") == u"4.5"
    assert run(u"STRING({Width (m)} * 0)") == u"0" and run(u"STRING(-0.0 * 1)") == u"0"
    assert run(u"STRING({Load Bearing})") == u"TRUE" and run(u"STRING(1 > 2)") == u"FALSE"
    assert run(u"STRING({Type Mark})") == u"A1"
    err(run(u"STRING({Width (m)} / {Count})", count=0), u"div0")
    assert run(u"STRING({Width (m)})", width=None) is NONE


# ------------------------------------------------------------------------------------------------ text
def test_text_join_and_comparison():
    assert run(u"{Type Mark} + \"-\" + {Type Name}") == u"A1-Brick wall"
    assert run(u"{Type Mark} + STRING({Count})") == u"A13"
    assert run(u"{Type Mark} = \"a1\"") is True                 # case-insensitive
    assert run(u"{Type Mark} != \"a1\"") is False
    assert run(u"SENSITIVE({Type Mark}) = \"a1\"") is False     # case-sensitive
    assert run(u"SENSITIVE({Type Mark}) = \"A1\"") is True
    assert run(u"\"A1\" = SENSITIVE({Type Mark})") is True
    assert run(u"SENSITIVE({Type Mark}) != \"a1\"") is True
    assert run(u"\"a\" < \"B\"") is True
    assert run(u"{Type Name} = \"BRICK WALL\"") is True


# ----------------------------------------------------------------------------------------------- yes/no
def test_yes_no_fields_are_booleans():
    assert run(u"{Load Bearing}") is True
    assert run(u"{Load Bearing}", load=u"yes") is True and run(u"{Load Bearing}", load=u" NO ") is False
    assert run(u"{Load Bearing}", load=u"No") is False
    assert run(u"{Load Bearing}", load=u"Maybe") is NONE       # any other text
    assert run(u"{Load Bearing}", load=None) is NONE
    assert run(u"{Load Bearing} = TRUE", load=u"Yes") is True
    assert run(u"{Load Bearing} AND {Count} > 2") is True
    assert run(u"{Load Bearing} AND {Count} > 2", load=u"No") is False


# --------------------------------------------------------------------------------------- bad row data
def test_missing_and_wrongly_typed_row_values():
    e = E.evaluate(tree(u"{Width (m)} + 1 m"), lambda k: ROW[k] if k != u"@WIDTH" else (_ for _ in ()).throw(KeyError(k)))
    err(e, u"ref")
    err(run(u"{Width (m)} + 1 m", width=u"Varies"), u"type")
    err(run(u"{Type Mark}", **{"mark": 5}), u"type")
    assert run(u"{Count} + 1", count=2) == 3.0                  # ints from the pipeline become floats
    # without kind_of the Python type decides
    assert E.evaluate(tree(u"{Width (m)} + 1 m"), lambda k: 4) == 5.0


# --------------------------------------------------------------------------------------- row values
def test_formulas_see_the_row_values():
    grouped = {u"@COUNT": 3, u"@AREA": 12.0, u"@WIDTH": 0.9}         # 3 elements, summed area 12
    get = lambda k: grouped[k]
    assert E.evaluate(tree(u"{Count}"), get, KINDS.get) == 3.0
    assert E.evaluate(tree(u"{Area (m\u00b2)} / {Count}"), get, KINDS.get) == 4.0      # average per element
    assert E.evaluate(tree(u"{Area (m\u00b2)} * 2"), get, KINDS.get) == 24.0           # doubles the sum


def test_live_recompute_has_no_cache_between_calls():
    t = tree(u"{Area (m\u00b2)} / {Count}")
    rows = [{u"@AREA": 12.0, u"@COUNT": 3}, {u"@AREA": 12.0, u"@COUNT": 4}, {u"@AREA": 12.0, u"@COUNT": 0}]
    first = [E.evaluate(t, (lambda r: lambda k: r[k])(r), KINDS.get) for r in rows]
    assert first[0] == 4.0 and first[1] == 3.0
    err(first[2], u"div0")
    rows[0][u"@COUNT"] = 6                                      # the table was rebuilt with other groups
    assert E.evaluate(t, lambda k: rows[0][k], KINDS.get) == 2.0
    assert E.evaluate(t, lambda k: rows[1][k], KINDS.get) == 3.0


# ------------------------------------------------------------------------------ calculated fields
def test_calculated_field_using_another():
    per = tree(u"{Area (m\u00b2)} / {Count}")                    # m2
    deps = {u"PER": set([u"@AREA", u"@COUNT"]), u"TWICE": set([u"PER"])}
    twice = F.check(u"{PER} * 2 m\u00b2", FIELDS, LABELS)         # PER is not a catalogue field here: unknown ref
    assert twice.errors and twice.errors[0].reason == "ref"
    order = E.topological_order(deps)
    assert order == [u"PER", u"TWICE"]
    from_ast = {u"PER": per, u"TWICE": F.parse(u"{PER} * 2")}
    got = E.calculate_row(from_ast, order, lambda k: ROW[k], KINDS.get)
    assert got == {u"PER": 2.0, u"TWICE": 4.0}
    bad_row = dict(ROW, **{u"@COUNT": 0})
    got = E.calculate_row(from_ast, order, lambda k: bad_row[k], KINDS.get)
    err(got[u"PER"], u"div0")
    err(got[u"TWICE"], u"div0")                                  # the failed field poisons its users
    assert E.to_cell(got[u"TWICE"]) == u"#ERROR"


def test_circular_references_are_refused_with_the_loop():
    deps = {u"A": set([u"B"]), u"B": set([u"C"]), u"C": set([u"A", u"@WIDTH"])}
    try:
        E.topological_order(deps, {u"A": u"Alpha", u"B": u"Beta", u"C": u"Gamma"})
        raise AssertionError("expected a circular reference")
    except F.FormulaError as ex:
        assert ex.reason == "ref" and u"circular reference: {Alpha} -> {Beta} -> {Gamma} -> {Alpha}" in ex.message, ex.message
    try:
        E.topological_order({u"A": set([u"A"])})
        raise AssertionError("expected a circular reference")
    except F.FormulaError as ex:
        assert u"{A} -> {A}" in ex.message
    assert E.topological_order({u"B": set([u"A"]), u"A": set(), u"C": set([u"A", u"B"])}) == [u"A", u"B", u"C"]


# --------------------------------------------------------------------------------------- display, dry run
def test_cell_display():
    assert E.to_cell(NONE) == u"#NONE" and E.to_cell(E.Err(u"div0", u"x")) == u"#ERROR"
    assert E.to_cell(True) == u"#TRUE" and E.to_cell(False) == u"#FALSE"
    assert E.to_cell(2.5) == 2.5 and E.to_cell(u"abc") == u"abc"


def test_dry_run_counts_by_reason_with_three_examples():
    t = tree(u"{Area (m\u00b2)} / {Count}")
    counts = [0, 3, 0, 0, 2, 0, 0]
    rows = [(i, (lambda c: lambda k: {u"@AREA": 6.0, u"@COUNT": c}[k])(c)) for i, c in enumerate(counts, start=10)]
    res = E.dry_run(t, rows, KINDS.get)
    assert res.total == 7 and res.errors == 5 and res.by_reason == {u"div0": 5} and not res.ok
    assert [e[0] for e in res.examples] == [10, 12, 13]
    s = res.summary(u"Per element")
    assert u"5 of 7 rows give #ERROR" in s and u"div0: 5" in s
    clean = E.dry_run(tree(u"{Width (m)} * 2"), [(1, lambda k: ROW[k]), (2, lambda k: None)], KINDS.get)
    assert clean.ok and clean.none == 1 and u"no errors in 2 rows" in clean.summary(u"x")
    mixed = E.dry_run(tree(u"SQRT({Area (m\u00b2)}) / {Count}"),
                      [(1, lambda k: {u"@AREA": -1.0, u"@COUNT": 1}[k]), (2, lambda k: {u"@AREA": 4.0, u"@COUNT": 0}[k])],
                      KINDS.get)
    assert mixed.by_reason == {u"sqrt_neg": 1, u"div0": 1}


def test_every_reason_code_is_produced():
    seen = set()
    for text in (u"1 +", u"{Width (m)} + {Area (m\u00b2)}", u"{Type Mark} + 1", u"{Nope}", u"1 / 0", u"SQRT(-4)"):
        r = F.check(text, FIELDS, LABELS)
        seen.update(e.reason for e in r.errors)
    for text, kw in ((u"{Width (m)} / {Count}", {"count": 0}), (u"SQRT({Area (m\u00b2)})", {"area": -1.0}),
                     (u"{Width (m)} + 1 m", {"width": u"x"})):
        seen.add(run(text, **kw).reason)
    seen.add(E.evaluate(tree(u"{Width (m)}"), lambda k: (_ for _ in ()).throw(KeyError(k)), KINDS.get).reason)
    assert set([F.R_SYNTAX, F.R_UNIT, F.R_TYPE, F.R_REF, F.R_DIV0, F.R_SQRT]) <= seen, seen
    err(run(u"{Count} ^ 400", count=10), u"range")             # the one code added here


def test_int_edge_below_half():
    ev = E._Eval(None, None, {})
    assert ev.f_int([0.49999999999999994]) == 0.0          # a + 0.5 would round this up to 1
    assert ev.f_int([-0.49999999999999994]) == 0.0
    assert ev.f_int([2.5]) == 3.0 and ev.f_int([-2.5]) == -3.0


def test_string_never_uses_exponent_notation():
    assert E._shortest(0.00001) == u"0.00001"
    assert E._shortest(1e-7) == u"0.0000001"
    assert E._shortest(1e22) == u"10000000000000000000000"
    assert E._shortest(2.0) == u"2" and E._shortest(-2.5) == u"-2.5"
    assert E._shortest(0.1 + 0.2) == u"0.30000000000000004"
    assert E._shortest(100.0) == u"100"                    # trailing zeros of a whole number are kept


def test_and_or_decider_wins_on_either_side_even_against_none():
    n = u"{Width (m)} > 1 m"                                   # NONE when Width is empty
    assert run(n + u" AND FALSE", width=None) is False         # NONE AND FALSE is FALSE
    assert run(n + u" OR TRUE", width=None) is True            # NONE OR TRUE is TRUE
    assert run(n + u" AND TRUE", width=None) is NONE           # no decider: still NONE
    assert run(n + u" OR FALSE", width=None) is NONE
    bad = u"{Area (m\u00b2)} / {Count} > 1 m" + u"\u00b2"             # div0 when Count is 0: an error is never hidden
    assert E.is_error(run(bad + u" AND FALSE", count=0))
    assert E.is_error(run(bad + u" OR TRUE", count=0))


def test_circular_reference_error_carries_the_loop_keys():
    try:
        E.topological_order({"a": set(["b"]), "b": set(["a"]), "c": set()})
        assert False
    except F.FormulaError as ex:
        assert set(ex.loop) == set(["a", "b"]) and ex.reason == F.R_REF

def test_varies_propagates_with_the_priority_none_then_varies():
    V = E.VARIES
    assert run(u"{Width (m)} * 2", width=V) is V
    assert run(u"{Width (m)} + {Height (m)}", width=V, height=None) is NONE      # NONE decides for every element
    err(run(u"{Width (m)} * ({Area (m\u00b2)} / {Count})", width=V, count=0), u"div0")
    assert run(u"STRING({Width (m)})", width=V) is V


def test_varies_with_and_or_and_if():
    V = E.VARIES
    v = u"{Width (m)} > 1 m"
    assert run(u"FALSE AND " + v, width=V) is False       # the decider wins
    assert run(v + u" OR TRUE", width=V) is True
    assert run(v + u" AND TRUE", width=V) is V
    assert run(u"IF(" + v + u", 1, 2)", width=V) is V
    assert run(u"IF(TRUE, {Width (m)}, 0 m)", width=V) is V
    assert run(u"IF(FALSE, {Width (m)}, 0 m)", width=V) == 0.0     # the unused branch is never evaluated


def test_varies_cell_text_uses_the_label():
    assert E.to_cell(E.VARIES) == u"Varies" and E.to_cell(E.VARIES, u"Varia") == u"Varia"

def test_if_field_is_a_presence_test():
    V = E.VARIES
    assert run(u"IF({Width (m)}, 1, 2)") == 1.0
    assert run(u"IF({Width (m)}, 1, 2)", width=None) == 2.0
    assert run(u"IF({Width (m)}, 1, 2)", width=0.0) == 1.0          # 0 is a value
    assert run(u"IF({Width (m)}, 1, 2)", width=V) is V
    assert run(u"IF({Type Name}, \"y\", \"n\")", name=u"") == u"n"  # empty text is empty
    assert run(u"IF({Load Bearing}, 1, 2)", load=None) is NONE     # Yes/No uses its value
    assert run(u"IF({Load Bearing}, 1, 2)", load=u"No") == 2.0

if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for n, f in tests:
        f()
        print("ok   " + n)
    print("%d tests passed" % len(tests))
