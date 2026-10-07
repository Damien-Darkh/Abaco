# -*- coding: utf-8 -*-
"""Abaco Tables window (Phase 4). Wires ui.xaml to the state (ui_state), the preview (preview) and the
output layers (runner). All table logic lives in lib/abaco; this file only moves values between controls
and the state and calls Run.

Project defaults (prefix, text height, page height, Excel path) are in DEFAULTS below.
"""
import os
import traceback

from pyrevit import forms, script, revit
from pyrevit.forms import WPFWindow
from Autodesk.Revit import DB
from System import Action, Double
from System.Windows import RoutedEventHandler, Visibility, FontWeights
from System.Windows.Controls import Button
from System.Windows.Media import SolidColorBrush, Color
from System.Windows.Threading import DispatcherPriority

from abaco import revit_reader as rr
from abaco import pipeline as P
from abaco import runner
from abaco import ui_state as US
from abaco import preview as PV
from abaco.layout import build_layout

doc = revit.doc

DEFAULTS = {
    "prefix": u"AM",
    "text_mm": u"2.5",
    "page_h": u"490",
    "excel_path": os.path.join(os.path.expanduser("~"), "Documents", "Abaco_tables.xlsx"),
}
CALC_TAGS = list(US.CALC_MODES)            # same order as the fmt_calc items in ui.xaml
TOTAL_BG = SolidColorBrush(Color.FromRgb(0xF1, 0xF5, 0xFB))


