# -*- coding: utf-8 -*-
"""Colour choice for the Appearance tab, using PixiEditor ColorPicker (WPF).

Files in this folder: ColorPicker.dll and ColorPicker.Models.dll (both from the same release).
The control is created in code and hosted in a modal window. If it cannot be used, pick() shows the
reason and falls back to a #RRGGBB prompt.
"""
import os
import re

import clr
from pyrevit import forms

_HERE = os.path.dirname(os.path.abspath(__file__))
_HEX = re.compile(r"^#?[0-9A-Fa-f]{6}$")
_last_error = [None]
_loaded = [False]


def _load():
    """Load both assemblies from this folder, once."""
    if _loaded[0]:
        return
    clr.AddReferenceToFileAndPath(os.path.join(_HERE, "ColorPicker.Models.dll"))
    clr.AddReferenceToFileAndPath(os.path.join(_HERE, "ColorPicker.dll"))
    _loaded[0] = True


def _to_hex(color):
    return u"#%02X%02X%02X" % (color.R, color.G, color.B)


def _pixi_pick(current_hex):
    """'#RRGGBB' or None when cancelled."""
    _load()
    from ColorPicker import StandardColorPicker
    from System.Windows import (Window, Thickness, RoutedEventHandler, SizeToContent,
                                WindowStartupLocation, ResizeMode, HorizontalAlignment)
    from System.Windows.Controls import StackPanel, Button, Orientation
    from System.Windows.Media import Color

    h = current_hex.lstrip("#")
    picker = StandardColorPicker()
    picker.Width = 260
    picker.Height = 380
    picker.SelectedColor = Color.FromRgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    ok = Button()
    ok.Content = u"OK"
    ok.Width = 70
    ok.Margin = Thickness(0, 0, 6, 0)
    ok.IsDefault = True

    cancel = Button()
    cancel.Content = u"Cancel"
    cancel.Width = 70
    cancel.IsCancel = True

    buttons = StackPanel()
    buttons.Orientation = Orientation.Horizontal
    buttons.HorizontalAlignment = HorizontalAlignment.Right
    buttons.Margin = Thickness(0, 8, 0, 0)
    buttons.Children.Add(ok)
    buttons.Children.Add(cancel)

    root = StackPanel()
    root.Margin = Thickness(10)
    root.Children.Add(picker)
    root.Children.Add(buttons)

    win = Window()
    win.Title = u"Abaco colour"
    win.Content = root
    win.SizeToContent = SizeToContent.WidthAndHeight
    win.ResizeMode = ResizeMode.NoResize
    win.WindowStartupLocation = WindowStartupLocation.CenterScreen
    win.ShowInTaskbar = False

    result = {"hex": None}

    def ok_click(sender, args):
        result["hex"] = _to_hex(picker.SelectedColor)
        win.Close()

    ok.Click += RoutedEventHandler(ok_click)
    win.ShowDialog()
    return result["hex"]


def pick(current_hex):
    """'#RRGGBB' or None when cancelled."""
    current_hex = current_hex or u"#000000"
    try:
        return _pixi_pick(current_hex)
    except Exception as ex:
        _last_error[0] = u"%s" % ex
    forms.alert(u"Colour picker could not open: %s\n\nEnter the colour as #RRGGBB instead." % _last_error[0],
                title="Abaco colour")
    text = forms.ask_for_string(default=current_hex, prompt="Colour as #RRGGBB", title="Abaco colour")
    if not text:
        return None
    text = text.strip()
    if not _HEX.match(text):
        forms.alert(u"Not a colour: %s" % text)
        return None
    if not text.startswith("#"):
        text = "#" + text
    return text.upper()