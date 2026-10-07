# -*- coding: utf-8 -*-
"""Phase 3 check (temporary dev button): draw + write multiple categories with deliberately varied settings.

Run it in a TEST COPY of the project: it creates drafting views and sheets named 'Abaco Phase3 check ...'.
What to look at afterwards:
  Revit : right / centred text inside its column, vertical Level heading (reads bottom to top, centred,
          clear of the lines), bold total / min / max rows with a line above, grand totals at the end.
  Run 2 : the same views are UPDATED in place (see the report), no new sheets.
  Excel : real formulas in the total rows (click a cell), alignment, number formats, the vertical
          heading column is not as wide as its heading text.
Delete this button when Phase 4 is done.
"""
import os
import re
import tempfile
import traceback
from pyrevit import forms, script, revit

from abaco import revit_reader as rr
from abaco import pipeline as P
from abaco import runner
from abaco.sheet import build_sheet
from abaco.excel_writer import write_table
from abaco.records import (K_LAYER_THICKNESS, K_LAYER_MATERIAL, K_LAYER_AREA, K_WIDTH, K_FAMILY,
                           K_LEVEL, K_COUNT)

doc = revit.doc
NAME = u"Abaco Phase3 check"

TARGET_CATEGORIES = {
    "Ceilings",
    "Curtain Panels",
    "Curtain Wall Mullions",
    "Doors",
    "Floors",
    "Roofs",
    "Rooms",
    "Walls",
    "Windows",
}


def tweak(settings):
    """Exercise every Phase 3 feature that applies to the fields of this table."""
    for f in settings["fields"]:
        k = f["key"]
        if k in (K_LAYER_THICKNESS, K_WIDTH):
            f["align"] = "right"
        if k in (K_LAYER_MATERIAL, K_FAMILY):
            f["align"] = "center"
        if k == K_LEVEL:
            f["orientation"] = "vertical"
        if k in (K_LAYER_THICKNESS, K_COUNT):
            f["calc"] = "total"
        if k == K_LAYER_AREA:
            f["calc"] = "minmax"
    settings["grandTotals"] = True


def make_excel_sheet_title(raw_title):
    """Clean and truncate Excel tab title to fit within Excel's 31 character limit."""
    cleaned = re.sub(r'[:\\/?*\[\]]', '', raw_title)
    return cleaned[:31].strip()


def main():
    out = script.get_output()
    cats = rr.list_model_categories(doc)

    # Filter categories matching TARGET_CATEGORIES that have elements in the model (>0 count)
    selected_cats = [c for c in cats if c[0] in TARGET_CATEGORIES and c[1] > 0]

    if not selected_cats:
        out.print_md(u"**No elements found for the target categories.**")
        return

    for name, count, cat in selected_cats:
        out.print_md(u"---")
        out.print_md(u"## Phase 3 check: %s (%d elements)" % (name, count))

        try:
            rs = rr.read_category(doc, cat)
            settings = P.default_settings(rs, "standard", u"Phase 3 check")
            tweak(settings)
            rr.ensure_values(doc, rs, P.required_keys(settings))
            res = P.build_table(rs, settings)

            for w in res.warnings:
                out.print_md(u"- warning: %s" % w)
            out.print_md(u"- %d columns in Revit, %d in Excel." % (len(res.revit.columns), len(res.excel.columns)))

            view_name = u"%s - %s" % (NAME, name)
            for run in (1, 2):
                with revit.Transaction("Abaco Phase 3 check %s (run %d)" % (name, run)):
                    lines = runner.draw_revit(doc, res, view_name, u"P3", 2.5, 490, None)
                out.print_md(u"**Revit, run %d**" % run)
                for ln in lines:
                    out.print_md(u"- %s" % ln)

            excel_filename = "abaco_phase3_check_%s.xlsx" % name.lower().replace(" ", "_")
            path = os.path.join(tempfile.gettempdir(), excel_filename)
            sh = build_sheet(res.excel)
            
            # Truncate tab title to <=31 characters
            sheet_tab_title = make_excel_sheet_title(view_name)
            out.print_md(u"**Excel**: %s" % write_table(path, sheet_tab_title, sh))
            out.print_md(u"- file: %s" % path)
            out.print_md(u"- first formulas: %s" % sorted(sh.formulas.items())[:4])

        except Exception as ex:
            out.print_md(u"**ERROR processing %s**: %s" % (name, str(ex)))
            out.print_md(u"```\n%s\n```" % traceback.format_exc())


if __name__ == "__main__":
    if not doc or doc.IsFamilyDocument:
        forms.alert("Open a Revit project first.", exitscript=True)
    main()