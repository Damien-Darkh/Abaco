# -*- coding: utf-8 -*-
"""Filter tab controller (window side). Needs pyRevit + WPF, NOT the Revit API.

Owns everything the Filter tab does, so script.py only creates it and forwards the XAML events:

    # in the window __init__ (after the XAML is loaded)
    self.filter_tab = FilterTab(self.filter_list, self.filter_status, self.filter_all, self.filter_any,
                                on_change=self.refresh_preview)

    # XAML handlers (names fixed by ui.xaml)
    def filter_add_click(self, sender, args):    self.filter_tab.add()
    def filter_clear_click(self, sender, args):  self.filter_tab.clear()
    def filter_match_click(self, sender, args):  self.filter_tab.changed()

    # after read_category / Re-read model, and when settings are loaded (Phase 5)
    self.filter_tab.set_catalogue(self.rs)
    self.filter_tab.load(saved_settings.get("filter"))

    # in refresh_preview (see filters.py for the pipeline side)
    flt = self.filter_tab.to_settings()
    rr.ensure_values(doc, self.rs, filters.needed_keys(flt), self.log)
    result = filters.apply_filters(self.rs, elements, flt)
    self.filter_tab.show_result(result)

Row items are INotifyPropertyChanged (pyrevit.forms.Reactive) so the two-way bindings in ui.xaml work.
Common-subset Python: no f-strings.
"""
from System import TimeSpan
from System.Collections.Generic import List
from System.Collections.ObjectModel import ObservableCollection
from System.Windows import RoutedEventHandler
from System.Windows.Controls import Button
from System.Windows.Threading import DispatcherTimer
from pyrevit import forms

from abaco import filters


def _net(items):
    out = List[object]()
    for i in items:
        out.Add(i)
    return out


class FilterRow(forms.Reactive):
    """One condition. Bound properties: Index, Columns, Column, Operators, Operator, Value,
    NeedsValue, Error, HasError (see the code contract in ui.xaml)."""

    def __init__(self, tab, columns, column, op_code, value):
        forms.Reactive.__init__(self)
        self._tab = tab
        self._loading = True                      # no change notifications while the row is being built
        self._index = 0
        self._columns = _net(columns)
        self._column = column
        self._ops = _net([])
        self._operator = u""
        self._needs = True
        self._value = value or u""
        self._error = u""
        self._code_by_label = {}
        self._label_by_code = {}
        self._exact = False
        self._suggestions = _net([])
        self._fill_operators(op_code)
        self._loading = False
        self._labels_all = {}                     # key -> label of every field (for "not in Fields" rows)

    # ---- bound properties
    @forms.reactive
    def Index(self):
        return self._index

    @Index.setter
    def Index(self, v):
        self._index = v

    @forms.reactive
    def Columns(self):
        return self._columns

    @Columns.setter
    def Columns(self, v):
        self._columns = v

    @forms.reactive
    def Column(self):
        return self._column

    @Column.setter
    def Column(self, v):
        if v is None or v == self._column:        # WPF sends None while the ItemsSource is replaced
            return
        self._column = v
        self._fill_operators(None)
        self._changed()

    @forms.reactive
    def Operators(self):
        return self._ops

    @Operators.setter
    def Operators(self, v):
        self._ops = v

    @forms.reactive
    def Operator(self):
        return self._operator

    @Operator.setter
    def Operator(self, v):
        if v is None or v == self._operator:
            return
        self._operator = v
        code = self._code_by_label.get(v)
        self.NeedsValue = filters.needs_value(code) if code else True
        self.IsExact = code in ("eq", "ne")
        self.IsText = None
        self._changed()

    @forms.reactive
    def Value(self):
        return self._value

    @Value.setter
    def Value(self, v):
        v = v if v is not None else u""
        if v == self._value:
            return
        self._value = v
        self._changed()

    @forms.reactive
    def NeedsValue(self):
        return self._needs

    @NeedsValue.setter
    def NeedsValue(self, v):
        self._needs = v

    @forms.reactive
    def Error(self):
        return self._error

    @Error.setter
    def Error(self, v):
        self._error = v or u""
        self.HasError = bool(self._error)

    @forms.reactive
    def HasError(self):
        return bool(self._error)

    @HasError.setter
    def HasError(self, v):
        pass                                      # derived from Error; the setter only raises the notification

    @forms.reactive
    def IsExact(self):
        return self._exact

    @IsExact.setter
    def IsExact(self, v):
        self._exact = bool(v)

    @forms.reactive
    def IsText(self):
        return self._needs and not self._exact

    @IsText.setter
    def IsText(self, v):
        pass                                      # derived from NeedsValue and IsExact

    @forms.reactive
    def Suggestions(self):
        return self._suggestions

    @Suggestions.setter
    def Suggestions(self, v):
        self._suggestions = v

    # ---- internals
    def _changed(self):
        if not self._loading:
            self._tab.changed()

    def _fill_operators(self, op_code):
        """Operators depend on the field kind; keep the old operator when the new kind supports it."""
        was, self._loading = self._loading, True
        keep = op_code
        if keep is None:
            keep = self._code_by_label.get(self._operator)
        ops = filters.operators_for(self._tab.kind_of(self._column))
        self._code_by_label = dict((lab, code) for code, lab in ops)
        self._label_by_code = dict((code, lab) for code, lab in ops)
        self._operator = u""                      # force the setter below to run its notifications
        self.Operators = _net([lab for _, lab in ops])
        self.Operator = self._label_by_code.get(keep, ops[0][1])
        self.Suggestions = self._tab.values_for(self._column)
        self._loading = was

    def to_condition(self):
        return {"key": self._tab.key_of(self._column),
                "op": self._code_by_label.get(self._operator, u""),
                "value": self._value}