class AbacoWindow(WPFWindow):
    # events fire while the XAML loads, before __init__ finishes: class-level defaults keep the handlers safe
    _ready = False
    _loading = False
    _loading_fmt = False

    def __init__(self):
        WPFWindow.__init__(self, script.get_bundle_file("ui.xaml"))
        self.cats = rr.list_model_categories(doc)
        self.rs = None
        self.state = None
        self.result = None
        self._row_kinds = []
        self._auto_name = u""
        self._tb_items = self._title_blocks()
        self._init_controls()
        # one container-level handler per list (XamlReader cannot wire handlers inside DataTemplates)
        self.fields_list.AddHandler(Button.ClickEvent, RoutedEventHandler(self.field_row_click))
        self.suggest_list.AddHandler(Button.ClickEvent, RoutedEventHandler(self.suggest_row_click))
        self.sort_list.AddHandler(Button.ClickEvent, RoutedEventHandler(self.sort_row_click))
        self.tabs.SelectionChanged += self.tabs_changed
        self._ready = True
        self.category_changed(None, None)

    # ------------------------------------------------------------------------------------------ setup
    def _title_blocks(self):
        items = []
        col = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
        for s in col.WhereElementIsElementType():
            try:
                nm = s.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
                items.append((u"%s : %s" % (s.FamilyName, nm), s))
            except Exception:
                continue
        items.sort(key=lambda t: t[0].lower())
        return items

    def _init_controls(self):
        self.category_combo.ItemsSource = [u"%s  (%d)" % (n, c) for n, c, _ in self.cats]
        idx = 0
        for i, (n, c, cat) in enumerate(self.cats):
            if self._is_walls(cat):
                idx = i
                break
        self.category_combo.SelectedIndex = idx if self.cats else -1
        self.cmb_titleblock.ItemsSource = [u"(no title block)"] + [t[0] for t in self._tb_items]
        self.cmb_titleblock.SelectedIndex = 1 if self._tb_items else 0
        self.tb_prefix.Text = DEFAULTS["prefix"]
        self.tb_text_mm.Text = DEFAULTS["text_mm"]
        self.tb_page_h.Text = DEFAULTS["page_h"]
        self.tb_path.Text = DEFAULTS["excel_path"]

    # --------------------------------------------------------------------------------------- helpers
    @staticmethod
    def _is_walls(cat):
        return rr.eid_val(cat.Id) == int(DB.BuiltInCategory.OST_Walls)

    def current_cat(self):
        i = self.category_combo.SelectedIndex
        return self.cats[i][2] if 0 <= i < len(self.cats) else None

    def is_curtain(self):
        cat = self.current_cat()
        return bool(cat is not None and self._is_walls(cat) and self.mode_curtain.IsChecked)

    def title_block(self):
        i = self.cmb_titleblock.SelectedIndex
        return self._tb_items[i - 1][1] if i >= 1 else None

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
        """(text height mm, page height mm); falls back on the defaults while a box holds nonsense."""
        out = []
        for ctrl, key in ((self.tb_text_mm, "text_mm"), (self.tb_page_h, "page_h")):
            try:
                v = US.parse_decimal(ctrl.Text)
                if v <= 0:
                    raise ValueError()
            except ValueError:
                v = float(DEFAULTS[key])
            out.append(v)
        return out[0], out[1]

    # ----------------------------------------------------------------------------- model and state
    def default_settings(self):
        mode = "curtain" if self.is_curtain() else "standard"
        return P.default_settings(self.rs, mode, self.tb_title.Text.strip())

    def load_model(self, keep=False):
        cat = self.current_cat()
        if cat is None:
            return
        old = self.state.settings if (keep and self.state is not None) else None
        self.status(u"Reading the model...")
        self.log(u"Reading %s..." % cat.Name)
        self.rs = rr.read_category(doc, cat, self.log)
        for line in self.rs.summary_lines():
            self.log(line)
        self.category_info.Text = self.rs.summary_lines()[0]
        self.state = US.EditState(self.rs, old if old is not None else self.default_settings())
        self.bind_all()
        self.status(u"Ready")

    def current_result(self):
        s = self.state.settings
        s["title"] = self.tb_title.Text.strip()
        return runner.build_result(doc, self.rs, s, self.log)

    # --------------------------------------------------------------------------- binding the lists
    def bind_all(self):
        self.bind_fields()
        self.bind_sort()
        self.bind_options()
        self.bind_format()

    def bind_fields(self):
        self.fields_list.ItemsSource = self.state.field_rows(self.row_changed)
        self.update_counts()
        self.bind_suggest()

    def update_counts(self):
        shown, avail = self.state.counts()
        self.fields_count.Text = u"%d shown, %d available" % (shown, avail)

    def bind_suggest(self):
        self.suggest_list.ItemsSource = self.state.suggestions(self.tb_param_search.Text)

    def bind_sort(self):
        self.sort_list.ItemsSource = self.state.sort_rows(self.row_changed)
        self.sort_fixed_index.Text = u"%d" % (len(self.state.settings["sort"]) + 1)

    def bind_options(self):
        self._loading = True
        try:
            self.chk_grand_totals.IsChecked = bool(self.state.settings.get("grandTotals"))
            self.chk_itemize.IsChecked = bool(self.state.settings.get("itemize"))
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

    # ------------------------------------------------------------------------------------ preview
    def refresh_preview(self):
        if not self._ready or self.state is None:
            return
        try:
            res = self.current_result()
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
            warn = self.size_warning(lay)
            self.preview_status.Text = u"%d rows, %d columns, %d sheet(s), %.0f mm wide%s%s" % (
                res.revit.n_data_rows(), len(res.revit.columns), len(lay.pages), lay.table_w,
                (u"   |   " + warn) if warn else u"", note)
        else:
            self._row_kinds = PV.fill_grid(self.preview_grid, res.excel)
            self.preview_status.Text = u"%d rows, %d columns%s" % (
                res.excel.n_data_rows(), len(res.excel.columns), note)

    def size_warning(self, lay):
        """Compare the table with the selected title block (sheet size in mm), 20 mm margins like Run."""
        tb = self.title_block()
        if tb is None:
            return u""
        try:
            w = tb.get_Parameter(DB.BuiltInParameter.SHEET_WIDTH).AsDouble() * 304.8
            h = tb.get_Parameter(DB.BuiltInParameter.SHEET_HEIGHT).AsDouble() * 304.8
        except Exception:
            return u""
        out = []
        if lay.table_w + 40 > w:
            out.append(u"table is %.0f mm wide, the sheet only %.0f mm" % (lay.table_w, w))
        tall = max([p.height for p in lay.pages] or [0.0]) + lay.row_h + 40
        if tall > h:
            out.append(u"a page is %.0f mm tall, the sheet only %.0f mm" % (tall, h))
        return u"TOO BIG: " + u"; ".join(out) if out else u""

    def preview_loading_row(self, sender, args):
        try:
            kind = self._row_kinds[args.Row.GetIndex()]
        except Exception:
            return
        row = args.Row
        row.MinHeight = 0
        row.Height = 8.0 if kind == "blank" else Double.NaN
        row.FontWeight = FontWeights.Bold if kind == "total" else FontWeights.Normal
        row.Background = TOTAL_BG if kind == "total" else None

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
                if self.rs is None:
                    self.load_model()
                else:
                    self.bind_all()
                self.refresh_preview()
            except Exception as ex:
                self.fail(ex)

    # ------------------------------------------------------------------------------ settings tab
    def category_changed(self, sender, args):
        if not self._ready:
            return
        cat = self.current_cat()
        if cat is None:
            return
        self.rs = None
        self.state = None
        walls = self._is_walls(cat)
        self.wall_mode_panel.Visibility = Visibility.Visible if walls else Visibility.Collapsed
        name, count = self.cats[self.category_combo.SelectedIndex][:2]
        self.category_info.Text = u"%d elements. The model is read when you open the Preview tab or press Run." % count
        auto = (u"Abaco %s" % name)[:31]
        if not self.tb_name.Text.strip() or self.tb_name.Text == self._auto_name:
            self.tb_name.Text = auto
        self._auto_name = auto
        self.preview_status.Text = u"Open this tab to read the model."

    def mode_changed(self, sender, args):
        if not self._ready or self.rs is None:
            return
        self.state = US.EditState(self.rs, self.default_settings())     # new template, no rescan

    def browse_click(self, sender, args):
        path = forms.save_file(file_ext="xlsx", default_name=os.path.basename(self.tb_path.Text or "Abaco_tables.xlsx"),
                               title="Excel workbook")
        if path:
            self.tb_path.Text = path

    # --------------------------------------------------------------------------------- fields tab
    def row_changed(self, row, name):
        """A watched property of a list row was edited by the user."""
        if not self._ready or self._loading or self.state is None:
            return
        if isinstance(row, US.FieldRow):
            self.state.set_include(row.key, row.Include)
            self.update_counts()
            self.bind_format()
        elif isinstance(row, US.SortRow):
            self.state.sort_set(row.Index - 1, label=row.Column, descending=row.Descending, gap=row.GapRow)
        self.refresh_preview()

    def field_row_click(self, sender, args):
        btn = args.OriginalSource
        tag, row = getattr(btn, "Tag", None), getattr(btn, "DataContext", None)
        if tag not in ("up", "down") or row is None or self.state is None:
            return
        self.state.move(row.key, -1 if tag == "up" else 1)
        self.bind_fields()
        self.bind_format()
        self.refresh_preview()

    def suggest_row_click(self, sender, args):
        btn = args.OriginalSource
        row = getattr(btn, "DataContext", None)
        if getattr(btn, "Tag", None) != "add" or row is None or self.state is None:
            return
        if self.state.add_field(row.key):
            self.bind_fields()
            self.bind_format()
            self.refresh_preview()

    def param_search_changed(self, sender, args):
        if self._ready and self.state is not None:
            self.bind_suggest()

    def fields_reset_click(self, sender, args):
        if self.rs is None:
            return
        self.state = US.EditState(self.rs, self.default_settings())
        self.bind_all()
        self.refresh_preview()

    # --------------------------------------------------------------------------------- sorting tab
    def sort_row_click(self, sender, args):
        btn = args.OriginalSource
        row = getattr(btn, "DataContext", None)
        if getattr(btn, "Tag", None) != "remove" or row is None or self.state is None:
            return
        self.state.sort_remove(row.Index - 1)
        self.bind_sort()
        self.refresh_preview()

    def sort_add_click(self, sender, args):
        if self.state is None:
            return
        self.state.sort_add()
        self.bind_sort()
        self.refresh_preview()

    def sort_clear_click(self, sender, args):
        if self.state is None:
            return
        self.state.sort_clear()
        self.bind_sort()
        self.refresh_preview()

    def options_changed(self, sender, args):
        if not self._ready or self._loading or self.state is None:
            return
        self.state.settings["grandTotals"] = bool(self.chk_grand_totals.IsChecked)
        self.state.settings["itemize"] = bool(self.chk_itemize.IsChecked)
        self.bind_format()
        self.refresh_preview()

    # ------------------------------------------------------------------------------ formatting tab
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
            self.orient_v.IsChecked = (v["orientation"] == "vertical")
            self.orient_h.IsChecked = not self.orient_v.IsChecked
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
        key = self._fmt_key()
        if key is None or self._loading_fmt or not self._ready:
            return
        self.state.format_set(key, **kw)
        self.state.update_format_row(self.format_list.SelectedItem)
        self.refresh_preview()

    def fmt_heading_changed(self, sender, args):
        self._apply_format(heading=self.fmt_heading.Text)

    def orient_click(self, sender, args):
        self._apply_format(orientation=str(sender.Tag))

    def align_click(self, sender, args):
        self._apply_format(align=str(sender.Tag))

    def fmt_width_changed(self, sender, args):
        if self._loading_fmt or self.fmt_auto.IsChecked:
            return
        try:
            w = US.parse_decimal(self.fmt_width.Text)
        except ValueError:
            return                                   # still typing
        if w > 0:
            self._apply_format(widthMm=w)

    def fmt_auto_click(self, sender, args):
        if self._loading_fmt:
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
        item = self.fmt_calc.SelectedItem
        if item is not None:
            self._apply_format(calc=str(item.Tag))

    def fmt_flag_click(self, sender, args):
        self._apply_format(hiddenInRevit=bool(self.fmt_hidden.IsChecked),
                           showInExcel=bool(self.fmt_excel.IsChecked))

    # ------------------------------------------------------------------------------------------ run
    def validate(self):
        errs, v = [], {}
        revit_on, excel_on = bool(self.chk_revit.IsChecked), bool(self.chk_excel.IsChecked)
        if not (revit_on or excel_on):
            errs.append(u"Tick at least one output (Revit or Excel).")
        v["name"] = self.tb_name.Text.strip()
        errs += US.check_table_name(v["name"], revit_on, excel_on)
        if revit_on:
            for ctrl, key, label, lo, hi in ((self.tb_text_mm, "text_mm", u"Text height", 1.0, 10.0),
                                             (self.tb_page_h, "page_h", u"Max table height", 50.0, 5000.0)):
                try:
                    v[key] = US.parse_decimal(ctrl.Text)
                    if not (lo <= v[key] <= hi):
                        errs.append(u"%s must be between %g and %g mm." % (label, lo, hi))
                except ValueError:
                    errs.append(u"%s is not a number." % label)
            v["prefix"] = self.tb_prefix.Text.strip()
            if not v["prefix"]:
                errs.append(u"Enter a sheet number prefix.")
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
        res = self.current_result()
        self.result = res
        for w in res.warnings:
            self.log(u"Warning: %s" % w)
        ok = []
        if v["revit"]:
            try:
                text_mm, page_h = v["text_mm"], v["page_h"]
                warn = self.size_warning(build_layout(res.revit, text_mm, page_h))
                if warn:
                    self.log(u"Warning: %s" % warn)
                with revit.Transaction("Abaco Tables"):
                    lines = runner.draw_revit(doc, res, v["name"], v["prefix"], text_mm, page_h, self.title_block())
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


if __name__ == "__main__":
    if not doc or doc.IsFamilyDocument:
        forms.alert("Open a Revit project first.", exitscript=True)
    AbacoWindow().show_dialog()
