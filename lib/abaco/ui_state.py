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
from abaco import appearance as AP

CALC_MODES = P.CALC_MODES
ALIGN_CHIP = {"left": u"L", "center": u"C", "right": u"R"}
SCOPE_TEXT = {"element": u"instance", "type": u"type", "layer": u"layer", "group": u"calculated", "formula": u"custom"}
EXCEL_BAD = u":\\/?*[]"
REVIT_BAD = u"\\:{}[]|;<>?`~"
FOOTER_MODES = [(u"Per field", "field"), (u"Totals", "total"), (u"Min", "min"),
                (u"Max", "max"), (u"Min and max", "minmax")]
FOOTER_CODE = dict((lab, code) for lab, code in FOOTER_MODES)
FOOTER_LABEL = dict((code, lab) for lab, code in FOOTER_MODES)

COMMON_FONTS = [u"Arial", u"Calibri", u"Consolas", u"Courier New", u"Georgia", u"Segoe UI",
                u"Tahoma", u"Times New Roman", u"Verdana"]
FONT_SEP = u"\u2500" * 12


# ---------------------------------------------------------------------------------------------- helpers

def _netlist(items):
    try:
        from System.Collections.Generic import List
        out = List[object]()
        for i in items:
            out.Add(i)
        return out
    except Exception:
        return list(items)
    
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

def installed_fonts():
    """Common fonts first, a separator, then every other installed font (read from the machine)."""
    try:
        import clr
        clr.AddReference("System.Drawing")
        from System.Drawing.Text import InstalledFontCollection
        names = [f.Name for f in InstalledFontCollection().Families]
    except Exception:
        names = list(COMMON_FONTS)
    names = sorted(set(names), key=lambda s: s.lower())
    common = [n for n in COMMON_FONTS if n in names]
    rest = [n for n in names if n not in common]
    return common + ([FONT_SEP] if common and rest else []) + rest


