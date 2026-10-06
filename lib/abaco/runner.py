# -*- coding: utf-8 -*-
"""Glue between the window and the new data / pipeline / output layers (Phase 3).

build()        model -> records -> pipeline -> Result (excel table + revit table)
draw_revit()   Result -> layout -> drafting views and sheets (call inside an open transaction)
write_excel()  Result -> Excel tab

Phase 4 replaces the 'hidden' text box with per-field settings; until then build() maps the v1 text box
('Wall Type Name;Order;Function') onto the Hidden-in-Revit flag of the fields with that heading.
"""
from abaco import revit_reader
from abaco import pipeline
from abaco import drafting
from abaco.layout import build_layout
from abaco.sheet import build_sheet
from abaco.excel_writer import write_table


def build(doc, category, curtain, title, hidden_text, log=None):
    """Returns (RecordSet, pipeline.Result)."""
    rs = revit_reader.read_category(doc, category, log)
    settings = pipeline.default_settings(rs, "curtain" if curtain else "standard", title or u"")
    pipeline.apply_hidden_headings(rs, settings, hidden_text)
    revit_reader.ensure_values(doc, rs, pipeline.required_keys(settings), log)
    return rs, pipeline.build_table(rs, settings)


def draw_revit(doc, result, name, prefix, text_mm, page_h_mm, title_block):
    """Report lines. Must run inside a transaction."""
    report = []
    hidden = [c.heading for c in result.table.columns if c.hidden_in_revit]
    if hidden:
        report.append(u"Hidden in Revit: " + u", ".join(hidden))
    layout = build_layout(result.revit, text_mm, page_h_mm)
    return report + layout.report + drafting.build_tables(doc, layout, name, prefix, text_mm, title_block)


def write_excel(path, name, result):
    return write_table(path, name, build_sheet(result.excel))