class FilterTab(object):
    def __init__(self, list_control, status_control, all_radio, any_radio, on_change, delay_ms=300):
        self._status = status_control
        self._all = all_radio
        self._any = any_radio
        self._on_change = on_change
        self._muted = False                       # True while loading: no refresh per row
        self._keys = {}                           # column label -> field key
        self._fields = {}                         # column label -> Field (None when the field is missing)
        self._labels = []                         # sorted labels offered in the Column combo
        self.rows = ObservableCollection[object]()
        list_control.ItemsSource = self.rows
        list_control.AddHandler(Button.ClickEvent, RoutedEventHandler(self._row_click))
        self._timer = DispatcherTimer()
        self._timer.Interval = TimeSpan.FromMilliseconds(delay_ms)
        self._timer.Tick += self._tick


    def values_for(self, label):
        """Distinct values of a field across the model, for the Value suggestions."""
        key = self.key_of(label)
        if not key or self._rs is None:
            return _net([])
        if key not in self._value_cache:
            seen = set()
            for er in self._rs.elements:
                try:
                    v = self._rs.value(er, key)
                except KeyError:
                    continue
                if v is not None and u"%s" % v != u"":
                    seen.add(u"%s" % v)
            self._value_cache[key] = _net(sorted(seen, key=lambda s: s.lower()))
        return self._value_cache[key]
    
    # ---- catalogue
    def set_catalogue(self, rs, allowed=None):
        """Offer only the fields of the Fields tab (allowed = their keys). Existing conditions are kept."""
        self._rs = rs
        self._value_cache = {}
        saved = self.to_settings()
        labels = rs.display_labels()
        self._labels_all = labels
        self._allowed = None if allowed is None else set(allowed)
        self._keys, self._fields = {}, {}
        for f in rs.fields:
            if f.scope not in filters.FILTERABLE_SCOPES:
                continue
            if self._allowed is not None and f.key not in self._allowed:
                continue
            lab = labels[f.key]
            self._keys[lab] = f.key
            self._fields[lab] = f
        self._labels = sorted(self._keys, key=lambda s: s.lower())
        self.load(saved)

    def kind_of(self, label):
        f = self._fields.get(label)
        return f.kind if f is not None else "text"

    def key_of(self, label):
        return self._keys.get(label, u"")

    def _label_for_key(self, key):
        for lab, k in self._keys.items():
            if k == key:
                return lab, self._labels
        lab = u"%s (not in Fields)" % self._labels_all.get(key, key)   # kept, flagged, skipped
        self._keys[lab] = key
        self._fields[lab] = None
        return lab, self._labels + [lab]

    # ---- rows
    def _make_row(self, cond):
        if cond is None:
            lab, cols, op, val = self._labels[0], self._labels, None, u""
        else:
            lab, cols = self._label_for_key(cond["key"])
            op, val = cond["op"], cond["value"]
        return FilterRow(self, cols, lab, op, val)

    def _renumber(self):
        for i, r in enumerate(self.rows):
            r.Index = i + 1

    def add(self):
        if not self._labels:
            self._status.Text = u"Read the model first (open the Preview tab)."
            return
        self.rows.Add(self._make_row(None))
        self._renumber()
        self.changed()

    def clear(self):
        self.rows.Clear()
        self.changed()

    def load(self, settings):
        """Restore from saved settings (Phase 5) or after a re-read. One refresh at the end."""
        s = filters.normalize_settings(settings)
        self._muted = True
        try:
            self._all.IsChecked = (s["match"] != filters.MATCH_ANY)
            self._any.IsChecked = (s["match"] == filters.MATCH_ANY)
            self.rows.Clear()
            for c in s["conditions"]:
                self.rows.Add(self._make_row(c))
            self._renumber()
        finally:
            self._muted = False
        self.changed()

    def _row_click(self, sender, args):
        src = args.OriginalSource
        while src is not None and not isinstance(src, Button):
            src = getattr(src, "Parent", None)
        if src is not None and src.Tag == "remove" and src.DataContext in self.rows:
            self.rows.Remove(src.DataContext)
            self._renumber()
            self.changed()

    # ---- settings <-> window
    def to_settings(self):
        return {"match": filters.MATCH_ANY if self._any.IsChecked else filters.MATCH_ALL,
                "conditions": [r.to_condition() for r in self.rows]}

    def show_result(self, result):
        """Call after filters.apply_filters(): puts each error on its row and the summary in the status line."""
        for r, err in zip(list(self.rows), result.errors):
            r.Error = err
        self._status.Text = result.summary()

    # ---- debounce: typing must not re-run the pipeline on every key
    def changed(self):
        if self._muted:
            return
        self._timer.Stop()
        self._timer.Start()

    def flush(self):
        """Run any pending refresh now (call before Run so the output matches the preview)."""
        if self._timer.IsEnabled:
            self._timer.Stop()
            self._on_change()

    def _tick(self, sender, args):
        self._timer.Stop()
        self._on_change()

    def set_condition(self, key, op, value):
        """Quick filters: replace any condition on this field with a ready-made one."""
        if key not in self._keys.values():
            return False
        for r in [r for r in self.rows if self.key_of(r.Column) == key]:
            self.rows.Remove(r)
        self.rows.Add(self._make_row({"key": key, "op": op, "value": value}))
        self._renumber()
        self.changed()
        return True
