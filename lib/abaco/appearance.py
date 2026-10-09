# -*- coding: utf-8 -*-
"""Appearance (Preview > Appearance). Pure Python: no Revit, no WPF.

settings["appearance"] is JSON-ready and shared by the Revit drawing and the Excel sheet.
"theme" is the preset last chosen; any single change makes it "custom".
Font size is the text height in mm (Revit's unit); Excel converts it to points.
"""
try:
    _STR = (str, unicode)
except NameError:
    _STR = (str,)

THEMES = [(u"Black & white", "bw"), (u"Office", "office"), (u"Accent", "accent"), (u"Custom", "custom")]
CASES = [(u"None", "none"), (u"UPPER", "upper"), (u"lower case", "lower"),
         (u"Title Case", "title"), (u"Sentence case", "sentence")]
CASE_CODE = dict((lab, code) for lab, code in CASES)
CASE_LABEL = dict((code, lab) for lab, code in CASES)
ELEMENTS = [("title", u"Title"), ("heading", u"Heading row"), ("header", u"Group header rows"),
            ("summaryHeader", u"Summary header"), ("summary", u"Summary rows"), ("data", u"Data rows")]
ALIGNS = [(u"Left", "left"), (u"Center", "center"), (u"Right", "right")]
ALIGN_CODE = dict((lab, code) for lab, code in ALIGNS)
ALIGN_LABEL = dict((code, lab) for lab, code in ALIGNS)
ORIENTS = [(u"Horizontal", "horizontal"), (u"Vertical", "vertical")]
ORIENT_CODE = dict((lab, code) for lab, code in ORIENTS)
ORIENT_LABEL = dict((code, lab) for lab, code in ORIENTS)


def _el(bold=False, case="none", lines=True, italic=False, underline=False,
        color="#000000", background=None, align=None, orientation=None):
    d = {"bold": bold, "italic": italic, "underline": underline, "case": case,
         "color": color, "background": background, "lines": lines}
    if align is not None:
        d["align"] = align              # not set on data rows: their alignment is per field
    if orientation is not None:
        d["orientation"] = orientation  # heading row only
    return d


def preset(theme="bw", accent="#2F6FDE"):
    a = {
        "theme": theme,
        "accent": accent,
        "font": {"family": u"Arial", "sizeMm": 2.5},
        "wrap": False,
        "blankMm": 8.0,
        "elements": {
            "title": _el(bold=True, case="upper", align="center"),
            "heading": _el(bold=True, case="title", align="left", orientation="horizontal"),
            "header": _el(bold=True, case="title", lines=False, align="left"),
            "summaryHeader": _el(bold=True, case="title", lines=False, align="left"),
            "summary": _el(case="sentence", align="left"),
            "data": _el(),
        },
        "zebra": {"on": False, "color": "#E3E9F2"},
        "lines": {"color": "#000000", "outer": True, "inner": True},
        "excel": {"freezeHeading": True, "gridlines": False},
    }
    if theme == "office":
        a["elements"]["heading"]["background"] = "#E7EAF0"
        a["elements"]["summary"].update(bold=True, background="#F4F6F9")
        a["zebra"]["on"] = True
        a["lines"]["color"] = "#9AA3B2"
    elif theme == "accent":
        a["elements"]["heading"].update(background=accent, color="#FFFFFF")
        a["elements"]["header"]["color"] = accent
        a["elements"]["summaryHeader"]["color"] = accent
        a["elements"]["summary"].update(bold=True, background="#EAF1FD")
        a["lines"]["color"] = accent
    return a

def _merge(base, over):
    for k, v in over.items():
        if k not in base:
            continue
        b = base[k]
        if isinstance(b, dict):
            if isinstance(v, dict):
                _merge(b, v)
        elif b is None or _same_kind(b, v):
            base[k] = v


def _same_kind(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return True
    return isinstance(a, _STR) and isinstance(b, _STR)


def normalize(d):
    """Full appearance dict from saved settings. Missing or bad values fall back to Black & white."""
    out = preset("bw")
    if isinstance(d, dict):
        _merge(out, d)
    if out["theme"] not in [c for _, c in THEMES]:
        out["theme"] = "custom"
    return out


def case_of(app, element):
    return app["elements"][element]["case"]


def is_text(v):
    return isinstance(v, _STR)


def apply_case(text, mode):
    """Display only: labels, formulas and sort order keep their original text."""
    if not text or mode in (None, "none"):
        return text
    if mode == "upper":
        return text.upper()
    if mode == "lower":
        return text.lower()
    if mode == "title":
        return u" ".join(w[:1].upper() + w[1:] for w in text.split(u" "))
    if mode == "sentence":
        return text[:1].upper() + text[1:].lower()
    return text