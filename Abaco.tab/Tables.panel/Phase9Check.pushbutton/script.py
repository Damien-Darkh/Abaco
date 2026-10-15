# -*- coding: utf-8 -*-
"""Phase 9 check (temporary dev button): saved settings on the real model.

Writes ONLY to a temporary folder, never to the user's real tables.json.
Checks:
  - round trip of fields, levels, custom fields, filter, row numbers, appearance, labels and output
  - the table built from the restored settings equals the table built from the original
  - missing fields are kept, reported and shown as #NOT_IN_PROJECT
  - corrupt file is moved aside, newer file blocks saving and is not overwritten
  - Save writes no temporary file
  - schedule and takeoff of the same category are stored apart
  - an old entry with removed keys (titleBlock, prefix) still loads
Delete this button when Phase 9 is done.
"""
import copy
import io
import os
import shutil
import tempfile
import traceback

from pyrevit import forms, script, revit

from abaco import revit_reader as rr
from abaco import pipeline as P
from abaco import runner
from abaco import settings_store as SS
from abaco import filters
from abaco.records import K_WIDTH, K_HEIGHT, K_LAYER_THICKNESS

doc = revit.doc
out = script.get_output()

TEST_DIR = tempfile.mkdtemp(prefix="abaco_phase9_")
OUT_OPTS = {"tableName": u"Abaco Doors", "excelPath": u"C:\\test\\a.xlsx", "titleBlock": u"TB : A1",
            "prefix": u"AM", "pageHeight": u"490"}
DEF_OPTS = {"tableName": u"default", "excelPath": u"d.xlsx", "titleBlock": None,
            "prefix": u"AM", "pageHeight": u"490"}

results = []


# ------------------------------------------------------------------ reporting
def check(name, ok, detail=u""):
    results.append((name, bool(ok)))
    out.print_md(u"- **%s** %s%s" % (u"PASS" if ok else u"FAIL", name, (u" - " + detail) if detail else u""))


def info(text):
    out.print_md(u"- INFO %s" % text)


def guarded(name, fn, *args):
    try:
        fn(*args)
    except Exception:
        check(name + u" ran without error", False)
        out.print_md(u"```\n%s\n```" % traceback.format_exc())


def _quiet(msg):
    pass


def find_category(name):
    for n, count, cat in rr.list_model_categories(doc):
        if n == name:
            return cat
    return None


def path_in_test(name):
    return os.path.join(TEST_DIR, name)


def write_text(path, text):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ------------------------------------------------------------- settings used
def tweak(s, ttype, formula):
    """Changes every part of the settings, so the round trip has something to lose."""
    s["title"] = u"Phase 9 check"
    s["fields"][0]["heading"] = u"First heading"
    s["fields"][0]["align"] = "center"
    s["levels"] = s["levels"][:1]
    s["levels"][0]["dir"] = "desc"
    s["levels"][0]["gap"] = True
    s["grandTotals"] = True
    s["rowNumbers"] = {"on": True, "heading": u"#"}
    s["appearance"]["elements"]["data"]["bold"] = True
    s["appearance"]["zebra"]["on"] = True
    s["labels"]["varies"] = u"Varia"
    s["custom"] = [{"key": u"calc:1", "name": u"Check Calc", "formula": formula}]
    s["fields"].append(P.field_setting(u"calc:1"))
    s["filter"] = {"match": "all", "conditions": [{"key": K_WIDTH, "op": "gt", "value": u"0.1"}]}
    return s


def settings_for(rs, ttype):
    return P.default_settings(rs, ttype, u"")


def known_keys_for(rs, settings):
    """Project fields plus the custom fields of the settings. The window must do the same, because
    custom fields are only attached to the catalogue after the settings are restored."""
    keys = set(f.key for f in rs.fields)
    keys |= set(d["key"] for d in settings.get("custom", []))
    return keys


def same_matrix(a, b):
    return a.table.to_matrix() == b.table.to_matrix()


