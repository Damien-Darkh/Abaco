# -*- coding: utf-8 -*-
"""Window state for the Preview tab (Phase 4): pipeline settings <-> list rows. No Revit, no WPF.

The row classes implement INotifyPropertyChanged when running under IronPython (so two-way bindings work)
and are plain objects under CPython (so this module is unit-tested outside Revit).
EditState owns the settings dict the pipeline reads; every edit is a method here, the window only calls them.
"""
import os

try:
    import clr
    from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs
    _Base = INotifyPropertyChanged
except Exception:
    PropertyChangedEventArgs = None
    _Base = object

from abaco import pipeline as P
from abaco.records import K_TYPE_MARK

CALC_MODES = P.CALC_MODES
ALIGN_CHIP = {"left": u"L", "center": u"C", "right": u"R"}
SCOPE_TEXT = {"element": u"instance", "type": u"type", "layer": u"layer", "group": u"calculated"}
EXCEL_BAD = u":\\/?*[]"
REVIT_BAD = u"\\:{}[]|;<>?`~"


# ---------------------------------------------------------------------------------------------- helpers
def parse_decimal(text):
    """'2,5' or '2.5' -> 2.5 (Italian decimal comma). Raises ValueError."""
    t = (text or u"").strip().replace(u",", u".")
    if not t:
        raise ValueError("empty")
    return float(t)


def check_table_name(name, revit, excel):
    """Problems with the table name (used for the Revit views and the Excel tab). [] = fine."""
    name = (name or u"").strip()
    if not name:
        return [u"The table name is empty."]
    out = []
    if excel and len(name) > 31:
        out.append(u"Excel tab names are limited to 31 characters (the table name has %d)." % len(name))
    bad = set()
    if excel:
        bad |= set(EXCEL_BAD)
    if revit:
        bad |= set(REVIT_BAD)
    found = sorted(set(c for c in name if c in bad))
    if found:
        out.append(u"The table name contains characters Revit or Excel do not allow: %s" % u" ".join(found))
    return out


def check_excel_path(path):
    path = (path or u"").strip()
    if not path:
        return [u"Choose the Excel workbook (.xlsx)."]
    out = []
    if not path.lower().endswith(u".xlsx"):
        out.append(u"The workbook must be an .xlsx file.")
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        out.append(u"Folder not found: %s" % folder)
    return out


# ----------------------------------------------------------------------------------------- row items
class Observable(_Base):
    def __init__(self):
        self._handlers = []
        self.on_change = None

    def add_PropertyChanged(self, handler):
        self._handlers.append(handler)

    def remove_PropertyChanged(self, handler):
        if handler in self._handlers:
            self._handlers.remove(handler)

    def raise_changed(self, name):
        if PropertyChangedEventArgs is None:
            return
        args = PropertyChangedEventArgs(name)
        for h in list(self._handlers):
            h(self, args)


def _bind(name, watched=True):
    """Property that notifies the UI and, when watched, calls on_change(row, name) (user edits only)."""
    attr = "_" + name

    def getter(self):
        return getattr(self, attr)

    def setter(self, value):
        if getattr(self, attr, None) == value:
            return
        setattr(self, attr, value)
        self.raise_changed(name)
        if watched and self.on_change is not None:
            self.on_change(self, name)
    return property(getter, setter)


class FieldRow(Observable):
    Include = _bind("Include")

    def __init__(self, key, label, include, scope_text, on_change=None):
        Observable.__init__(self)
        self.key = key
        self.Label = label
        self._Include = bool(include)
        self.ScopeText = scope_text
        self.HasScope = bool(scope_text)
        self.on_change = on_change


class SuggestRow(object):
    def __init__(self, key, label, scope_text):
        self.key = key
        self.Label = label
        self.ScopeText = scope_text


class SortRow(Observable):
    Column = _bind("Column")
    Descending = _bind("Descending")
    GapRow = _bind("GapRow")

    def __init__(self, index, columns, column, descending, gap, on_change=None):
        Observable.__init__(self)
        self.Index = index                  # 1-based, shown in the badge
        self.Columns = columns
        self._Column = column
        self._Descending = bool(descending)
        self._GapRow = bool(gap)
        self.on_change = on_change


class FormatRow(Observable):
    Label = _bind("Label", False)
    AlignChip = _bind("AlignChip", False)
    HiddenInRevit = _bind("HiddenInRevit", False)
    NoExcel = _bind("NoExcel", False)
    HasCalc = _bind("HasCalc", False)

    def __init__(self, key, label, chip, hidden, no_excel, has_calc):
        Observable.__init__(self)
        self.key = key
        self._Label = label
        self._AlignChip = chip
        self._HiddenInRevit = bool(hidden)
        self._NoExcel = bool(no_excel)
        self._HasCalc = bool(has_calc)


