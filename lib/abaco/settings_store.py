# -*- coding: utf-8 -*-
"""Saved settings per category (Phase 9). Pure Python: no Revit, no WPF.

One file for all categories and table types:
    v1 (pyRevit)   %APPDATA%\\pyRevit\\Abaco\\tables.json
    v2 onward      %APPDATA%\\Abaco\\tables.json   (same format)

Format:
    {"v": 1, "saved": {"OST_Walls|schedule": {"settings": {...}, "output": {...}}}}

Key: the English BuiltInCategory name, then the table type. Curtain walls are a filter, not a table
type, so the table type is the second part of the key.

Loading never raises:
  - a missing file is an empty store, silently;
  - an unreadable file or unknown layout is moved aside to tables.json.corrupt, and defaults are used;
  - a file from a NEWER version is not loaded, and the store is marked blocked so saving cannot overwrite it.

Saving happens only when the user presses Save settings (write_file).
Common-subset Python (IronPython 2.7 / CPython 3): no f-strings.
"""
import copy
import io
import json
import os

from abaco import appearance as AP
from abaco import filters
from abaco import pipeline as P

VERSION = 1
SEP = u"|"
ASIDE_SUFFIX = u".corrupt"
OUTPUT_KEYS = ("tableName", "excelPath", "titleBlock", "prefix", "pageHeight")
FIELD_ALIGNS = ("left", "center", "right")
FIELD_BOOLS = ("include", "hiddenInRevit", "showInExcel")
LEVEL_DIRS = ("asc", "desc")

try:
    _TEXT = unicode
except NameError:
    _TEXT = str


def _is_text(v):
    return isinstance(v, _TEXT)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ------------------------------------------------------------------------------------------- paths
def default_path(app_data=None, pyrevit=True):
    """pyrevit=True: v1 location. pyrevit=False: v2 standalone location (same file format)."""
    base = app_data or os.environ.get("APPDATA") or os.path.expanduser(u"~")
    if pyrevit:
        return os.path.join(base, "pyRevit", "Abaco", "tables.json")
    return os.path.join(base, "Abaco", "tables.json")


def store_key(category_key, table_type):
    return u"%s%s%s" % (category_key, SEP, table_type)


def empty_store():
    return {"v": VERSION, "saved": {}}


# ------------------------------------------------------------------------------------- file I/O
def _set_aside(path):
    aside = path + ASIDE_SUFFIX
    try:
        if os.path.exists(aside):
            os.remove(aside)
        os.rename(path, aside)
        return aside
    except Exception:
        return u""


def _unreadable(path, reason):
    aside = _set_aside(path)
    msg = u"Saved settings %s. Defaults are used." % reason
    if aside:
        msg += u" The file was moved to %s." % aside
    return empty_store(), msg


def read_file(path):
    """-> (store, message). message is empty when the file is fine or missing. Never raises."""
    if not os.path.exists(path):
        return empty_store(), u""
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            data = json.loads(f.read())
    except Exception as ex:
        return _unreadable(path, u"could not be read (%s)" % ex)
    if not isinstance(data, dict) or not isinstance(data.get("saved", {}), dict):
        return _unreadable(path, u"has an unexpected layout")
    version = data.get("v")
    if version == VERSION:
        data.setdefault("saved", {})
        return data, u""
    if _is_number(version) and version > VERSION:
        store = empty_store()
        store["blocked"] = True
        return store, (u"Saved settings were written by a newer version of Abaco (format %s). They are "
                       u"not loaded, and saving is turned off so the file is not overwritten." % version)
    return _unreadable(path, u"has unknown format version %s" % (version,))


def write_file(path, store):
    """Writes the whole file through a temporary file. Raises IOError when the store is blocked."""
    if store.get("blocked"):
        raise IOError(u"Saved settings were written by a newer Abaco. Saving is turned off.")
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    text = json.dumps({"v": VERSION, "saved": store.get("saved", {})}, indent=2, sort_keys=True)
    if not isinstance(text, _TEXT):
        text = text.decode("ascii")          # json.dumps is ASCII-only, so this is always safe
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    if os.path.exists(path):
        os.remove(path)
    os.rename(tmp, path)


# ---------------------------------------------------------------------------- get and put
def get_saved(store, category_key, table_type):
    entry = store.get("saved", {}).get(store_key(category_key, table_type))
    return entry if isinstance(entry, dict) else None


def put_saved(store, category_key, table_type, settings, output):
    """Stores the settings and the output options for one category and table type (in memory only)."""
    s = copy.deepcopy(dict((k, v) for k, v in settings.items() if k != "category"))
    out = dict((k, output.get(k)) for k in OUTPUT_KEYS)
    entry = {"settings": s, "output": out}
    store.setdefault("saved", {})[store_key(category_key, table_type)] = entry
    return entry