# ----------------------------------------------------------- round trip
def round_trip(label, cat, ttype, formula):
    out.print_md(u"## Round trip: %s (%s)" % (label, ttype))
    rs = rr.read_category(doc, cat, _quiet)
    key = rr.category_key(cat)
    info(u"category key %s (localised name: %s)" % (key, cat.Name))

    original = tweak(settings_for(rs, ttype), ttype, formula)
    store = SS.empty_store()
    SS.put_saved(store, key, ttype, original, OUT_OPTS)
    path = path_in_test(u"rt_%s_%s.json" % (key, ttype))
    SS.write_file(path, store)

    store2, msg = SS.read_file(path)
    check(u"%s: file read back with no message" % label, msg == u"", msg)
    saved = SS.get_saved(store2, key, ttype)
    check(u"%s: entry found under its key" % label, saved is not None)
    if saved is None:
        return

    known = known_keys_for(rs, original)
    got, out_opts, notes = SS.restore(saved, settings_for(rs, ttype), DEF_OPTS, known)

    check(u"%s: fields restored" % label, got["fields"] == original["fields"])
    check(u"%s: levels restored" % label, got["levels"] == original["levels"])
    check(u"%s: custom fields restored" % label, got["custom"] == original["custom"])
    check(u"%s: filter restored" % label,
          got["filter"] == filters.normalize_settings(original["filter"]))
    check(u"%s: row numbers restored" % label, got["rowNumbers"] == original["rowNumbers"])
    check(u"%s: appearance restored" % label, got["appearance"] == original["appearance"])
    check(u"%s: labels restored" % label, got["labels"] == original["labels"])
    check(u"%s: title and options restored" % label,
          got["title"] == original["title"] and got["grandTotals"] == original["grandTotals"])
    check(u"%s: output options restored" % label,
          out_opts["tableName"] == OUT_OPTS["tableName"] and out_opts["excelPath"] == OUT_OPTS["excelPath"]
          and out_opts["pageHeight"] == OUT_OPTS["pageHeight"])
    check(u"%s: no restore notes for a project that has every field" % label, notes == [], u" | ".join(notes))

    res_a = runner.build_result(doc, rs, original, _quiet)
    res_b = runner.build_result(doc, rs, got, _quiet)
    check(u"%s: table from restored settings equals the original" % label, same_matrix(res_a, res_b))


# ------------------------------------------------------- missing fields
def run_missing_field():
    out.print_md(u"## Missing field kept and reported")
    cat = find_category(u"Doors")
    if cat is None:
        info(u"Doors not in the model: skipped")
        return
    rs = rr.read_category(doc, cat, _quiet)
    key = rr.category_key(cat)
    s = settings_for(rs, "schedule")
    s["fields"].append(P.field_setting(u"GONE_FROM_ANOTHER_PROJECT", heading=u"Old"))
    store = SS.empty_store()
    SS.put_saved(store, key, "schedule", s, OUT_OPTS)
    saved = SS.get_saved(store, key, "schedule")

    got, _, notes = SS.restore(saved, settings_for(rs, "schedule"), DEF_OPTS, known_keys_for(rs, s))
    check(u"missing field kept in the restored settings",
          u"GONE_FROM_ANOTHER_PROJECT" in [f["key"] for f in got["fields"]])
    check(u"missing field reported", any(u"not in this project" in n for n in notes), u" | ".join(notes))

    res = P.build_table(rs, got)
    m = res.excel.to_matrix()
    check(u"missing column heading kept", m[1][-1] == u"Old", u"got %s" % m[1][-1])
    data = [r for r in m[2:] if any(r)]
    check(u"missing column shows #NOT_IN_PROJECT", data and all(r[-1] == P.MARK_NOT_IN_PROJECT for r in data))


# ------------------------------------------------------- bad files
def run_bad_files():
    out.print_md(u"## Corrupt and newer files")

    p = path_in_test(u"corrupt.json")
    write_text(p, u"{bad json")
    store, msg = SS.read_file(p)
    check(u"corrupt file gives defaults and a message", store["saved"] == {} and u"could not be read" in msg)
    check(u"corrupt file moved aside", os.path.exists(p + SS.ASIDE_SUFFIX) and not os.path.exists(p))

    p2 = path_in_test(u"newer.json")
    write_text(p2, u'{"v": 2, "saved": {}}')
    store2, msg2 = SS.read_file(p2)
    check(u"newer file marks the store blocked", store2.get("blocked") is True and u"newer" in msg2)
    refused = False
    try:
        SS.write_file(p2, store2)
    except IOError:
        refused = True
    check(u"saving over a newer file is refused", refused)
    with io.open(p2, "r", encoding="utf-8") as f:
        check(u"newer file is unchanged", u'"v": 2' in f.read())


