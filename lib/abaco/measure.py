# -*- coding: utf-8 -*-
"""Text measurement for the layout. Pure Python: uses System.Drawing inside pyRevit, and an estimate
elsewhere (for example in CPython tests).

Widths are in mm for text whose em height is em_mm (the appearance's text height).
"""
import re

FALLBACK_GLYPH = 0.60                       # average glyph width / em, used only without System.Drawing
_TOKEN = re.compile(u"[^\\s\\-]*-|[^\\s\\-]+|\\s+")   # words and hyphen pieces: Revit breaks after both
_gdi = None                                 # None = not tried yet, False = unavailable, else the tools
_fonts = {}
_cache = {}


def _init():
    global _gdi
    if _gdi is None:
        try:
            import clr
            clr.AddReference("System.Drawing")
            from System.Drawing import Bitmap, Graphics, Font, FontStyle, GraphicsUnit, StringFormat
            g = Graphics.FromImage(Bitmap(4, 4))
            g.PageUnit = GraphicsUnit.Millimeter
            _gdi = (g, Font, FontStyle, GraphicsUnit, StringFormat.GenericTypographic)
        except Exception:
            _gdi = False
    return _gdi


def _font(family, em_mm, bold, italic):
    g, Font, FontStyle, GraphicsUnit, _fmt = _gdi
    if bold and italic:
        style = FontStyle.BoldItalic
    elif bold:
        style = FontStyle.Bold
    elif italic:
        style = FontStyle.Italic
    else:
        style = FontStyle.Regular
    key = (family, round(em_mm, 3), style)
    if key not in _fonts:
        try:
            _fonts[key] = Font(family, em_mm, style, GraphicsUnit.Millimeter)
        except Exception:
            _fonts[key] = Font(u"Arial", em_mm, style, GraphicsUnit.Millimeter)
    return _fonts[key]


def width_mm(text, family, em_mm, bold=False, italic=False):
    """Width of `text` in mm, measured with the font when possible."""
    if not text:
        return 0.0
    key = (text, family, round(em_mm, 3), bool(bold), bool(italic))
    if key in _cache:
        return _cache[key]
    gdi = _init()
    if gdi:
        size = gdi[0].MeasureString(text, _font(family, em_mm, bold, italic), 100000, gdi[4])
        w = float(size.Width)
    else:
        w = len(text) * em_mm * FALLBACK_GLYPH
    _cache[key] = w
    return w


def wrap_lines(text, avail_mm, family, em_mm, bold=False, italic=False, safety=1.0):
    """Split `text` into lines that fit `avail_mm`, breaking after spaces and hyphens.
    `safety` scales the measured widths (1.06 = plan for 6 % more width than measured)."""
    if not text or avail_mm <= 0:
        return [text or u""]

    def w(s):
        return width_mm(s.rstrip(), family, em_mm, bold, italic) * safety

    out, cur = [], u""
    for tok in _TOKEN.findall(text):
        if tok.isspace():
            if cur.strip():
                cur += u" "
            continue
        if not cur.strip():
            cur = tok
        elif w(cur + tok) > avail_mm:
            out.append(cur.rstrip())
            cur = tok
        else:
            cur += tok
        while len(cur.strip()) > 1 and w(cur) > avail_mm:    # one piece longer than the line
            k = len(cur) - 1
            while k > 1 and w(cur[:k]) > avail_mm:
                k -= 1
            out.append(cur[:k])
            cur = cur[k:]
    out.append(cur.strip())
    return out


def count_lines(text, avail_mm, family, em_mm, bold=False, italic=False, safety=1.0):
    return len(wrap_lines(text, avail_mm, family, em_mm, bold, italic, safety))
