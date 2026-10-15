# -*- coding: utf-8 -*-
"""Abaco Tables window. Wires ui.xaml to the state (ui_state), the preview (preview) and the output
layers (runner). Table logic lives in lib/abaco; this file moves values between controls and the state.

Output is drafting views only. Saved settings are per category and table type (settings_store).
"""
import json
import os
import traceback

from pyrevit import forms, script, revit
from pyrevit.forms import WPFWindow
from Autodesk.Revit import DB
from System import Action
from System.Windows import RoutedEventHandler, Visibility, FontWeights, FontStyles
from System.Windows.Controls import Button
from System.Windows.Media import FontFamily
from System.Windows.Threading import DispatcherPriority

from abaco import revit_reader as rr
from abaco import pipeline as P
from abaco import runner
from abaco import ui_state as US
from abaco import preview as PV
from abaco import filters
from abaco.filter_ui import FilterTab
from abaco.layout import build_layout
from abaco import appearance as AP
from abaco import color_picker
from abaco.sheet import build_sheet
from abaco import ui_theme
from abaco import field_editor as FE
from abaco import settings_store as SS

doc = revit.doc

DEFAULTS = {
    "page_h": u"490",
    "excel_path": os.path.join(os.path.expanduser("~"), "Documents", "Abaco_tables.xlsx"),
}
CALC_TAGS = list(US.CALC_MODES)            # same order as the fmt_calc items in ui.xaml

TYPE_HINTS = {
    "schedule": u"One row per type and level (and size): count, length, height, area.",
    "takeoff": u"One row per layer / material of each type: thickness, function, material area.",
}


class NoMatch(Exception):
    """The active filter matches no element: nothing to preview or write."""