def brush(hexcolor):
    """WPF brush for a '#RRGGBB' string (None when empty or WPF is not available)."""
    if not hexcolor:
        return None
    try:
        from System.Windows.Media import SolidColorBrush, Color
        h = hexcolor.lstrip("#")
        return SolidColorBrush(Color.FromRgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
    except Exception:
        return None


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


class ElemRow(Observable):
    Bold = _bind("Bold")
    Italic = _bind("Italic")
    Underline = _bind("Underline")
    Lines = _bind("Lines")
    Case = _bind("Case")
    Align = _bind("Align")
    Orientation = _bind("Orientation")

    def __init__(self, element, label, e, on_change=None):
        Observable.__init__(self)
        self.element = element
        self.Label = label
        self._Bold = bool(e["bold"])
        self._Italic = bool(e["italic"])
        self._Underline = bool(e["underline"])
        self._Lines = bool(e["lines"])
        self._Case = AP.CASE_LABEL[e["case"]]
        self.CaseItems = _netlist([lab for lab, _ in AP.CASES])
        self.HasAlign = "align" in e
        self._Align = AP.ALIGN_LABEL.get(e.get("align"), u"Left")
        self.AlignItems = _netlist([lab for lab, _ in AP.ALIGNS])
        self.HasOrient = "orientation" in e
        self._Orientation = AP.ORIENT_LABEL.get(e.get("orientation"), u"Horizontal")
        self.OrientItems = _netlist([lab for lab, _ in AP.ORIENTS])
        self.TextBrush = brush(e["color"])
        self.BgBrush = brush(e["background"])
        self.on_change = on_change


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


class LevelRow(Observable):
    Column = _bind("Column")
    Descending = _bind("Descending")
    Header = _bind("Header")
    Footer = _bind("Footer")
    Gap = _bind("Gap")
    FooterMode = _bind("FooterMode")

    def __init__(self, index, columns, column, descending, header, footer, gap, footer_calc, on_change=None):
        Observable.__init__(self)
        self.Index = index
        self.Columns = columns
        self._Column = column
        self._Descending = bool(descending)
        self._Header = bool(header)
        self._Footer = bool(footer)
        self._Gap = bool(gap)
        self._FooterMode = FOOTER_LABEL.get(footer_calc, FOOTER_LABEL["field"])
        self.FooterModes = _netlist([lab for lab, _ in FOOTER_MODES])
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

    def _usable(self, f):
        return f.scope != "layer" or P.effective_type(self.rs, self.settings) == "takeoff"

    def is_custom(self, key):
        """True for a calculated (formula-scope) field, the only kind Edit and Delete apply to."""
        f = self.rs.field(key)
        return f is not None and f.scope == "formula"

    # ---- fields
    def field_rows(self, on_change=None):
        """Only show fields that are set to appear somewhere (Hidden=false OR Excel=true)."""
        rows = []
        for st in self.settings["fields"]:
            key = st["key"]
            lab = self.label(key) if self.rs.field(key) is not None else u"%s (not found)" % (st.get("heading") or key)
            # Include only if visible in at least one output
            if not (st.get("hiddenInRevit") and not st.get("showInExcel", True)):
                rows.append(FieldRow(key, lab, True, self._scope_text(key), on_change))
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

    def remove_field(self, key):
        """Remove a field from the table. Returns False if it's the last one."""
        fl = self.settings["fields"]
        if len([s for s in fl if s.get("include", True)]) <= 1:
            return False
        for i, s in enumerate(fl):
            if s["key"] == key:
                del fl[i]
                return True
        return False

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
            if not self._usable(f): continue
            if f.key in used:
                continue
            lab = self.label(f.key)
            if t and t not in lab.lower():
                continue
            out.append((lab.lower(), SuggestRow(f.key, lab, SCOPE_TEXT.get(f.scope, u""))))
        out.sort(key=lambda x: x[0])
        return [r for _, r in out[:limit]]

    # ---- sorting
    def table_keys(self):
        """Keys of the fields checked in the Fields tab: the only fields Sort & group and Filter may use."""
        out = []
        for st in self.settings["fields"]:
            if st.get("include", True) and self.rs.field(st["key"]) is not None:
                out.append(st["key"])
        return out

    def sort_columns(self):
        keys = [k for k in self.table_keys() if self._usable(self.rs.field(k))]
        return sorted([self.label(k) for k in keys], key=lambda s: s.lower())


    # ---- sort and group: one list of levels
    def level_rows(self, on_change=None):
        cols = self.sort_columns()
        rows = []
        for i, s in enumerate(self.settings.setdefault("levels", [])):
            lab = self.label(s["key"])
            own = cols if lab in cols else cols + [lab]     # field left the table: keep it visible
            rows.append(LevelRow(i + 1, own, lab, s.get("dir") == "desc",
                                 s.get("header"), s.get("footer"), s.get("gap"),
                                 s.get("footerCalc") or "field", on_change))
        return rows

    def level_update(self, i, row):
        """Copy the edited properties of one row back into the settings (user edits only)."""
        s = self.settings["levels"][i]
        if row.Column in self._by_label:
            s["key"] = self._by_label[row.Column]
        s["dir"] = "desc" if row.Descending else "asc"
        s["header"] = bool(row.Header)
        s["footer"] = bool(row.Footer)
        s["gap"] = bool(row.Gap)
        s["footerCalc"] = FOOTER_CODE.get(row.FooterMode, "field")

    def level_add(self):
        keys = self.table_keys()
        used = set(s["key"] for s in self.settings.get("levels", []))
        free = [k for k in keys if k not in used]
        choice = (free or keys or [None])[0]
        if choice is None:
            return
        self.settings.setdefault("levels", []).append(P.sort_setting(choice))

    def level_remove(self, i):
        del self.settings["levels"][i]

    def level_clear(self):
        self.settings["levels"] = []
        

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
        return {"heading": self.heading(key),
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

    # ---- appearance
    def app(self):
        return self.settings["appearance"]

    def app_touch(self):
        self.app()["theme"] = "custom"

    def app_element_rows(self, on_change=None):
        app = self.app()
        return [ElemRow(k, lab, app["elements"][k], on_change) for k, lab in AP.ELEMENTS]

    def app_element_update(self, row):
        e = self.app()["elements"][row.element]
        e["bold"], e["italic"], e["underline"] = bool(row.Bold), bool(row.Italic), bool(row.Underline)
        e["lines"] = bool(row.Lines)
        e["case"] = AP.CASE_CODE.get(row.Case, "none")
        if "align" in e and row.Align in AP.ALIGN_CODE:
            e["align"] = AP.ALIGN_CODE[row.Align]
        if "orientation" in e and row.Orientation in AP.ORIENT_CODE:
            e["orientation"] = AP.ORIENT_CODE[row.Orientation]
        self.app_touch()

    def app_color(self, element, which, hexcolor):
        """which: 'color' (text) or 'background'. hexcolor None clears the background."""
        self.app()["elements"][element][which] = hexcolor
        self.app_touch()

    def app_set(self, path, value):
        d = self.app()
        for k in path[:-1]:
            d = d[k]
        d[path[-1]] = value
        self.app_touch()

    def app_theme(self, theme):
        app = self.app()
        fresh = AP.preset(theme, app["accent"])
        app["elements"] = fresh["elements"]
        app["zebra"] = fresh["zebra"]
        app["lines"]["color"] = fresh["lines"]["color"]
        app["theme"] = theme
