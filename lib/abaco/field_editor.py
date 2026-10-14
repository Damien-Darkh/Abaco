# -*- coding: utf-8 -*-
"""Custom field editor (Phase 7). Code-behind for new_parameter.xaml, opened modally over the Tables window.

Entry point:  open_editor(owner, xaml_path, ctx, existing=None) -> definition dict, or None when cancelled.
Definition:   {"key": u"calc:N", "name": u"...", "formula": u"<stored formula>"}

Checks: formula.check() on every change (syntax, units, types, unknown fields). Dry run: after a short pause
the table is built with the candidate field, and the "Where it fails" box shows the first failing row.
The dry run ignores the row filter and grand totals, and it restores the catalogue afterwards.

Common-subset Python (IronPython 2.7 / CPython 3): no f-strings.
"""
import copy

from pyrevit import forms
from System import TimeSpan
from System.Windows import Visibility
from System.Windows.Threading import DispatcherTimer

from abaco import formula as F
from abaco import pipeline as P
from abaco import runner
from abaco import ui_state as US
from abaco import ui_theme

SEPARATORS = u" ,()=<>!+-*/%^"
DRY_RUN_DELAY_MS = 400
KEY_PREFIX = u"calc:"


class EditorContext(object):
    """What the editor needs from the Tables window. The editor never changes these objects."""

    def __init__(self, doc, rs, settings, table_keys, own_key, label_of, log):
        self.doc = doc
        self.rs = rs
        self.settings = settings              # the window's live settings: copied before any dry run
        self.table_keys = list(table_keys)    # keys checked in the Fields tab
        self.own_key = own_key                # the field being edited, None for a new one
        self.label_of = label_of              # key -> label shown in the table (EditState.labels)
        self.log = log


def _base_labels(rs):
    """key -> label with the base unit, as the formula editor shows it: 'Width (m)', 'Door Area (m²)'."""
    out = {}
    for key, lab in rs.display_labels().items():
        f = rs.field(key)
        unit = f.base_unit if f is not None else None
        out[key] = lab + (u" (%s)" % unit if unit else u"")
    return out


def _next_key(rs, settings):
    """The next free calculated key: calc:N with N above every existing one."""
    used = [f.key for f in rs.fields if f.key.startswith(KEY_PREFIX)]
    used += [d.get("key", u"") for d in settings.get("custom", [])]
    n = 0
    for k in used:
        try:
            n = max(n, int(k[len(KEY_PREFIX):]))
        except ValueError:
            pass
    return u"%s%d" % (KEY_PREFIX, n + 1)


def _example(labels, fields):
    """An example that the checker accepts, built from the table's own fields."""
    for f in fields:
        if f.dim and f.base_unit:
            lab = labels[f.key]
            return u"IF({%s} > 1 %s, {%s} * 2, {%s})" % (lab, f.base_unit, lab, lab)
    if fields:
        return u"{%s} + 1" % labels[fields[0].key]
    return u"{Width (m)} * {Height (m)}"