class AbacoWindow(WPFWindow):
    # Events fire while the XAML loads, before __init__ finishes. Class-level defaults keep handlers safe.
    _ready = False
    _loading = False
    _loading_fmt = False
    _loading_app = False
    _reverting = False
    _active_list = "table"       # which list the user selected last: "table" or "suggest"
    _cat_index = None            # last accepted category index (for revert after a refused change)
    _tt_index = None             # last accepted table type index
    filter_tab = None
    filter_result = None
    _baseline = None

    def __init__(self):
        dark = ui_theme.revit_is_dark()
        WPFWindow.__init__(self, ui_theme.themed_xaml(script.get_bundle_file("ui.xaml"), dark))
        self.log(u"Window theme: %s (follows Revit)" % (u"dark" if dark else u"light"))

        self.store_path = SS.default_path()
        self.store, note = SS.read_file(self.store_path)
        if note:
            self.log(note)
        self.update_store_state(note, bool(self.store.get("blocked")))

        self.cats = rr.list_model_categories(doc)
        self.rs = None
        self.state = None
        self.result = None
        self._auto_name = u""
        self._init_controls()
        self.revit_scale_note.Text = u"Preview scale: 1 mm = %g px" % PV.PX_PER_MM

        # one container-level handler per list (XamlReader cannot wire handlers inside DataTemplates)
        self.level_list.AddHandler(Button.ClickEvent, RoutedEventHandler(self.level_row_click))
        self.elem_list.AddHandler(Button.ClickEvent, RoutedEventHandler(self.elem_row_click))
        self.filter_tab = FilterTab(self.filter_list, self.filter_status, self.filter_all, self.filter_any,
                                    on_change=self.refresh_preview)
        self.tabs.SelectionChanged += self.tabs_changed
        self._tt_index = self.table_type_combo.SelectedIndex
        self._ready = True
        self.category_changed(None, None)

    # ------------------------------------------------------------------------------------------ setup
    def _init_controls(self):
        self.category_combo.ItemsSource = [u"%s  (%d)" % (n, c) for n, c, _ in self.cats]
        idx = 0
        for i, (n, c, cat) in enumerate(self.cats):
            if self._is_walls(cat):
                idx = i
                break
        self.category_combo.SelectedIndex = idx if self.cats else -1
        self.tb_page_h.Text = DEFAULTS["page_h"]
        self.tb_path.Text = DEFAULTS["excel_path"]

    # --------------------------------------------------------------------------------------- helpers
    @staticmethod
    def _is_walls(cat):
        return rr.eid_val(cat.Id) == int(DB.BuiltInCategory.OST_Walls)

    def current_cat(self):
        i = self.category_combo.SelectedIndex
        return self.cats[i][2] if 0 <= i < len(self.cats) else None

    def table_type(self):
        i = self.table_type_combo.SelectedIndex
        return P.TABLE_TYPES[i] if 0 <= i < len(P.TABLE_TYPES) else "schedule"

    def category_key(self):
        return rr.category_key(self.current_cat())

    def type_note(self):
        t = self.table_type()
        if t == "takeoff" and self.rs is not None and not self.rs.has_layered:
            return u"This category has no layered types: the table is built as a schedule."
        return TYPE_HINTS[t]

    def pump(self):
        self.Dispatcher.Invoke(Action(lambda: None), DispatcherPriority.Background)

    def log(self, msg):
        self.log_box.AppendText(u"%s\n" % msg)
        self.log_box.ScrollToEnd()
        self.pump()

    def status(self, msg):
        self.status_text.Text = msg

    def fail(self, ex):
        self.log(u"ERROR: %s" % ex)
        self.log(traceback.format_exc())
        self.status(u"Error: see the log")

    def text_and_page(self):
        """(text height mm from Appearance, page height mm from Settings)."""
        text_mm = float(self.state.app()["font"]["sizeMm"]) if self.state is not None else 2.5
        try:
            page_h = US.parse_decimal(self.tb_page_h.Text)
            if page_h <= 0:
                raise ValueError()
        except ValueError:
            page_h = float(DEFAULTS["page_h"])
        return text_mm, page_h

    def new_state(self, settings):
        _, _, warns = P.attach_custom(self.rs, settings)     # custom fields enter the catalogue
        for w in warns:
            self.log(u"Warning: %s" % w)
        self.state = US.EditState(self.rs, settings)

    def custom_defs(self):
        return self.state.settings.get("custom", []) if self.state is not None else []

    def default_settings(self, title=u""):
        return P.default_settings(self.rs, self.table_type(), title, custom=self.custom_defs())

    def _confirm_discard(self):
        """True when there is nothing unsaved, or the user agrees to discard the changes."""
        if self.txt_unsaved.Visibility != Visibility.Visible:
            return True
        return bool(forms.alert(u"Discard the unsaved changes to this table's settings?",
                                title=u"Abaco Tables", yes=True, no=True))

    def window_closing(self, sender, args):
        if not self._confirm_discard():
            args.Cancel = True

    # ------------------------------------------------------------------------- saved state (dirty)
    def store_state_note(self):
        return u""

    def update_store_state(self, note, blocked):
        """Shows why the settings file was moved aside or blocked, and disables Save when it is blocked."""
        self.store_note_text.Text = note or u""
        self.store_note.Visibility = Visibility.Visible if note else Visibility.Collapsed
        self.btn_save.IsEnabled = not blocked

    def snapshot(self):
        """Settings and output as the user sees them now, as JSON. None when no model is loaded."""
        if self.state is None or self.rs is None or self.filter_tab is None:
            return None
        s = dict(self.state.settings)
        s["title"] = self.tb_title.Text.strip()
        s["filter"] = self.filter_tab.to_settings()
        return json.dumps({"settings": s, "output": self.current_output()}, sort_keys=True, default=str)

    def set_baseline(self):
        """Marks the current state as saved, or as the starting point of a fresh load."""
        self._baseline = self.snapshot()
        self.update_dirty()

    def update_dirty(self):
        now = self.snapshot()
        dirty = self._baseline is not None and now is not None and now != self._baseline
        self.txt_unsaved.Visibility = Visibility.Visible if dirty else Visibility.Collapsed

    # ----------------------------------------------------------------------- model and state
    def load_model(self, keep=False):
        cat = self.current_cat()
        if cat is None:
            return
        old = self.state.settings if (keep and self.state is not None) else None

        # A disabled window ignores input until the read finishes.
        self.IsEnabled = False
        try:
            self.state = None
            self.status(u"Reading the model...")
            self.log(u"Reading %s..." % cat.Name)
            self.rs = rr.read_category(doc, cat, self.log)
            lines = self.rs.summary_lines()
            for line in lines:
                self.log(line)
            self.category_info.Text = lines[0]
            self.table_type_note.Text = self.type_note()
            settings = old if old is not None else self.load_saved_settings()
            self.new_state(settings)
            self.bind_all()
            self.sync_lists()
            if not keep:
                self.filter_tab.load(self.state.settings.get("filter"))
                self.set_baseline()
            self.status(u"Ready")
        finally:
            self.IsEnabled = True

    def load_saved_settings(self):
        """Settings for the current category and table type: the saved ones if any, else the template."""
        defaults = self.default_settings()
        saved = SS.get_saved(self.store, self.category_key(), self.table_type())
        known = set(f.key for f in self.rs.fields)
        if saved is not None:
            s0 = saved.get("settings")
            custom = s0.get("custom") if isinstance(s0, dict) else None
            known |= set(d.get("key") for d in (custom or []) if isinstance(d, dict))
        settings, out, notes = SS.restore(saved, defaults, self.output_defaults(), known)
        self.apply_output(out)
        self._loading = True
        try:
            self.tb_title.Text = settings.get("title") or u""
        finally:
            self._loading = False
        for n in notes:
            self.log(u"Saved settings: %s" % n)
        return settings

    def current_result(self):
        s = self.state.settings
        s["title"] = self.tb_title.Text.strip()
        flt = self.filter_tab.to_settings()
        s["filter"] = flt
        allowed = self.state.table_keys()
        keys = P.required_keys(s) + filters.needed_keys(flt)
        rr.ensure_values(doc, self.rs, [k for k in keys if k], self.log)
        fr = filters.apply_filters(self.rs, self.rs.elements, flt, allowed)
        self.filter_result = fr
        self.filter_tab.show_result(fr)
        if fr.n_active and fr.matched == 0:
            raise NoMatch()
        rs = filters.filtered_view(self.rs, fr.kept) if fr.n_active else self.rs
        res = runner.build_result(doc, rs, s, self.log)
        if fr.n_calc and not res.table.n_data_rows():
            raise NoMatch()
        return res

    # ------------------------------------------------------------------------ output options
    def output_defaults(self):
        return {"tableName": self._auto_name or u"", "excelPath": DEFAULTS["excel_path"],
                "pageHeight": DEFAULTS["page_h"]}

    def current_output(self):
        return {"tableName": self.tb_name.Text.strip(), "excelPath": self.tb_path.Text.strip(),
                "pageHeight": self.tb_page_h.Text.strip()}

    def apply_output(self, out):
        self._loading = True
        try:
            self.tb_name.Text = out["tableName"] or u""
            self.tb_path.Text = out["excelPath"] or u""
            self.tb_page_h.Text = out["pageHeight"] or u""
        finally:
            self._loading = False

    def output_changed(self, sender, args):
        """TextChanged of the title, table name, workbook path and page height."""
        if not self._ready or self._loading:
            return
        self.refresh_preview()

    # ---------------------------------------------------------------------------- binding
    def bind_all(self):
        self.bind_fields()
        self.bind_levels()
        self.bind_options()
        self.bind_format()
        self.bind_appearance()

    def bind_levels(self):
        self.level_list.ItemsSource = self.state.level_rows(self.row_changed)

    def bind_fields(self):
        self.fields_list.ItemsSource = self.state.field_rows(self.row_changed)
        self.update_counts()
        self.bind_suggest()
        missing = [f["key"] for f in self.state.settings["fields"] if self.rs.field(f["key"]) is None]
        self.missing_note.Visibility = Visibility.Visible if missing else Visibility.Collapsed

    def update_counts(self):
        shown, avail = self.state.counts()
        self.fields_count.Text = u"%d shown, %d available" % (shown, avail)

    def bind_suggest(self):
        self.suggest_list.ItemsSource = self.state.suggestions(self.tb_param_search.Text)
        self.update_suggest_buttons()

    def bind_options(self):
        rn = self.state.settings.get("rowNumbers") or {}
        self._loading = True
        try:
            self.chk_grand_totals.IsChecked = bool(self.state.settings.get("grandTotals"))
            self.chk_itemize.IsChecked = bool(self.state.settings.get("itemize"))
            self.chk_rownum.IsChecked = bool(rn.get("on"))
            self.tb_rownum_heading.Text = rn.get("heading", u"No.")
        finally:
            self._loading = False

    def bind_format(self, keep=None):
        if keep is None:
            sel = self.format_list.SelectedItem
            keep = sel.key if sel is not None else None
        self._loading = True
        try:
            rows = self.state.format_rows()
            self.format_list.ItemsSource = rows
            for i, r in enumerate(rows):
                if r.key == keep:
                    self.format_list.SelectedIndex = i
                    break
        finally:
            self._loading = False
        self.load_format_form()

    # ------------------------------------------------------------------------------- preview
    def refresh_preview(self):
        if not self._ready:
            return
        self.update_dirty()
        if self.state is None:
            return
        try:
            res = self.current_result()
        except NoMatch:
            self.result = None
            self.show_no_match()
            return
        except Exception as ex:
            self.preview_status.Text = u"Cannot build the table: %s" % ex
            return
        self.result = res
        note = u""
        if res.warnings:
            note = u"   |   " + u"; ".join(res.warnings[:2])

        if self.view_revit.IsChecked:
            text_mm, page_h = self.text_and_page()
            lay = build_layout(res.revit, text_mm, page_h)
            PV.draw_canvas(self.revit_canvas, self.width_ruler, lay)
            hidden = [c.heading for c in res.table.columns if c.hidden_in_revit]
            self.revit_hidden_note.Text = u"Hidden in Revit: " + (u", ".join(hidden) if hidden else u"none")
            calcs = [u"%s (%s)" % (c.heading, c.calc) for c in res.revit.columns if c.calc != "none"]
            self.revit_calc_note.Text = (u"Calculations: " + u", ".join(calcs)) if calcs else u"No calculations"
            self.preview_status.Text = u"%d rows, %d columns, %d view(s), %.0f mm wide%s" % (
                res.revit.n_data_rows(), len(res.revit.columns), len(lay.pages), lay.table_w, note)
        else:
            sheet = build_sheet(res.excel)
            PV.fill_grid(self.excel_grid, sheet)
            self.show_title(sheet)
            self.preview_status.Text = u"%d rows, %d columns%s" % (
                res.excel.n_data_rows(), len(res.excel.columns), note)

    def show_no_match(self):
        self.preview_status.Text = u"No elements match the filter. Change or clear the conditions in the Filter tab."
        try:
            self.excel_grid.Children.Clear()
            self.excel_grid.RowDefinitions.Clear()
            self.excel_grid.ColumnDefinitions.Clear()
            self.preview_title.Text = u""
            self.revit_canvas.Children.Clear()
            self.width_ruler.Children.Clear()
        except Exception:
            pass

    def show_title(self, sheet):
        app = sheet.appearance
        e = app["elements"]["title"]
        self.preview_title.Text = sheet.values[0][0]
        self.preview_title.FontFamily = FontFamily(app["font"]["family"])
        self.preview_title.FontSize = app["font"]["sizeMm"] * 2.835 * 4.0 / 3.0
        self.preview_title.FontWeight = FontWeights.Bold if e["bold"] else FontWeights.Normal
        self.preview_title.FontStyle = FontStyles.Italic if e["italic"] else FontStyles.Normal
        self.preview_title.Foreground = US.brush(e["color"])

    def view_changed(self, sender, args):
        if not self._ready:
            return
        revit_on = bool(self.view_revit.IsChecked)
        self.excel_host.Visibility = Visibility.Collapsed if revit_on else Visibility.Visible
        self.revit_host.Visibility = Visibility.Visible if revit_on else Visibility.Collapsed
        self.refresh_preview()

    def reread_click(self, sender, args):
        try:
            self.load_model(keep=True)
            self.refresh_preview()
        except Exception as ex:
            self.fail(ex)

    def tabs_changed(self, sender, args):
        if not self._ready or args.OriginalSource is not self.tabs:
            return
        if self.tabs.SelectedIndex == 1:
            try:
                if self.state is None:
                    self.load_model()
                else:
                    self.bind_all()
                self.refresh_preview()
            except Exception as ex:
                self.fail(ex)

    # ------------------------------------------------------------------ settings tab: source
    def category_changed(self, sender, args):
        if not self._ready or self._reverting:
            return
        if self._cat_index is not None and not self._confirm_discard():
            self._revert(self.category_combo, self._cat_index)
            return
        self._cat_index = self.category_combo.SelectedIndex
        cat = self.current_cat()
        if cat is None:
            return
        self.rs = None
        self.state = None
        self._baseline = None
        self.filter_tab.clear()
        name, count = self.cats[self.category_combo.SelectedIndex][:2]
        self.category_info.Text = u"%d elements. The model is read when you open the Preview tab or press Run." % count
        auto = (u"Abaco %s" % name)[:31]
        if not self.tb_name.Text.strip() or self.tb_name.Text == self._auto_name:
            self.tb_name.Text = auto
        self._auto_name = auto
        self.update_dirty()
        self.preview_status.Text = u"Open this tab to read the model."

    def table_type_changed(self, sender, args):
        if not self._ready or self._reverting:
            return
        if self.rs is not None and self._tt_index is not None and not self._confirm_discard():
            self._revert(self.table_type_combo, self._tt_index)
            return
        self._tt_index = self.table_type_combo.SelectedIndex
        self.table_type_note.Text = self.type_note()
        if self.rs is None:
            return
        self.new_state(self.load_saved_settings())
        self.bind_all()
        self.sync_lists()
        self.filter_tab.load(self.state.settings.get("filter"))
        self.set_baseline()
        self.refresh_preview()

    def _revert(self, combo, index):
        """Puts a combo box back on its previous item after the user refused to discard changes."""
        self._reverting = True
        try:
            combo.SelectedIndex = index
        finally:
            self._reverting = False

    def browse_click(self, sender, args):
        path = forms.save_file(file_ext="xlsx",
                               default_name=os.path.basename(self.tb_path.Text or "Abaco_tables.xlsx"),
                               title="Excel workbook")
        if path:
            self.tb_path.Text = path

    # ---------------------------------------------------------------------- fields tab
    def row_changed(self, row, name):
        """A watched property of a list row was edited by the user."""
        if not self._ready or self._loading or self.state is None:
            return
        if isinstance(row, US.FieldRow):
            self.state.set_include(row.key, row.Include)
            self.update_counts()
            self.bind_format()
            self.sync_lists()
        elif isinstance(row, US.LevelRow):
            self.state.level_update(row.Index - 1, row)
        self.refresh_preview()

    def update_field_buttons(self):
        if self.state is None:
            return
        idx = self.fields_list.SelectedIndex
        n = self.fields_list.Items.Count
        self.btn_field_up.IsEnabled = idx > 0
        self.btn_field_down.IsEnabled = 0 <= idx < n - 1
        self.btn_field_remove.IsEnabled = idx >= 0

    def _field_index_of(self, key):
        for i, s in enumerate(self.state.settings["fields"]):
            if s["key"] == key:
                return i
        return -1

    def _move_selected_field(self, delta):
        row = self.fields_list.SelectedItem
        if row is None or self.state is None:
            return
        if self.state.move(row.key, delta):
            self.bind_fields()
            self.bind_format()
            self.sync_lists()
            i = self._field_index_of(row.key)          # keep the moved field selected
            if i >= 0:
                self.fields_list.SelectedIndex = i
            self.update_field_buttons()
            self.refresh_preview()

    def field_up_click(self, sender, args):
        self._move_selected_field(-1)

    def field_down_click(self, sender, args):
        self._move_selected_field(1)

    def field_remove_click(self, sender, args):
        row = self.fields_list.SelectedItem
        if row is None or self.state is None:
            return
        if not self.state.remove_field(row.key):
            self.log(u"At least one field must stay in the table.")
            return
        self.bind_fields()
        self.bind_format()
        self.sync_lists()
        self.refresh_preview()

    # ----------------------------------------------------------- Add parameter icon column
    def _is_custom(self, row):
        return self.state is not None and self.state.is_custom(row.key)

    def _selected_row(self):
        """The selected row of the list the user clicked last: a table field or an Add parameter entry."""
        if self._active_list == "table":
            return self.fields_list.SelectedItem
        return self.suggest_list.SelectedItem

    def update_suggest_buttons(self):
        row = self._selected_row()
        custom = row is not None and self._is_custom(row)
        self.btn_param_add.IsEnabled = self._active_list == "suggest" and row is not None
        self.btn_param_custom.IsEnabled = True
        self.btn_param_edit.IsEnabled = custom
        self.btn_param_delete.IsEnabled = custom
        self.update_field_buttons()

    def table_selection_changed(self, sender, args):
        if self._ready:
            self._active_list = "table"
            self.update_suggest_buttons()

    def suggest_selection_changed(self, sender, args):
        if self._ready:
            self._active_list = "suggest"
            self.update_suggest_buttons()

    def param_search_changed(self, sender, args):
        if self._ready and self.state is not None:
            self.bind_suggest()

    def suggest_add_click(self, sender, args):
        row = self.suggest_list.SelectedItem
        if row is None or self.state is None:
            return
        if self.state.add_field(row.key):
            self.bind_fields()
            self.bind_format()
            self.refresh_preview()

    def open_field_editor(self, key=None):
        """Custom field editor over this window. key = the field to edit, None for a new field."""
        if self.state is None:
            self.load_model()
        if self.state is None or self.rs is None:
            self.log(u"The model is not read yet. Open the Preview tab first.")
            return
        existing = None
        if key is not None:
            found = [d for d in self.state.settings.get("custom", []) if d.get("key") == key]
            if not found:
                self.log(u"That custom field is not in the settings.")
                return
            existing = found[0]

        ctx = FE.EditorContext(doc, self.rs, self.state.settings, self.state.table_keys(),
                               key, self.state.labels, self.log)
        new = FE.open_editor(self, script.get_bundle_file("new_parameter.xaml"), ctx, existing)
        if new is None:
            return

        settings = self.state.settings
        settings["custom"] = [d for d in settings.get("custom", []) if d.get("key") != new["key"]] + [new]
        if key is None and not any(f["key"] == new["key"] for f in settings["fields"]):
            settings["fields"].append(P.field_setting(new["key"]))   # a new field goes into the table
        self.new_state(settings)                                      # rebuilds the catalogue and labels
        self.bind_all()
        self.sync_lists()
        self.refresh_preview()

    def suggest_custom_click(self, sender, args):
        self.open_field_editor(None)

    def suggest_edit_click(self, sender, args):
        if self.state is None:
            return
        row = self._selected_row()
        if row is not None and self._is_custom(row):
            self.open_field_editor(row.key)

    def suggest_delete_click(self, sender, args):
        if self.state is None:
            return
        row = self._selected_row()
        if row is None or not self._is_custom(row):
            return
        self.delete_custom_field(row.key)

    def delete_custom_field(self, key):
        """Deletes a custom field from the table, the settings, the sort levels and the filter."""
        settings = self.state.settings
        defs = settings.get("custom", [])
        target = [d for d in defs if d.get("key") == key]
        if not target:
            self.log(u"That custom field is not in the settings.")
            return
        name = target[0].get("name", key)

        # custom fields whose formulas read this one will show #ERROR after the delete
        token = u"{%s}" % key
        users = [d.get("name", d.get("key")) for d in defs
                 if d.get("key") != key and token in (d.get("formula") or u"")]
        msg = u"Delete the custom field '%s'?\n\nIt is removed from the table, its sort levels and its filter " \
              u"conditions. This cannot be undone." % name
        if users:
            msg += u"\n\nThese fields use it and will show #ERROR: " + u", ".join(users)
        if not forms.alert(msg, title=u"Delete custom field", yes=True, no=True):
            return

        settings["custom"] = [d for d in defs if d.get("key") != key]
        settings["fields"] = [f for f in settings["fields"] if f.get("key") != key]
        settings["levels"] = [l for l in settings.get("levels", []) if l.get("key") != key]

        # the filter tab holds its own rows: remove them first, or sync_lists would bring them back
        self.filter_tab.remove_key(key)

        self.new_state(settings)          # attach_custom drops the catalogue entry
        self.bind_all()
        self.sync_lists()
        self.refresh_preview()
        self.log(u"Deleted custom field '%s'." % name)

    def fields_reset_click(self, sender, args):
        if self.state is None or self.rs is None:
            return
        self.new_state(self.default_settings(self.tb_title.Text.strip()))
        self.bind_all()
        self.sync_lists()
        self.refresh_preview()

    # ----------------------------------------------------------------- sort and group tab
    def level_row_click(self, sender, args):
        btn = args.OriginalSource
        while btn is not None and not isinstance(btn, Button):
            btn = getattr(btn, "Parent", None)
        if btn is None or btn.Tag != "remove" or self.state is None or btn.DataContext is None:
            return
        self.state.level_remove(btn.DataContext.Index - 1)
        self.bind_levels()
        self.refresh_preview()

    def level_add_click(self, sender, args):
        if self.state is not None:
            self.state.level_add()
            self.bind_levels()
            self.refresh_preview()

    def level_clear_click(self, sender, args):
        if self.state is not None:
            self.state.level_clear()
            self.bind_levels()
            self.refresh_preview()

    def options_changed(self, sender, args):
        if not self._ready or self._loading or self.state is None:
            return
        s = self.state.settings
        s["grandTotals"] = bool(self.chk_grand_totals.IsChecked)
        s["itemize"] = bool(self.chk_itemize.IsChecked)
        self.bind_format()
        self.refresh_preview()

    def rownum_changed(self, sender, args):
        if not self._ready or self._loading or self.state is None:
            return
        rn = self.state.settings.get("rowNumbers") or {}
        self.state.settings["rowNumbers"] = {"on": bool(self.chk_rownum.IsChecked),
                                             "heading": rn.get("heading", u"No.")}
        self.refresh_preview()

    def rownum_heading_changed(self, sender, args):
        if not self._ready or self._loading or self.state is None:
            return
        rn = self.state.settings.get("rowNumbers") or {}
        self.state.settings["rowNumbers"] = {"on": bool(rn.get("on")),
                                             "heading": self.tb_rownum_heading.Text}
        self.refresh_preview()

    # --------------------------------------------------------------------------- filter tab
    def filter_add_click(self, sender, args):
        if self.filter_tab is not None:
            self.filter_tab.add()

    def filter_clear_click(self, sender, args):
        if self.filter_tab is not None:
            self.filter_tab.clear()

    def filter_match_click(self, sender, args):
        if self._ready and self.filter_tab is not None:
            self.filter_tab.changed()

    # ------------------------------------------------------------------------- formatting tab
    def _fmt_key(self):
        row = self.format_list.SelectedItem
        return row.key if row is not None else None

    def format_selection_changed(self, sender, args):
        if self._ready and not self._loading:
            self.load_format_form()

    def load_format_form(self):
        key = self._fmt_key()
        if key is None or self.state is None:
            self.fmt_panel.IsEnabled = False
            self.fmt_title.Text = u"Select a field"
            return
        v = self.state.format_values(key)
        self._loading_fmt = True
        try:
            self.fmt_panel.IsEnabled = True
            self.fmt_title.Text = u"Format: %s" % self.state.label(key)
            self.fmt_heading.Text = v["heading"]
            self.align_l.IsChecked = (v["align"] == "left")
            self.align_c.IsChecked = (v["align"] == "center")
            self.align_r.IsChecked = (v["align"] == "right")
            auto = v["widthMm"] is None
            self.fmt_auto.IsChecked = auto
            self.fmt_width.IsEnabled = not auto
            self.fmt_width.Text = u"" if auto else (u"%g" % v["widthMm"])
            self.fmt_calc.SelectedIndex = CALC_TAGS.index(v["calc"]) if v["calc"] in CALC_TAGS else 0
            self.fmt_hidden.IsChecked = v["hidden"]
            self.fmt_excel.IsChecked = v["excel"]
        finally:
            self._loading_fmt = False

    def _apply_format(self, **kw):
        if not self._ready or self._loading_fmt or self.state is None:
            return
        key = self._fmt_key()
        if key is None:
            return
        self.state.format_set(key, **kw)
        self.state.update_format_row(self.format_list.SelectedItem)
        self.refresh_preview()

    def fmt_heading_changed(self, sender, args):
        if not self._ready or self._loading_fmt:
            return
        self._apply_format(heading=self.fmt_heading.Text)

    def align_click(self, sender, args):
        if not self._ready:
            return
        self._apply_format(align=str(sender.Tag))

    def fmt_width_changed(self, sender, args):
        if not self._ready or self._loading_fmt or self.fmt_auto.IsChecked:
            return
        try:
            w = US.parse_decimal(self.fmt_width.Text)
        except ValueError:
            return                                   # still typing
        if w > 0:
            self._apply_format(widthMm=w)

    def fmt_auto_click(self, sender, args):
        if not self._ready or self._loading_fmt or self.state is None:
            return
        if self.fmt_auto.IsChecked:
            self.fmt_width.IsEnabled = False
            self._apply_format(widthMm=None)
            return
        # switching to fixed: start from the width the column has now
        w, key = 20.0, self._fmt_key()
        try:
            text_mm, page_h = self.text_and_page()
            lay = build_layout(self.result.revit, text_mm, page_h)
            i = [c.key for c in self.result.revit.columns].index(key)
            w = round(lay.col_w[i], 1)
        except Exception:
            pass
        self.fmt_width.IsEnabled = True
        self._loading_fmt = True
        self.fmt_width.Text = u"%g" % w
        self._loading_fmt = False
        self._apply_format(widthMm=w)

    def fmt_calc_changed(self, sender, args):
        if not self._ready or self._loading_fmt:     # fires while the XAML loads
            return
        item = self.fmt_calc.SelectedItem
        if item is not None:
            self._apply_format(calc=str(item.Tag))

    def fmt_flag_click(self, sender, args):
        if not self._ready:
            return
        self._apply_format(hiddenInRevit=bool(self.fmt_hidden.IsChecked),
                           showInExcel=bool(self.fmt_excel.IsChecked))

    # ----------------------------------------------------------------------- appearance tab
    def app_guard(self):
        return not self._ready or self._loading_app or self.state is None

    def bind_appearance(self):
        if self.state is None:
            return
        app = self.state.app()
        self._loading_app = True
        try:
            codes = [c for _, c in AP.THEMES]
            self.theme_combo.ItemsSource = [l for l, _ in AP.THEMES]
            self.theme_combo.SelectedIndex = codes.index(app["theme"]) if app["theme"] in codes else len(codes) - 1
            self.accent_panel.Visibility = Visibility.Visible if app["theme"] == "accent" else Visibility.Collapsed
            self.cmb_font.ItemsSource = US.installed_fonts()
            self.cmb_font.SelectedItem = app["font"]["family"]
            self.tb_font_mm.Text = u"%g" % app["font"]["sizeMm"]
            self.chk_wrap.IsChecked = bool(app["wrap"])
            self.tb_blank_mm.Text = u"%g" % app["blankMm"]
            self.sw_accent.Background = US.brush(app["accent"])
            self.chk_zebra.IsChecked = bool(app["zebra"]["on"])
            self.sw_zebra.Background = US.brush(app["zebra"]["color"])
            self.sw_lines.Background = US.brush(app["lines"]["color"])
            self.chk_lines_outer.IsChecked = bool(app["lines"]["outer"])
            self.chk_lines_inner.IsChecked = bool(app["lines"]["inner"])
            self.chk_freeze.IsChecked = bool(app["excel"]["freezeHeading"])
            self.chk_gridlines.IsChecked = bool(app["excel"]["gridlines"])
            self.elem_list.ItemsSource = self.state.app_element_rows(self.app_row_changed)
        finally:
            self._loading_app = False

    def theme_changed(self, sender, args):
        if self.app_guard():
            return
        code = AP.THEMES[self.theme_combo.SelectedIndex][1]
        if code == "custom":
            return
        self.state.app_theme(code)
        self.bind_appearance()
        self.refresh_preview()

    def font_changed(self, sender, args):
        if self.app_guard() or self.cmb_font.SelectedItem is None:
            return
        item = self.cmb_font.SelectedItem
        if item == US.FONT_SEP:                       # separator: keep the current font
            self._loading_app = True
            try:
                self.cmb_font.SelectedItem = self.state.app()["font"]["family"]
            finally:
                self._loading_app = False
            return
        self.state.app_set(("font", "family"), item)
        self.bind_appearance()
        self.refresh_preview()

    def _num(self, ctrl, lo, hi):
        try:
            v = US.parse_decimal(ctrl.Text)
        except ValueError:
            return None
        return v if lo <= v <= hi else None

    def font_size_changed(self, sender, args):
        if self.app_guard():
            return
        v = self._num(self.tb_font_mm, 1.0, 10.0)
        if v is not None:
            self.state.app_set(("font", "sizeMm"), v)
            self.refresh_preview()

    def blank_changed(self, sender, args):
        if self.app_guard():
            return
        v = self._num(self.tb_blank_mm, 0.5, 50.0)
        if v is not None:
            self.state.app_set(("blankMm",), v)
            self.refresh_preview()

    def app_check_click(self, sender, args):
        if self.app_guard():
            return
        path = {"chk_wrap": ("wrap",), "chk_zebra": ("zebra", "on"),
                "chk_lines_outer": ("lines", "outer"), "chk_lines_inner": ("lines", "inner"),
                "chk_freeze": ("excel", "freezeHeading"), "chk_gridlines": ("excel", "gridlines")}.get(sender.Name)
        if path is None:
            return
        self.state.app_set(path, bool(sender.IsChecked))
        self.bind_appearance()
        self.refresh_preview()

    def swatch_click(self, sender, args):
        """Accent, zebra and line colours."""
        if self.app_guard():
            return
        app = self.state.app()
        tag = sender.Tag
        current = {"accent": app["accent"], "zebra": app["zebra"]["color"], "lines": app["lines"]["color"]}[tag]
        new = color_picker.pick(current)
        if not new:
            return
        if tag == "accent":
            app["accent"] = new
            if app["theme"] == "accent":
                self.state.app_theme("accent")
        elif tag == "zebra":
            self.state.app_set(("zebra", "color"), new)
        else:
            self.state.app_set(("lines", "color"), new)
        self.bind_appearance()
        self.refresh_preview()

    def elem_row_click(self, sender, args):
        """Text colour, background colour and clear-background buttons in the Elements list."""
        btn = args.OriginalSource
        while btn is not None and not isinstance(btn, Button):
            btn = getattr(btn, "Parent", None)
        if btn is None or self.state is None:
            return
        tag, row = btn.Tag, btn.DataContext
        if tag not in ("text", "bg", "bgnone") or row is None:
            return
        if tag == "bgnone":
            self.state.app_color(row.element, "background", None)
        else:
            which = "color" if tag == "text" else "background"
            current = self.state.app()["elements"][row.element][which] or "#FFFFFF"
            new = color_picker.pick(current)
            if not new:
                return
            self.state.app_color(row.element, which, new)
        self.bind_appearance()
        self.refresh_preview()

    def app_row_changed(self, row, name):
        if self.app_guard():
            return
        self.state.app_element_update(row)
        self.refresh_preview()

    # ------------------------------------------------------------------------------- save
    def save_click(self, sender, args):
        if self.state is None or self.rs is None:
            self.log(u"Nothing to save yet: open the Preview tab first.")
            return
        try:
            self.filter_tab.flush()                       # pending typing in a filter value
            self.state.settings["title"] = self.tb_title.Text.strip()
            self.state.settings["filter"] = self.filter_tab.to_settings()
            SS.put_saved(self.store, self.category_key(), self.table_type(),
                         self.state.settings, self.current_output())
            SS.write_file(self.store_path, self.store)
            self.set_baseline()
            self.status(u"Settings saved: %s (%s)" % (self.category_key(), self.table_type()))
            self.log(u"Settings saved to %s" % self.store_path)
        except Exception as ex:
            self.fail(ex)

    # -------------------------------------------------------------------------------- run
    def validate(self):
        errs, v = [], {}
        revit_on, excel_on = bool(self.chk_revit.IsChecked), bool(self.chk_excel.IsChecked)
        if not (revit_on or excel_on):
            errs.append(u"Tick at least one output (Revit or Excel).")
        v["name"] = self.tb_name.Text.strip()
        errs += US.check_table_name(v["name"], revit_on, excel_on)
        if revit_on:
            try:
                v["page_h"] = US.parse_decimal(self.tb_page_h.Text)
                if not (50.0 <= v["page_h"] <= 5000.0):
                    errs.append(u"Max table height must be between 50 and 5000 mm.")
            except ValueError:
                errs.append(u"Max table height is not a number.")
        if excel_on:
            v["path"] = self.tb_path.Text.strip()
            errs += US.check_excel_path(v["path"])
        v["revit"], v["excel"] = revit_on, excel_on
        return errs, v

    def run_click(self, sender, args):
        errs, v = self.validate()
        if errs:
            forms.alert(u"\n".join(errs), title="Check the settings")
            return
        self.btn_run.IsEnabled = False
        try:
            self.do_run(v)
        except Exception as ex:
            self.fail(ex)
        finally:
            self.btn_run.IsEnabled = True

    def do_run(self, v):
        self.status(u"Running...")
        if self.rs is None:
            self.load_model()
        self.filter_tab.flush()                        # pending typing in a filter value
        try:
            res = self.current_result()
        except NoMatch:
            forms.alert(u"No elements match the filter, so there is nothing to write.\n"
                        u"Change or clear the conditions in the Filter tab.", title="Abaco Tables")
            self.status(u"Nothing written: the filter matches no element")
            return
        self.result = res
        for w in self.filter_result.warnings:
            self.log(u"Warning: %s" % w)
        if self.filter_result.n_active:
            self.log(self.filter_result.summary())
        for w in res.warnings:
            self.log(u"Warning: %s" % w)
        ok = []
        if v["revit"]:
            try:
                text_mm, page_h = self.text_and_page()[0], v["page_h"]
                with revit.Transaction("Abaco Tables"):
                    lines = runner.draw_revit(doc, res, v["name"], text_mm, page_h)
                for ln in lines:
                    self.log(ln)
                ok.append(u"Revit")
            except Exception as ex:
                self.log(u"REVIT FAILED (nothing was changed): %s" % ex)
                self.log(traceback.format_exc())
        if v["excel"]:
            try:
                self.log(runner.write_excel(v["path"], v["name"], res))
                ok.append(u"Excel")
            except Exception as ex:
                self.log(u"EXCEL FAILED: %s" % ex)
                self.log(traceback.format_exc())
        self.status(u"Done: " + (u", ".join(ok) if ok else u"nothing written, see the log"))

    def close_click(self, sender, args):
        self.Close()

    # ---------------------------------------------------------------------------- lists sync
    def sync_lists(self):
        """Fields, Sort & group and Filter all draw on the Fields tab: refresh the lists that offer them."""
        if self.rs is None or self.state is None:
            return
        self.bind_levels()
        self.filter_tab.set_catalogue(self.rs, self.state.table_keys())


if __name__ == "__main__":
    if not doc or doc.IsFamilyDocument:
        forms.alert("Open a Revit project first.", exitscript=True)
    AbacoWindow().show_dialog()