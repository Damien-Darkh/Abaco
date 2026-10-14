# Abaco Tables

**Quantity tables for Revit, built from the model and written to Excel.**

![Abaco Tables main window](docs/images/main-window.png)
<!-- Placeholder: full window, Preview tab open, Walls category -->

![Licence](https://img.shields.io/badge/licence-TBD-lightgrey)
![Revit](https://img.shields.io/badge/Revit-2024%20%7C%202025%20%7C%202026%20%7C%202027-blue)
![pyRevit](https://img.shields.io/badge/pyRevit-6.5%2B-orange)

> **Status: pre-release.** Developed and tested on Revit 2025. Revit 2024, 2026 and 2027 are being smoke-tested. Do not run it on a live project before you have tried it on a copy.

Abaco Tables is a pyRevit extension. You choose a model category, shape the table in a settings window, and Abaco writes it to the drawing as drafting views on sheets, to an Excel workbook, or both. The preview on screen shows exactly what gets written.

---

## Features

- **Two table types.** A *Schedule* gives one row per type, level and size. A *Material takeoff* expands each layered type into its layers, with thickness, function and material area.
- **Live preview.** *As Excel* and *As Revit* show the same table, built from the same data.
- **Revit drawing.** Tables become drafting views on sheets. Re-running updates the existing views in place.
- **Excel output.** Writes one tab of an `.xlsx` workbook, with number formats, live `SUBTOTAL` formulas, merged headings, borders, freeze panes and optional row numbers.
- **Sort, group and footers.** Nested levels with header, footer and gap rows, totals, minimum and maximum per block, and a grand summary.
- **Filters.** Conditions on model fields and calculated fields, combined with AND or OR.
- **Custom calculated fields.** Formulas with `{Field}` references, checked as you type, with a dry run on the model before you save.
- **Appearance.** Presets, fonts from the machine, per-element bold, italic, underline, case, alignment, colours and lines. Follows Revit's light or dark UI theme.
- **Units.** Follows the project's Project Units for length, area and volume.
- **Row numbers.** An optional numbering column that counts visible rows.

---

## Limitations

- **Text colour is not drawn in Revit.** Revit draws text in black in drafting views. Colour appears in Excel and in the preview.
- **Excel output replaces the chosen tab on each run.** Other tabs are left untouched, but the tab's previous contents are lost. Keep manual notes in a different tab.
- **Revit output needs a title block to size sheets.** Without one, the drafting views are created but not placed on sheets.
- **Calculated-field filters run after grouping**, on row values. Model-field filters run on elements before grouping.
- **Excel output requires desktop Excel.** Excel must be installed and registered for COM.
- **Custom model parameters are not in this release.** Calculated fields only. Model parameters are planned for version 2.

---

## Requirements

| Item | Version |
|---|---|
| Autodesk Revit | 2025 (tested). 2024, 2026 and 2027 in progress |
| pyRevit | 6.5 or newer |
| Microsoft Excel | Desktop Excel, for the Excel output |

---

## Installation

1. Download the latest release and unzip it. You should have an `Abaco.extension` folder.
2. Copy `Abaco.extension` to a folder of your choice, for example `C:\pyRevitExtensions\`.
3. In Revit, open **pyRevit > Settings > Custom Extension Directories**, add the parent folder (`C:\pyRevitExtensions\`), then click **Save Settings and Reload**.
4. A new **Abaco** tab appears with an **Abaco Tables** button.

> **Revit 2027:** attach pyRevit as *CurrentUser*. All-users manifests are rejected for unsigned add-ins.

---

## Quick start

> **Warning:** Abaco creates drafting views and sheets and can change Excel files. Try it on a **copy** of your project first.

1. Open a copy of the project.
2. Click **Abaco Tables**.
3. In **Settings**, choose the category (for example *Walls*) and the table type.
4. Open the **Preview** tab. Abaco reads the model, and the table appears on the right.
5. Adjust fields, sorting, formatting and appearance on the left. The preview updates as you go.
6. In **Settings**, choose the outputs: Revit views and sheets, Excel workbook, or both. Click **Run**.

For a step-by-step guide to every tab, see the [user guide](docs/user-guide.md).

---

## Documentation

- [User guide](docs/user-guide.md): every tab, with examples.
- [Formula reference](docs/formulas.md): the custom field language.
- [Development plan](development.md): phases, decisions and the version 2 roadmap.

---

## Running the tests

```bash
python3 tests/run_all.py
```

No Revit is needed for the unit tests. The Revit-side checks run from temporary buttons inside a test copy of a project.

The core code runs on IronPython 2.7 (pyRevit's engine) and CPython 3, so the tests run outside Revit.

---

## Roadmap

**Version 1 (current)**
- Schedules and material takeoffs for any category with elements
- Revit drafting views, sheets and Excel output
- Filters, sorting, grouping, footers and the grand summary
- Calculated custom fields, with the formula editor
- Appearance presets and dark theme
- Saved settings per category
- Row numbers

**Version 2 (planned)**
- Custom model parameters, bound to the model
- Two-way notes sync with Excel
- Arrays and `len()` in formulas
- Restart row numbers per block of a level
- Direct `.xlsx` writer, for machines without Excel

---

## Contributing

Issues and suggestions are welcome. Open an issue before a larger change. Code must run on IronPython 2.7 and CPython 3: no f-strings, and `u""` literals for text.

---

## Acknowledgements

- [pyRevit](https://github.com/pyrevitlabs/pyRevit), the framework this extension runs on
- [PixiEditor ColorPicker](https://github.com/PixiEditor/ColorPicker), used for colour selection

---

## Licence

To be decided before public release. Until a licence is added, the code is not open for reuse.
