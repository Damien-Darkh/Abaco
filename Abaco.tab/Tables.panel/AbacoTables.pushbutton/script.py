# -*- coding: utf-8 -*-
__title__ = "Abaco\nTables"
__doc__ = ("Builds the Abaco quantity tables (walls, curtain walls, floors, roofs, ceilings, doors, windows...) "
           "and draws them as drafting views on sheets and/or writes them to Excel.")

import re
import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
from System import Action
from System.Collections.Generic import List
from System.Windows.Controls import DataGridTextColumn
from System.Windows.Data import Binding
from System.Windows.Input import Cursors
from System.Windows.Threading import DispatcherPriority
from Microsoft.Win32 import SaveFileDialog

from pyrevit import DB, forms, script, revit

from abaco.table_builder import build_table, eid_val
from abaco.layout import build_layout
from abaco import drafting
from abaco.excel_writer import write_table, col_letter

doc = revit.doc

# ----------------------------------------------------------------------------------------------
# Defaults (values that were hard-wired in the Dynamo graph). Edit here for another project.
# ----------------------------------------------------------------------------------------------
_XL_DIR = r"\\192.168.1.52\001 - lavori correnti\026 BASTIA UMBRA PALAZZETTO\excel"
PRESETS = {
    False: dict(path=_XL_DIR + "\\Abaco Murature.xlsx",
                name="Abaco Murature", title="Abaco Muratura", prefix="AM"),
    True:  dict(path=_XL_DIR + "\\Abaco Curtain Walls.xlsx",
                name="Abaco Curtain Walls", title="Abaco Curtain Walls", prefix="AC"),
}
DEFAULT_HIDDEN = "Wall Type Name;Order;Function"
DEFAULT_TEXT_MM = "2.5"
DEFAULT_PAGE_H_MM = "490"

_BAD_VIEW_CHARS = re.compile(r"[\\:{}\[\]|;<>?`~]")      # not allowed in Revit view names
_BAD_TAB_CHARS = re.compile(r"[\\/:*?\[\]]")             # not allowed in Excel tab names


def _elements_filter(cat):
    return (DB.FilteredElementCollector(doc)
            .WherePasses(DB.ElementCategoryFilter(cat.Id))
            .WhereElementIsNotElementType())


def list_model_categories():
    """Model categories that actually have elements in this project: [(name, count, Category)]."""
    items = []
    for cat in doc.Settings.Categories:
        try:
            if cat.CategoryType != DB.CategoryType.Model:
                continue
            n = _elements_filter(cat).GetElementCount()
        except Exception:
            continue
        if n:
            items.append((cat.Name, n, cat))
    items.sort(key=lambda t: t[0].lower())
    return items


def is_walls(cat):
    return eid_val(cat.Id) == int(DB.BuiltInCategory.OST_Walls)


