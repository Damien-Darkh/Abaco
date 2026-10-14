# -*- coding: utf-8 -*-
"""Light and dark theme for the Abaco windows, following Revit's UI theme.

revit_is_dark() reads Revit's UI theme (UIThemeManager, Revit 2025 and later). Older versions return light.
themed_xaml() returns the path of the XAML to load: the original for light, or a dark copy written to the
temp folder under the source file's name, so two windows never overwrite each other's copy.

Colours in the light XAML are replaced by their dark equivalents. Paper and Excel preview areas use
#FFFFFF in the XAML, so they are not in the list and stay white in both themes.
"""
import io
import os
import re
import tempfile

_LIGHT_TO_DARK = {
    "#F4F5F7": "#1E2128",    # window background
    "#D5D9E0": "#3A4150",    # Line (borders)
    "#E6E8EC": "#2F3541",    # LineSoft (separators, grid lines)
    "#5B6472": "#A9B2C3",    # Muted (labels)
    "#1C1F24": "#E8EAEE",    # Ink (main text)
    "#FDEBD9": "#5A3C1E",    # WarnBg
    "#8A4B08": "#F2B67A",    # WarnText
    "#E3F3EA": "#1F4A32",    # GoodBg
    "#14653D": "#7FD3A0",    # GoodText
    "#FBE3E3": "#4A2626",    # ErrBg (field editor)
    "#9B1C1C": "#F4B4B4",    # ErrText (field editor)
    "#EAF1FD": "#26354F",    # AccentSoft
    "#E6EEFB": "#26354F",    # ChipInfo
    "#EEF0F3": "#3A4150",    # Chip
    "#3B4350": "#C9D0DC",    # chip, segmented and small button text
    "#EEF2FA": "#2C3A52",    # button hover
    "#F4F7FC": "#262C38",    # tab and list hover
    "#8A93A3": "#6E788A",    # drag grip
    "#F0F2F5": "#2A303B",    # grid header
    "#E3E7ED": "#181B21",    # Revit preview scroll area
    "#2459B8": "#5B8EE8",    # AccentHover
}
_SURFACE_DARK = "#262A33"    # cards, text boxes, buttons, combo boxes


def revit_is_dark():
    """True when Revit's UI theme is dark. False on older Revit versions or when the check fails."""
    try:
        from Autodesk.Revit.UI import UIThemeManager, UITheme
        return UIThemeManager.CurrentTheme == UITheme.Dark
    except Exception:
        return False


def _recolour(text):
    for light, dark in _LIGHT_TO_DARK.items():
        text = re.sub(re.escape(u'"%s"' % light), u'"%s"' % dark, text, flags=re.IGNORECASE)
    text = re.sub(r'(Background=")White(")', r'\g<1>%s\g<2>' % _SURFACE_DARK, text)
    text = re.sub(r'(Property="Background" Value=")White(")', r'\g<1>%s\g<2>' % _SURFACE_DARK, text)
    return text


def themed_xaml(src, dark, log=None):
    """Path of the XAML to load. Falls back to the light file if the dark copy is not valid XML."""
    if not dark:
        return src
    with io.open(src, "r", encoding="utf-8") as f:
        text = _recolour(f.read())
    try:
        import xml.dom.minidom
        xml.dom.minidom.parseString(text.encode("utf-8"))
    except Exception as ex:
        if log:
            log(u"Dark theme copy is not valid XML, using light: %s" % ex)
        return src
    base = os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(tempfile.gettempdir(), "abaco_%s_dark.xaml" % base)
    with io.open(out, "w", encoding="utf-8") as f:
        f.write(text)
    return out