# ------------------------------------------------------- atomic write
def run_atomic_write():
    out.print_md(u"## Atomic write")
    p = path_in_test(u"atomic.json")
    SS.write_file(p, SS.empty_store())
    check(u"file written", os.path.exists(p))
    check(u"no temporary file left behind", not os.path.exists(p + ".tmp"))


# ----------------------------------------------- schedule and takeoff apart
def run_table_types():
    out.print_md(u"## Schedule and takeoff stored apart")
    cat = find_category(u"Walls")
    if cat is None:
        info(u"Walls not in the model: skipped")
        return
    rs = rr.read_category(doc, cat, _quiet)
    key = rr.category_key(cat)
    a = settings_for(rs, "schedule")
    a["title"] = u"Schedule one"
    b = settings_for(rs, "takeoff")
    b["title"] = u"Takeoff one"
    store = SS.empty_store()
    SS.put_saved(store, key, "schedule", a, OUT_OPTS)
    SS.put_saved(store, key, "takeoff", b, OUT_OPTS)
    check(u"two separate entries", len(store["saved"]) == 2)
    got_a, _, _ = SS.restore(SS.get_saved(store, key, "schedule"), settings_for(rs, "schedule"), DEF_OPTS, None)
    got_b, _, _ = SS.restore(SS.get_saved(store, key, "takeoff"), settings_for(rs, "takeoff"), DEF_OPTS, None)
    check(u"each table type keeps its own title", got_a["title"] == u"Schedule one" and got_b["title"] == u"Takeoff one")


# ----------------------------------------------- old file with removed keys
def run_old_file():
    out.print_md(u"## Old file with removed keys")
    cat = find_category(u"Doors")
    if cat is None:
        info(u"Doors not in the model: skipped")
        return
    rs = rr.read_category(doc, cat, _quiet)
    key = rr.category_key(cat)
    p = path_in_test(u"old.json")
    old = {"v": 1, "saved": {u"%s|schedule" % key: {
        "settings": {"title": u"Old title"},
        "output": {"tableName": u"Old name", "titleBlock": u"TB : X", "prefix": u"AM", "pageHeight": u"490"}}}}
    write_text(p, unicode_json(old))
    store, msg = SS.read_file(p)
    check(u"old file reads with no message", msg == u"", msg)
    got, opts, _ = SS.restore(SS.get_saved(store, key, "schedule"), settings_for(rs, "schedule"), DEF_OPTS,
                              known_keys_for(rs, settings_for(rs, "schedule")))
    check(u"old file title and table name kept", got["title"] == u"Old title" and opts["tableName"] == u"Old name")


def unicode_json(obj):
    import json
    return json.dumps(obj, indent=2)


# ------------------------------------------------------- real file
def run_real_file_info():
    out.print_md(u"## Real settings file (not changed)")
    p = SS.default_path()
    info(u"path: %s" % p)
    info(u"exists: %s" % (u"yes" if os.path.exists(p) else u"no (created by the first Save settings)"))


# ------------------------------------------------------------------ main
def main():
    out.print_md(u"# Phase 9 check: saved settings")
    out.print_md(u"Test files are in `%s` and are removed at the end. The real tables.json is not touched." % TEST_DIR)

    doors = find_category(u"Doors")
    walls = find_category(u"Walls")

    if doors is not None:
        guarded(u"Doors schedule", round_trip, u"Doors", doors, "schedule", u"{@WIDTH} * {@HEIGHT}")
    else:
        info(u"Doors not in the model: round trip skipped")

    if walls is not None:
        guarded(u"Walls takeoff", round_trip, u"Walls", walls, "takeoff", u"{@LAYER_THICKNESS} * 2")
        guarded(u"Table types", run_table_types)
    else:
        info(u"Walls not in the model: takeoff and table type checks skipped")

    guarded(u"Missing field", run_missing_field)
    guarded(u"Bad files", run_bad_files)
    guarded(u"Atomic write", run_atomic_write)
    guarded(u"Old file", run_old_file)
    guarded(u"Real file info", run_real_file_info)

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    out.print_md(u"---")
    out.print_md(u"**%d of %d checks passed**" % (passed, total))
    forms.alert(u"Phase 9 check: %d of %d passed. See the output window." % (passed, total),
                title=u"Abaco Phase 9 check", warn_icon=passed < total)


if __name__ == "__main__":
    if not doc or doc.IsFamilyDocument:
        forms.alert("Open a Revit project first.", exitscript=True)
    try:
        main()
    finally:
        shutil.rmtree(TEST_DIR, ignore_errors=True)