# ------------------------------------------------------------------------------- cleaning values
def clean_output(raw, defaults):
    """Output options from a saved entry. Anything invalid falls back to the window's defaults."""
    out = dict(defaults)
    if not isinstance(raw, dict):
        return out
    for k in ("tableName", "excelPath", "prefix", "pageHeight"):
        if _is_text(raw.get(k)):
            out[k] = raw[k]
    tb = raw.get("titleBlock")
    out["titleBlock"] = tb if (tb is None or _is_text(tb)) else None
    return out


def _clean_fields(items):
    """-> (fields or None, number of entries skipped)."""
    if not isinstance(items, list):
        return None, 0
    out, skipped, seen = [], 0, set()
    for it in items:
        key = it.get("key") if isinstance(it, dict) else None
        if not _is_text(key) or not key or key in seen:
            skipped += 1
            continue
        seen.add(key)
        st = P.field_setting(key)
        for k in FIELD_BOOLS:
            if isinstance(it.get(k), bool):
                st[k] = it[k]
        for k in ("heading", "tag", "unit"):
            if _is_text(it.get(k)):
                st[k] = it[k]
        d = it.get("decimals")
        if isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 4:
            st["decimals"] = d
        w = it.get("widthMm")
        if _is_number(w) and w > 0:
            st["widthMm"] = float(w)
        if it.get("align") in FIELD_ALIGNS:
            st["align"] = it["align"]
        if it.get("calc") in P.CALC_MODES:
            st["calc"] = it["calc"]
        out.append(st)
    return out, skipped


def _clean_levels(items):
    """-> (levels or None, number of entries skipped)."""
    if not isinstance(items, list):
        return None, 0
    out, skipped = [], 0
    for it in items:
        key = it.get("key") if isinstance(it, dict) else None
        if not _is_text(key) or not key:
            skipped += 1
            continue
        out.append(P.sort_setting(
            key,
            it.get("dir") if it.get("dir") in LEVEL_DIRS else "asc",
            header=it.get("header") is True,
            footer=it.get("footer") is True,
            gap=it.get("gap") is True,
            footer_calc=it.get("footerCalc") if it.get("footerCalc") in P_FOOTER_CALCS else "field"))
    return out, skipped


P_FOOTER_CALCS = ("field", "total", "min", "max", "minmax")


def _clean_custom(items):
    out, seen = [], set()
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        key = it.get("key")
        if not _is_text(key) or not key or key in seen:
            continue
        seen.add(key)
        out.append({"key": key,
                    "name": it["name"] if _is_text(it.get("name")) else key,
                    "formula": it["formula"] if _is_text(it.get("formula")) else u""})
    return out


def _clean_row_numbers(v):
    out = {"on": False, "heading": u"No."}
    if isinstance(v, dict):
        out["on"] = v.get("on") is True
        if _is_text(v.get("heading")):
            out["heading"] = v["heading"]
    return out


# ------------------------------------------------------------------------------------- restore
def restore(saved, defaults, output_defaults, known_keys=None):
    """Builds the settings for the window from a saved entry.

    saved            the entry from get_saved(), or None
    defaults         P.default_settings(...) for this category, the template to fill from
    output_defaults  the window's output defaults (table name, workbook, title block, prefix, height)
    known_keys       field keys of this project. Saved fields not in it are KEPT and reported.

    Returns (settings, output, messages). Never raises. Messages are for the log.
    """
    messages = []
    if saved is None:
        return copy.deepcopy(defaults), dict(output_defaults), messages

    s = saved.get("settings") if isinstance(saved.get("settings"), dict) else {}
    out = copy.deepcopy(defaults)

    fields, skipped = _clean_fields(s.get("fields"))
    if fields is not None:
        out["fields"] = fields
    if skipped:
        messages.append(u"%d saved field entries were not valid and were skipped." % skipped)
    if known_keys is not None:
        missing = [f["key"] for f in out["fields"] if f["key"] not in known_keys]
        if missing:
            messages.append(u"%d saved field(s) are not in this project and show %s. Remove them with "
                            u"the x in Fields, or add the parameter again." % (len(missing), P.MARK_NOT_IN_PROJECT))

    levels, skipped = _clean_levels(s.get("levels"))
    if levels is not None:
        out["levels"] = levels
    if skipped:
        messages.append(u"%d saved sort levels were not valid and were skipped." % skipped)

    out["custom"] = _clean_custom(s.get("custom"))
    out["filter"] = filters.normalize_settings(s.get("filter"))
    out["appearance"] = AP.normalize(s.get("appearance"))
    for k in ("grandTotals", "itemize"):
        if isinstance(s.get(k), bool):
            out[k] = s[k]
    if _is_text(s.get("title")):
        out["title"] = s["title"]
    out["rowNumbers"] = _clean_row_numbers(s.get("rowNumbers"))

    labels = dict(out.get("labels") or {})
    if isinstance(s.get("labels"), dict):
        for k, v in s["labels"].items():
            if k in P.DEFAULT_LABELS and _is_text(v):
                labels[k] = v
    out["labels"] = labels

    return out, clean_output(saved.get("output"), output_defaults), messages