class FieldEditor(forms.WPFWindow):
    def __init__(self, owner, xaml_path, ctx, existing=None):
        forms.WPFWindow.__init__(self, ui_theme.themed_xaml(xaml_path, ui_theme.revit_is_dark(), ctx.log))
        self.Owner = owner
        self.ctx = ctx
        self.existing = existing
        self.result = None
        self._ready = False
        self._busy = False
        self.checked = None
        self.stored = u""

        rs = ctx.rs
        self.labels = _base_labels(rs)
        self.allowed = [k for k in ctx.table_keys if k != ctx.own_key and rs.field(k) is not None]
        self.fields = [rs.field(k) for k in self.allowed]
        self.label_of = dict((k, self.labels[k]) for k in self.allowed)
        self.key_of = dict((self.labels[k], k) for k in self.allowed)
        self.taken = set(ctx.label_of[k].lower() for k in ctx.table_keys
                         if k != ctx.own_key and k in ctx.label_of)
        self.all_rows = [US.SuggestRow(k, self.labels[k], US.SCOPE_TEXT.get(rs.field(k).scope, u""))
                         for k in self.allowed]
        self.new_key = ctx.own_key or _next_key(rs, ctx.settings)

        self.fields_list.ItemsSource = list(self.all_rows)
        self.example_text.Text = _example(self.labels, self.fields)

        self.dry_timer = DispatcherTimer()
        self.dry_timer.Interval = TimeSpan.FromMilliseconds(DRY_RUN_DELAY_MS)
        self.dry_timer.Tick += self.dry_tick

        if existing is not None:
            self.header_title.Text = u"Edit custom field"
            self.Title = u"Edit custom field"
            self.name_box.Text = existing["name"]
            self.formula.Text = F.to_editor(existing["formula"], self.label_of)

        self._ready = True
        self.update_name_status()
        self.check_now(self.formula.Text)

    # ------------------------------------------------------------------ name
    def name_problems(self, name):
        if not name:
            return u"Enter a name."
        if u"{" in name or u"}" in name:
            return u"The name cannot contain { or }."
        if name.lower() in self.taken:
            return u"This name is already a column in the table."
        return u""

    def update_name_status(self):
        msg = self.name_problems(self.name_box.Text.strip())
        if msg:
            self.name_status.Text = msg
            self.name_status.Foreground = self.FindResource("ErrText")
        else:
            self.name_status.Text = u"Shown as the column heading. It must be unique in this table."
            self.name_status.Foreground = self.FindResource("Muted")

    def name_changed(self, sender, args):
        if self._ready:
            self.update_name_status()

    # ---------------------------------------------------------------- status
    def _status(self, text, ok):
        """ok True = valid (green), False = error (red), None = neutral."""
        bg, fg = {True: ("GoodBg", "GoodText"), False: ("ErrBg", "ErrText"),
                  None: ("AccentSoft", "Ink")}[ok]
        self.status_box.Background = self.FindResource(bg)
        self.status_text.Foreground = self.FindResource(fg)
        self.status_text.Text = text

    def _preview(self, text):
        if text:
            self.preview_text.Text = text
            self.preview_box.Visibility = Visibility.Visible
        else:
            self.preview_box.Visibility = Visibility.Collapsed

    # --------------------------------------------------------------- formula
    def _set_text(self, text, caret):
        self._busy = True
        try:
            self.formula.Text = text
            self.formula.SelectionStart = caret
        finally:
            self._busy = False

    def _autocaps(self):
        """Keywords become capitals once a separator is typed after them, at the end of the text."""
        text = self.formula.Text
        if text and self.formula.SelectionStart == len(text) and text[-1] in SEPARATORS:
            caps = F.to_caps(text)
            if caps != text:
                self._set_text(caps, len(caps))

    def formula_changed(self, sender, args):
        if not self._ready or self._busy:
            return
        self._autocaps()
        self.check_now(self.formula.Text)

    def check_now(self, text):
        self.dry_timer.Stop()
        if not text.strip():
            self.checked = None
            self.stored = u""
            self.result_unit_text.Text = u"-"
            self._preview(None)
            self._status(u"Start typing, or click a key.", None)
            return
        self.stored = F.to_stored(text, self.key_of)
        self.checked = F.check(self.stored, self.fields, self.label_of)
        if self.checked.errors:
            e = self.checked.errors[0]
            self.result_unit_text.Text = u"-"
            self._preview(None)
            self._status(e.message + (u". " + e.fix if e.fix else u""), False)
            return
        self.result_unit_text.Text = F.unit_of(self.checked.ty)
        self._status(u"Valid. Result: %s." % self.result_unit_text.Text, True)
        self._preview(None)
        self.dry_timer.Start()

    def dry_tick(self, sender, args):
        self.dry_timer.Stop()
        if self.checked is None or self.checked.errors:
            return
        self._preview(self.dry_run_message())

    def dry_run_result(self):
        """Builds the table with the candidate field. Returns (bad_rows, all_rows, warnings).
        Raises if the table cannot be built; callers decide what to show."""
        rs = self.ctx.rs
        base = self.ctx.settings
        name = self.name_box.Text.strip() or u"Calculated"
        cand = {"key": self.new_key, "name": name, "formula": self.stored}

        s = copy.deepcopy(base)
        s["custom"] = [d for d in s.get("custom", []) if d.get("key") != self.new_key] + [cand]
        s["fields"] = [f for f in s["fields"] if f["key"] != self.new_key] + [P.field_setting(self.new_key)]
        s["filter"] = None
        s["grandTotals"] = False
        try:
            res = runner.build_result(self.ctx.doc, rs, s, self.ctx.log)
        finally:
            P.attach_custom(rs, base)            # the candidate must not stay in the catalogue
        rows = [r for b in res.table.blocks for r in b if r.kind == "data"]
        bad = [r for r in rows if r.cells.get(self.new_key) == u"#ERROR"]
        warn = [w for w in res.warnings if (u"'%s'" % name) in w]
        return bad, rows, warn

    def dry_run_message(self):
        """Text for the 'Where it fails' box, or None when every row calculates."""
        bad, rows, warn = self.dry_run_result()
        if not bad:
            return None
        first = bad[0]
        shown = [k for k in self.allowed[:4] if first.cells.get(k) not in (None, u"")]
        detail = u", ".join(u"%s = %s" % (self.labels[k], first.cells.get(k)) for k in shown)
        text = u"%d of %d rows give #ERROR." % (len(bad), len(rows))
        if warn:
            text += u"\n" + warn[0]
        if detail:
            text += u"\nFirst failing row: " + detail
        return text

    # ------------------------------------------------------- kind and fields
    def kind_changed(self, sender, args):
        if not self._ready:
            return
        hidden = Visibility.Collapsed if self.kind_notes.IsChecked else Visibility.Visible
        for card in (self.formula_card, self.fields_card, self.example_card, self.keys_card):
            card.Visibility = hidden

    def fields_search_changed(self, sender, args):
        if not self._ready:
            return
        t = self.fields_search.Text.strip().lower()
        self.fields_list.ItemsSource = [r for r in self.all_rows if not t or t in r.Label.lower()]

    # ----------------------------------------------------------- insertion
    def _insert(self, tag):
        """Inserts tag at the caret. A '@' in the tag marks where the caret goes; it is removed."""
        box = self.formula
        start, length, text = box.SelectionStart, box.SelectionLength, box.Text
        caret = tag.find(u"@")
        if caret >= 0:
            tag = tag.replace(u"@", u"", 1)
        else:
            caret = len(tag)
        new = text[:start] + tag + text[start + length:]
        self._set_text(new, start + caret)
        self.check_now(new)
        box.Focus()

    def key_click(self, sender, args):
        self._insert(u"%s" % sender.Tag)

    def insert_field_click(self, sender, args):
        row = self.fields_list.SelectedItem
        if row is not None:
            self._insert(u"{%s}" % row.Label)

    def fields_list_double_click(self, sender, args):
        self.insert_field_click(sender, args)

    # ------------------------------------------------------------- buttons
    def save_click(self, sender, args):
        if self.kind_notes.IsChecked:
            return
        name = self.name_box.Text.strip()
        self.update_name_status()
        if self.name_problems(name):
            self.name_box.Focus()
            return
        if self.checked is None or self.checked.errors:
            self.formula.Focus()
            return
        if not self.confirm_element_errors():
            return
        self.result = {"key": self.new_key, "name": name, "formula": self.stored}
        self.Close()

    def confirm_element_errors(self):
        """Element errors save with a warning. Runs the dry run and asks before saving when any row gives #ERROR.
        Returns True to save, False to stay in the editor."""
        try:
            bad, rows, warn = self.dry_run_result()
        except Exception as ex:
            return bool(forms.alert(u"The formula could not be tested on the model:\n\n%s\n\nSave anyway?" % ex,
                                    title=u"Save custom field", yes=True, no=True))
        if not bad:
            return True
        msg = u"%d of %d rows give #ERROR." % (len(bad), len(rows))
        if warn:
            msg += u"\n" + warn[0]
        msg += u"\n\nSave anyway? The table will show #ERROR on those rows."
        return bool(forms.alert(msg, title=u"Save custom field", yes=True, no=True))


def open_editor(owner, xaml_path, ctx, existing=None):
    """Shows the editor modally over owner. Returns the definition dict, or None when cancelled."""
    win = FieldEditor(owner, xaml_path, ctx, existing)
    win.show_dialog()
    return win.result