# ------------------------------------------------------------------------------------------- the state
class EditState(object):
    def __init__(self, rs, settings):
        self.rs = rs
        self.settings = settings
        self.labels = {}                    # key -> unique display label (shown in the lists)
        used = set()
        for key, lab in rs.display_labels().items():
            if lab in used:
                lab = u"%s [%s]" % (lab, key[:8])
            used.add(lab)
            self.labels[key] = lab
        self._by_label = dict((v, k) for k, v in self.labels.items())

    def label(self, key):
        return self.labels.get(key, key)

    def _st(self, key):
        for st in self.settings["fields"]:
            if st["key"] == key:
                return st
        return None

    def _scope_text(self, key):
        f = self.rs.field(key)
        if f is None or f.core:
            return u""
        return SCOPE_TEXT.get(f.scope, u"")

    # ---- fields
    def field_rows(self, on_change=None):
        rows = []
        for st in self.settings["fields"]:
            key = st["key"]
            lab = self.label(key) if self.rs.field(key) is not None else u"%s (not found)" % (st.get("heading") or key)
            rows.append(FieldRow(key, lab, st.get("include", True), self._scope_text(key), on_change))
        return rows

    def counts(self):
        shown = sum(1 for st in self.settings["fields"] if st.get("include", True))
        return shown, len(self.rs.fields)

    def move(self, key, delta):
        fl = self.settings["fields"]
        i = [s["key"] for s in fl].index(key)
        j = i + delta
        if j < 0 or j >= len(fl):
            return False
        fl[i], fl[j] = fl[j], fl[i]
        return True

    def set_include(self, key, value):
        st = self._st(key)
        if st is not None:
            st["include"] = bool(value)

    def add_field(self, key):
        f = self.rs.field(key)
        if f is None or self._st(key) is not None:
            return False
        st = P.field_setting(key)
        lab = self.label(key)
        if lab != f.label:
            st["heading"] = lab             # two fields with the same name: keep the headings apart
        self.settings["fields"].append(st)
        return True

    def suggestions(self, text, limit=40):
        t = (text or u"").strip().lower()
        used = set(s["key"] for s in self.settings["fields"])
        out = []
        for f in self.rs.fields:
            if f.key in used:
                continue
            lab = self.label(f.key)
            if t and t not in lab.lower():
                continue
            out.append((lab.lower(), SuggestRow(f.key, lab, SCOPE_TEXT.get(f.scope, u""))))
        out.sort(key=lambda x: x[0])
        return [r for _, r in out[:limit]]

    # ---- sorting
    def sort_columns(self):
        return sorted(self.labels.values(), key=lambda s: s.lower())

    def sort_rows(self, on_change=None):
        cols = self.sort_columns()
        return [SortRow(i + 1, cols, self.label(s["key"]), s.get("dir") == "desc", s.get("gap"), on_change)
                for i, s in enumerate(self.settings["sort"])]

    def sort_set(self, index0, label=None, descending=None, gap=None):
        s = self.settings["sort"][index0]
        if label is not None and label in self._by_label:
            s["key"] = self._by_label[label]
        if descending is not None:
            s["dir"] = "desc" if descending else "asc"
        if gap is not None:
            s["gap"] = bool(gap)

    def sort_add(self):
        used = set(s["key"] for s in self.settings["sort"])
        key = None
        for st in self.settings["fields"]:
            if st.get("include", True) and st["key"] not in used and self.rs.field(st["key"]) is not None:
                key = st["key"]
                break
        if key is None:
            key = K_TYPE_MARK if self.rs.field(K_TYPE_MARK) is not None else self.rs.fields[0].key
        self.settings["sort"].append(P.sort_setting(key))

    def sort_remove(self, index0):
        del self.settings["sort"][index0]

    def sort_clear(self):
        self.settings["sort"] = []

    # ---- formatting
    def heading(self, key):
        st, f = self._st(key), self.rs.field(key)
        return (st.get("heading") if st else None) or (f.label if f is not None else key)

    def _format_args(self, st):
        return (self.heading(st["key"]), ALIGN_CHIP.get(st.get("align") or "left", u"L"),
                bool(st.get("hiddenInRevit")), not st.get("showInExcel", True),
                (st.get("calc") or "none") != "none")

    def format_rows(self):
        return [FormatRow(st["key"], *self._format_args(st)) for st in self.settings["fields"]
                if st.get("include", True) and self.rs.field(st["key"]) is not None]

    def update_format_row(self, row):
        st = self._st(row.key)
        row.Label, row.AlignChip, row.HiddenInRevit, row.NoExcel, row.HasCalc = self._format_args(st)

    def format_values(self, key):
        st = self._st(key)
        return {"heading": self.heading(key), "orientation": st.get("orientation") or "horizontal",
                "align": st.get("align") or "left", "widthMm": st.get("widthMm"),
                "calc": st.get("calc") or "none", "hidden": bool(st.get("hiddenInRevit")),
                "excel": bool(st.get("showInExcel", True))}

    def format_set(self, key, **kw):
        """kw: heading, orientation, align, widthMm, calc, hiddenInRevit, showInExcel."""
        st = self._st(key)
        f = self.rs.field(key)
        for k, v in kw.items():
            if k == "heading":
                v = (v or u"").strip()
                st["heading"] = None if (not v or (f is not None and v == f.label)) else v
            elif k == "calc":
                st["calc"] = v if v in CALC_MODES else "none"
            else:
                st[k] = v