class AbacoWindow(forms.WPFWindow):
    _ready = False          # XAML fires Checked/SelectionChanged while loading; ignore until set up

    def __init__(self):
        forms.WPFWindow.__init__(self, script.get_bundle_file("ui.xaml"))
        self._cats = []
        self._titleblocks = []
        self._fill_categories()
        self._fill_titleblocks()

        self.tb_hidden.Text = DEFAULT_HIDDEN
        self.tb_text_mm.Text = DEFAULT_TEXT_MM
        self.tb_page_h.Text = DEFAULT_PAGE_H_MM
        self.tb_path.Text = PRESETS[False]["path"]
        self._ready = True
        self._refresh_category(set_path=True)

    # ------------------------------------------------------------------ setup
    def _fill_categories(self):
        self._cats = list_model_categories()
        pick = 0
        for i, (name, count, cat) in enumerate(self._cats):
            self.category_combo.Items.Add(u"%s  (%d)" % (name, count))
            if is_walls(cat):
                pick = i
        if self._cats:
            self.category_combo.SelectedIndex = pick

    def _fill_titleblocks(self):
        coll = (DB.FilteredElementCollector(doc)
                .OfCategory(DB.BuiltInCategory.OST_TitleBlocks).WhereElementIsElementType())
        for fs in coll:      # collector order: first one is the default (same as the Dynamo graph)
            nm = fs.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
            self.cmb_titleblock.Items.Add(u"%s : %s" % (fs.FamilyName, nm))
            self._titleblocks.append(fs)
        self.cmb_titleblock.Items.Add(u"<No title block>")
        self._titleblocks.append(None)
        self.cmb_titleblock.SelectedIndex = 0

    # ------------------------------------------------------------------ helpers
    def _selected(self):
        i = self.category_combo.SelectedIndex
        return self._cats[i] if 0 <= i < len(self._cats) else None

    def _walls_selected(self):
        sel = self._selected()
        return bool(sel) and is_walls(sel[2])

    def _curtain_selected(self):
        return self._walls_selected() and bool(self.mode_curtain.IsChecked)

    def _refresh_category(self, set_path):
        """Category / wall-mode changed: fill the fields the Dynamo graph picked with its switch nodes."""
        sel = self._selected()
        if not sel:
            return
        name, count, cat = sel
        self.category_info.Text = u"%d elements in the model" % count
        self.wall_mode_panel.IsEnabled = is_walls(cat)
        if is_walls(cat):
            p = PRESETS[self._curtain_selected()]
            if set_path:
                self.tb_path.Text = p["path"]
            self.tb_name.Text, self.tb_title.Text, self.tb_prefix.Text = p["name"], p["title"], p["prefix"]
        else:
            # other categories: own tab in the same workbook, title blank = "Abaco <Category>"
            self.tb_name.Text = u"Abaco %s" % name
            self.tb_title.Text = u""
            self.tb_prefix.Text = u"A" + name[:1].upper()

    def _log(self, msg):
        self.log_box.AppendText(u"%s\n" % msg)
        self.log_box.ScrollToEnd()
        self._pump()

    def _pump(self):
        """Let WPF repaint while the (synchronous) work is running."""
        self.Dispatcher.Invoke(Action(lambda: None), DispatcherPriority.Render)

    def _busy(self, on, text=None):
        self.btn_run.IsEnabled = self.btn_preview.IsEnabled = not on
        self.Cursor = Cursors.Wait if on else None
        self.status_text.Text = text or ("Working…" if on else "Ready")
        self._pump()

    def _read_settings(self):
        sel = self._selected()
        if not sel:
            raise ValueError("Pick a category.")
        s = dict(cat=sel[2], cat_name=sel[0], curtain=self._curtain_selected())
        s["title"] = self.tb_title.Text.strip()
        s["name"] = self.tb_name.Text.strip()
        s["hidden"] = self.tb_hidden.Text
        s["do_revit"] = bool(self.chk_revit.IsChecked)
        s["do_excel"] = bool(self.chk_excel.IsChecked)
        s["prefix"] = self.tb_prefix.Text.strip()
        s["path"] = self.tb_path.Text.strip().strip('"')
        s["title_block"] = self._titleblocks[max(self.cmb_titleblock.SelectedIndex, 0)]
        for key, box, label in (("text_mm", self.tb_text_mm, "Text height"),
                                ("page_h_mm", self.tb_page_h, "Max table height")):
            try:
                s[key] = float(box.Text.strip().replace(",", "."))      # accepts 2,5 as well as 2.5
            except ValueError:
                raise ValueError("%s must be a number." % label)
            if s[key] <= 0:
                raise ValueError("%s must be greater than 0." % label)
        if not s["name"]:
            raise ValueError("Table name is required.")
        if _BAD_VIEW_CHARS.search(s["name"]):
            raise ValueError("Table name contains characters Revit does not allow in view names:  \\ : { } [ ] | ; < > ? ` ~")
        if s["do_excel"]:
            if _BAD_TAB_CHARS.search(s["name"]) or len(s["name"]) > 31:
                raise ValueError("Table name is also the Excel tab name: max 31 characters, none of  \\ / : * ? [ ]")
            if not s["path"].lower().endswith(".xlsx"):
                raise ValueError("The Excel workbook path must end with .xlsx")
        if s["do_revit"] and not s["prefix"]:
            raise ValueError("Sheet number prefix is required.")
        if not (s["do_revit"] or s["do_excel"]):
            raise ValueError("Tick at least one output (Revit or Excel).")
        return s

    def _build(self, s):
        elements = list(_elements_filter(s["cat"]).ToElements())
        table = build_table(doc, elements, s["title"], s["curtain"])
        return elements, table

    def _show_preview(self, table):
        grid = self.preview_grid
        grid.Columns.Clear()
        ncols = max(len(r) for r in table)
        for i in range(ncols):
            col = DataGridTextColumn()
            col.Header = col_letter(i + 1)
            col.Binding = Binding("[%d]" % i)
            grid.Columns.Add(col)
        rows = List[object]()
        for r in table:
            row = List[object]()
            for i in range(ncols):
                v = r[i] if i < len(r) else u""
                row.Add(u"" if v is None else u"%s" % v)
            rows.Add(row)
        grid.ItemsSource = rows
        self.preview_note.Text = u"%d rows x %d columns (title and header included, blank rows separate type blocks)." % (
            len(table), ncols)

    # ------------------------------------------------------------------ events
    def category_changed(self, sender, args):
        if self._ready:
            self._refresh_category(set_path=self._walls_selected())

    def mode_changed(self, sender, args):
        if self._ready:
            self._refresh_category(set_path=True)

    def browse_click(self, sender, args):
        dlg = SaveFileDialog()
        dlg.Title = "Excel workbook"
        dlg.Filter = "Excel workbook (*.xlsx)|*.xlsx"
        dlg.OverwritePrompt = False         # we write into the workbook, we do not replace it
        dlg.CheckFileExists = False
        dlg.FileName = self.tb_path.Text
        if dlg.ShowDialog():
            self.tb_path.Text = dlg.FileName

    def close_click(self, sender, args):
        self.Close()

    def preview_click(self, sender, args):
        try:
            s = self._read_settings_for_preview()
        except ValueError as ex:
            forms.alert(str(ex), title="Abaco Tables", warn_icon=True)
            return
        self._busy(True, "Reading model…")
        try:
            elements, table = self._build(s)
            self._show_preview(table)
            self.tabs.SelectedIndex = 1
            self._log(u"Preview: %d elements -> %d table rows." % (len(elements), len(table)))
        except Exception as ex:
            self._log(u"ERROR: %s" % ex)
        finally:
            self._busy(False)

    def _read_settings_for_preview(self):
        """Preview only needs category + title; do not demand valid output settings."""
        sel = self._selected()
        if not sel:
            raise ValueError("Pick a category.")
        return dict(cat=sel[2], title=self.tb_title.Text.strip(), curtain=self._curtain_selected())

    def run_click(self, sender, args):
        try:
            s = self._read_settings()
        except ValueError as ex:
            forms.alert(str(ex), title="Abaco Tables", warn_icon=True)
            return

        self._busy(True, "Reading model…")
        try:
            elements, table = self._build(s)
            self._show_preview(table)
            n_data = sum(1 for r in table[2:] if any(c != u"" for c in r))
            self._log(u"--- %s | %s ---" % (s["cat_name"], "curtain walls" if s["curtain"] else "standard"))
            self._log(u"Collected %d elements -> %d table rows." % (len(elements), n_data))
            if n_data == 0:
                self._log(u"Nothing to export for this selection (check the category / wall type).")
                return

            if s["do_revit"]:
                self._busy(True, "Drawing tables in Revit…")
                self._run_revit(s, table)
            if s["do_excel"]:
                self._busy(True, "Writing Excel…")
                self._run_excel(s, table)
            self._log(u"Done.")
        except Exception as ex:
            self._log(u"ERROR: %s" % ex)
        finally:
            self._busy(False)

    def _run_revit(self, s, table):
        t = DB.Transaction(doc, u"Abaco tables: %s" % s["name"])
        t.Start()
        try:
            layout = build_layout(table, s["text_mm"], s["page_h_mm"], s["hidden"])
            report = layout.report + drafting.build_tables(
                doc, layout, s["name"], s["prefix"], s["text_mm"], s["title_block"])
            t.Commit()
        except Exception as ex:
            t.RollBack()
            self._log(u"Revit: FAILED, nothing was changed. %s" % ex)
            return
        for line in report:
            self._log(u"Revit: %s" % line)

    def _run_excel(self, s, table):
        try:
            self._log(u"Excel: %s" % write_table(s["path"], s["name"], table))
        except Exception as ex:
            self._log(u"Excel: FAILED. %s" % ex)


if __name__ == "__main__":
    if not doc or doc.IsFamilyDocument:
        forms.alert("Open a Revit project first.", exitscript=True)
    AbacoWindow().ShowDialog()
