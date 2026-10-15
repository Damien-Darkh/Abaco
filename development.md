# Abaco Tables: Development Plan

Last updated: 14 October 2026

- **Target:** Revit 2024, 2025, 2026 and 2027, with pyRevit 6.5 or newer for v1.
- **Status:** v1 (pyRevit MVP). Phases 1 to 7 done for Revit 2025. Phase 0 still needs the Revit 2024 and 2027 smoke tests.
- **Version 1 scope:** calculated custom fields, saved settings, and row numbers, on top of Phases 0 to 7.
- **Later versions:** see section 6. v2 (standalone add-in) is decided after MVP feedback and a prototype.
- **UI reference:** the Preview tab as built is the reference.

---

## 0. Overview

### 0.1 Folder layout (v1)

---

## 0. Overview

### 0.1 Folder layout

```
Abaco.extension/
  lib/abaco/
    records.py                model data, neutral (no Revit)
    units.py                  units, decimals, display text, M2 (no Revit)
    revit_reader.py           the only module that reads the Revit API for the data layer; rs.project from Project Units
    pipeline.py               settings -> table (no Revit)
    layout.py                 table -> drawing geometry, paged (no Revit)
    measure.py                text measurement for the layout (System.Drawing)
    drafting.py               draws views and sheets (Revit)
    sheet.py                  table -> Excel sheet model (no Excel)
    excel_writer.py           Excel COM writer
    runner.py                 glue: records + settings -> results, drawing, Excel
    preview.py                As Excel grid and As Revit canvas
    appearance.py             presets, styles, case, alignment (no Revit)
    ui_state.py               window state and row items (no WPF on CPython)
    filters.py                filter conditions (no Revit)
    filter_ui.py              Filter tab controller
    formula.py                formula tokenizer, parser, unit and type checker (no Revit)
    evaluate.py               formula evaluator, per row, incl. NONE and VARIES (no Revit)
    field_editor.py           custom field editor code-behind
    ui_theme.py               light and dark copies of the XAML files, following Revit 2025
    color_picker.py           PixiEditor colour picker, with hex fallback
    ColorPicker.dll, ColorPicker.Models.dll

  Abaco.tab/
    Tables.panel/
      AbacoTables.pushbutton/
        script.py             Tables window code
        ui.xaml               Tables window
        new_parameter.xaml    custom field editor, opened modally over the Tables window

      AbacoTest.pushbutton/
        script.py

      Phase3Check.pushbutton/ temporary, delete after Phase 13
        script.py


      Phase6Check.pushbutton/ temporary, delete after Phase 13
        script.py


  tests/                      run with python3 tests/run_all.py
    records
    units
    pipeline
    outputs
    ui
    filters
    formula
    evaluate
    custom
    formula integration
```


Held for v4, not part of v1: `model_params.py`, `param_writer.py` and `tests/test_model_params.py`. They are not added to the extension until Phase 8 starts.

`table_builder.py` is retired. Delete it once Phase 0 passes.

### 0.2 Guiding rules

1. **One source of truth.** The preview, the Revit drawing and the Excel file all read the same pipeline output. What you see is what is written.
2. **Pure Python wherever possible.** Pipeline, layout, formula and evaluator have no Revit dependency, so they are tested outside Revit. This also keeps a later port possible.
3. **Read the model deliberately.** Changing a setting recomputes in memory. The model is read again only by Re-read model, or when the category or table type changes. The one exception is the formula dry run, which loads only the fields a formula refers to (see Phase 5).
4. **Common-subset Python.** Code must run on IronPython 2.7 (pyRevit default engine) and CPython 3. No f-strings. Use `u""` literals.
5. **Revit-version-safe API use.** `ElementId.Value`, `ForgeTypeId` units, `SpecTypeId`. Never `IntegerValue`, `UnitType`, `ParameterType`.
6. **Honest limits.** Anything Revit cannot draw is said so in the UI and in this plan, and Excel carries it instead.

---

## 1. Phase summary

| Phase | Name | Status | Release | Depends on |
|---|---|---|---|---|
| 0 | Baseline: runs on every target Revit version | In progress, in Revit 2025 | v1 | none |
| 1 | Data layer: flat records | Done | v1 | 0 |
| 2 | Pipeline: settings to table | Done | v1 | 1 |
| 3 | Output layers: Revit drawing and Excel writer | Done (known Revit limits) | v1 | 2 |
| 4 | Window: Settings, Preview, Appearance, theme | Done | v1 | 2, 3 |
| 5 | Formula language and evaluator | Done (IronPython verified in Revit, 13 October 2026) | v1 | 2 |
| 6 | Custom fields in the table: catalogue, pipeline, calculated fields | Done (Revit check: 26 of 26 passed) | v1 | 4, 5 |
| 7 | Custom field editor and icon column | Done (Revit tested, 14 October 2026) | v1 | 4, 6 |
| 8 | Custom model parameters (Revit) | Planned | v4 | 7 |
| 9 | Saved settings, per category | Planned | v1 | 4, 6, 7 |
| 10 | Notes and comments sync with Excel | Planned | v4 | 8, 9 |
| 11 | Arrays and `len()` in formulas | Planned | v4 | 5, 6 |
| 12 | Row numbers (formatting option) | Planned | v1 | 2 |
| 13 | Testing and release | Planned | v1 | all v1 phases |

Notes / comments stays disabled in the custom field editor until v4.

---

## 2. Phase details

### Phase 0: Baseline

**Goal:** the same behaviour on every supported Revit version.

**Done**
- The extension loads, reads the model, builds tables, writes Excel, and creates drafting views and sheets in Revit 2025.
- `bundle.yaml` is in place for the buttons.
- The inspection of `ColorPicker.dll` was done, and the picker's type names are known.

**To do**
- Smoke test on Revit 2024 and Revit 2027, using the checklist in Phase 13.
- Confirm Excel COM works on each version.
- Attach pyRevit as CurrentUser for Revit 2027 (all-users manifests are rejected for unsigned add-ins).
- Delete `table_builder.py`.

**Done when:** Revit 2024 and 2027 pass the checklist with no unhandled errors.

### Phase 1: Data layer

**Goal:** read the model once into records that hold every value the pipeline may need.

**Done**
- `records.py`: element, type and layer data; field catalogue with scope and kind; display labels that keep twin parameters apart.
- `revit_reader.py`: reads core values, scans the catalogue, loads values on demand and caches them.
- `test_records.py` passes.

**Notes**
- Field keys are stable identifiers (BuiltInParameter name, GUID, or `id:<n>`). Display names are never keys, so an Italian Revit works.
- Values are loaded when a field is first used, to keep large models fast.

### Phase 2: Pipeline

**Goal:** turn records and settings into the table.

**Done**
- Stages: field selection, rows (grouped or itemized, layers expanded), Varies or calculated value per cell, sort and blocks, footers and summary, number formatting, output split.
- One list of levels. Each level has Header, Footer (with its own calculation: per field, totals, min, max, min and max) and Gap row.
- Summary block at the bottom: a bold "Summary" header, then Total, Min and Max rows. Its Excel formulas stay live.
- A cell in a column with a calculation shows the calculated value of its elements. Otherwise it shows the value, or "Varies".
- Sort and group only use fields checked in the Fields tab.
- Footers add up each element once, even for layered walls.

### Phase 3: Output layers

**Goal:** the Revit drawing and the Excel file show the same table.

**Done**
- `measure.py`: measures text with the real font, and breaks lines after spaces and hyphens the way Revit does.
- `layout.py`: auto widths fit the text. Wrapped cells get the height their lines need. Alignment and heading orientation come from the Appearance tab for headings and summary rows, and from each field for data rows. Lines, backgrounds and zebra striping are computed per row. Revit receives the line breaks itself, so it never wraps on its own.
- `drafting.py`: one Revit text type per appearance element (font, size, bold, italic, underline). Thin lines use the `<Thin Lines>` style. Backgrounds and zebra are filled regions. Line colour uses a line style per colour.
- `sheet.py` and `excel_writer.py`: number formats, live `SUBTOTAL` formulas where safe, merges for full-row text, row heights from the line count, freeze panes, gridlines, borders, and a readback of the applied fonts in the log.

**Known limits**
- **Revit text colour:** Revit draws text colour from the view's Text Notes category, so it can only be set for a whole view. Per-cell text colour is not possible. Revit keeps text black. Excel and the preview show the colour.
- **Revit underline and italic** work through text types. Check the type names in Manage > Text Types.

### Phase 4: Window

**Goal:** the window, with every setting in one place and a preview that matches the output.

**Done**
- **Settings:** category, table type, table name and title, Revit options (sheet prefix, title block, page height), Excel workbook.
- **Preview left column:** Fields, Filter, Sort & group, Formatting, Appearance.
- **Preview right column:** As Excel (a grid of styled cells, so every appearance setting shows) and As Revit (a canvas drawn from the same layout).
- **Filter:** conditions with and/or, exact-value combo box with suggestions from the model, numeric and text operators. No quick links.
- **Formatting:** heading, alignment for data, column width, calculation, hidden in Revit, shown in Excel.
- **Appearance:** themes (Black & white, Office, Accent, Custom), font family from the machine, font size in mm, bold, italic, underline, case (none, UPPER, lower, Title, Sentence), per-element text and background colour, lines, zebra, wrap text, blank row height, Excel freeze and gridlines.
- **Theme:** dark window when Revit's UI is dark (Revit 2025 and later). Light otherwise.
- **Colour picker:** PixiEditor ColorPicker, with the hex prompt as a fallback. It needs `ColorPicker.dll` and `ColorPicker.Models.dll` in `lib/abaco/`.

**To do**
- Verify the colour picker opens and returns a colour in Revit 2025 (the fallback runs until then).
- Remove the Max auto width remnants if any remain.

**Done when:** every tab behaves as described, and Run output matches the As Excel and As Revit previews.

### Phase 5: Formula language and evaluator

**Goal:** a formula can be written, checked and evaluated, with no Revit and no UI.

**Status:** done. `formula.py` and `evaluate.py` pass their suites under CPython. The Phase 6 check ran `STRING` and the other functions under IronPython 2.7 in Revit on 13 October 2026.

**Version 1 scope**
- **Grammar:** one expression. No chains, no blocks, no arrays. Chains `IF(c): v; ELIF (c): v; ELSE: v;` and blocks are deferred (section 6.5).
- **Fields:** written `{Label}` in the editor, stored as `{key}`. `[ ]` is reserved for arrays (v4, Phase 11).
- **Operators:** comparison `= != < > <= >=` (no chaining); logic `AND`, `OR` (booleans only, short-circuit); arithmetic `+ - * / %` and `^` (right-associative, whole-number literal exponent when the value has a unit); unary minus; grouping `( )`. `+` also joins two texts. `|x|` is not used: use `ABS(x)`.
- **Conditions:** a bare field may be the condition of `IF`. It is TRUE when the field has a value and FALSE when it is empty. A Yes/No field uses its own value. Expressions such as `{Width} + 1 m` or `{Width} > 1 m` still need TRUE or FALSE. There is no `HASVALUE` function.
- **Functions:** `IF(c, a, b)` (lazy, both branches one type and unit), `MIN`, `MAX`, `SQRT`, `ROOT(x, n)`, `ABS`, `INT` (rounds half away from zero; a text gives its length), `FLOAT`, `STRING` (a literal keeps its typed text, other numbers use the shortest plain form), `SENSITIVE` (case-sensitive text comparison, on one side of `=` or `!=`). `LEN` is reserved and says "not available until version 4". `ROUND(x, n)` is deferred (section 6.5).
- **Keywords:** case-insensitive, shown in capitals everywhere. Reserved: `AND OR IF ELIF ELSE TRUE FALSE SENSITIVE MIN MAX SQRT ROOT ABS INT FLOAT STRING LEN`.
- **Units:** the exponent of `m` is tracked (`m` 1, `m²` 2, `m³` 3). `*` and `/` add and subtract exponents. `+`, `-`, `%` and comparisons need equal exponents; a literal `0` fits any unit. Suffixes `m`, `m²`, `m³` follow a number or a count (`{Count} m` is a length). A count plus a plain number stays a count. `MIN` and `MAX` with different units are refused at save time.
- **Booleans:** `TRUE` and `FALSE` in any letter case. Yes/No fields are booleans in formulas. A boolean result shows as `#TRUE` or `#FALSE`.
- **Empty and errors:** an empty value is `NONE`, shown `#NONE`. Arithmetic, functions and comparisons with NONE give NONE. An element field that varies inside a grouped row is `VARIES`, shown with the table's Varies label. Arithmetic, functions and comparisons with VARIES give VARIES, so itemizing the table recalculates real values. Priority when values combine: an error wins, then NONE, then VARIES. A deciding `FALSE AND x` or `TRUE OR x` wins over NONE and VARIES, because it gives the same answer for every element. Division or remainder by zero and an even root of a negative are `#ERROR` (reasons `div0`, `sqrt_neg`). Other run-time reasons: `ref` (row has no such field), `type` (a row value of the wrong type), `range` (result not a finite number).
- **Numbers:** `=` and `!=` use a tolerance of 1e-6, as filters do. Formulas run on full-precision values, not the rounded display values. `%` follows Python.
- **Save-time checks, which refuse the save:** syntax with position; unknown field with the nearest match; circular reference with the full loop; unit mismatch; type mismatch; `AND` or `OR` on a non-boolean; literal division or remainder by zero; `SQRT` or even `ROOT` of a negative literal; a key containing `}`. Each error carries a position, a reason code (`syntax`, `unit`, `type`, `ref`, `div0`, `sqrt_neg`) and a suggested fix.
- **Save-time dry run, which saves with a warning:** the formula is evaluated for every row. Failures are counted per reason, with up to three examples. Failing rows show `#ERROR`.
- **Dry-run loading:** the dry run loads only the fields the formula refers to, the first time they are needed, and caches them until Re-read model.

**Still to verify in Revit (Phase 13):** both files under IronPython 2.7; `repr()` of a float gives the shortest round-trip text there, which `STRING` relies on.

### Phase 6: Custom fields in the table

**Goal:** calculated fields work in the table like any other field.

**Status:** done (13 October 2026). The Revit check passed 26 of 26 on the Doors and Walls of the test copy. Row values, `#ERROR` and `#NONE` markers, circular references, unknown fields, grand totals, layer footers, the median row filter and the Excel readback all match independent calculations.

**Scope**
- Custom fields enter the catalogue with type and scope, and are marked as custom. The result type comes from the checked formula.
- **Evaluation is per row, after grouping.** A formula sees the row's cell values: a group's `Count`, the summed `Area` and `Total Length`, shared values. So `{Area} / {Count}` is the average area per element and `{Area} * 2` doubles the group's summed area. `evaluate.calculate_row()` runs the fields in `topological_order()`; a circular reference is refused with the loop shown.
- **Live behaviour:** calculated fields are recomputed every time the table is rebuilt: filter, group, sort, formatting or field changes. A row carries every field its formulas use, including fields hidden in Revit or not included in the table. Nothing recomputes when the window is closed.
- **Sort, group, footers, summary:** the calculated value is a row value, so it can be sorted on and can start a new block when it changes. It cannot split a row. Footers and the summary skip `#NONE`, `#ERROR`, `#TRUE` and `#FALSE`, as they skip `Varies`.
- **Filter:** conditions on model fields run on elements before grouping, as in Phase 4. Conditions on calculated fields run after grouping, on row values. A row whose value is VARIES is kept, because its elements may match.
- **Removal:** a field removed from the table with × returns to Add parameter. Formulas that use it show `#ERROR` (reason `ref`), and the removal warning lists them.
- **Names:** custom field names are checked against existing labels when created or edited.

**Units rule**
- A model field (element, type, layer or group scope) takes its dimension from its kind. Its initial unit and decimals come from the project's Project Units, through `revit_reader.project_units()` and `pipeline.project_default()`. The Formatting tab can override either.
- A custom field takes its dimension from its formula's checked result. Its initial unit is the unit that result is computed in, so `{Width} * {Height}` starts in m². The project supplies only the decimals. A custom field's heading does not change when the project's area unit changes.

**Done when:** the Revit checks for a `VARIES` result on a grouped row and for a non-metric project (cm² or ft²) have been run. Both are in the Phase 13 checklist.

### Phase 7: Custom field editor and icon column

**Goal:** create, edit and delete custom fields from the Tables window.

**Status (14 October 2026):** done and tested in Revit for delete, edit, cancel and Escape, self-reference and circular references, and the Notes option. The element-error save check was added after that test and still needs one run (Phase 13, item 19).

**As built**
- **Editor:** a separate modal window, `new_parameter.xaml`, opened over the Tables window. Its code is in `field_editor.py`. Its left column scrolls as a whole, so the keys stay reachable on a short window.
- **Kind:** Calculated or Notes / comments. Notes / comments is selectable so the layout can be reviewed, but Save is blocked while it is selected. It becomes a working option in v4 (Phase 8).
- **Formula:** the checker runs on every change. The result unit is shown read-only, and decimals are automatic.
- **Save:** runs the dry run on the model. If any row would show `#ERROR`, it asks for confirmation. No keeps the editor open. Yes saves, and those rows show `#ERROR`.
- **Table fields:** a selectable list with no include checkbox. A field stays in the table until it is removed. An icon column holds ↑, ↓ and × (remove back to Add parameter). Each is enabled only when it applies.
- **Add parameter:** an icon column holds Add, Custom field, Edit and Delete. Edit and Delete are enabled only for custom fields. They act on the list clicked last.
- **Delete:** removes the field from the custom list, the table, the sort levels, the filter conditions and the catalogue. Formulas that use it are kept and show `#ERROR`. The confirmation names those formulas before deletion.
- **Dark theme:** `ui_theme.py` recolours both XAML files. Each dark copy is written under its source file's name.
- **Icons:** inline WPF path geometry, filled with the theme's Ink brush, so they follow dark mode.

### Phase 8: Custom model parameters (Revit) (v4)

**Goal:** bind parameters in the model and fill them from the table.

**Status:** planned for v4. Not part of v1. The files `model_params.py`, `param_writer.py` and `tests/test_model_params.py` are held outside the extension until this phase starts.

**Prerequisites:** a test project with a shared parameter file and the categories in use. The non-metric check from Phase 6 must be done first.

**Scope (to confirm at the start of v4)**
- **Shared parameters:** Abaco binds definitions that already exist in the project's shared parameter file. It does not add definitions to that file.
- **Project parameters:** not yet confirmed. The public API for a true non-shared project parameter needs checking on the test copy before this is committed. Shared parameters ship first.
- **Kinds:** instance or type, chosen at creation.
- **Categories:** created for every category chosen at creation. The assignment can be edited later.
- **Values:** filled from a formula or a constant, in a transaction, after a confirmation that states how many elements change. A formula fill is per element. Formulas that use `Count` or a layer field are refused, because they have no single per-element value.
- **Delete:** removes the binding. Revit deletes the parameter's values from every element in the model. The shared definition stays in the shared parameter file. The confirmation says so.
- **Name clashes:** checked against table labels and existing parameters in the project.
- **Keys:** a bound parameter appears in Add parameter straight away, keyed by GUID (shared) or `id:<n>` (project), as `revit_reader` already reads them.

**Done when:** a parameter created on the test copy is readable by Abaco, filled from a formula, and removed cleanly.

### Phase 9: Saved settings, per category

**Goal:** the table arrangement survives between sessions.

**Settings file (decided, see section 6.2)**
- v1 (pyRevit): `%APPDATA%\pyRevit\Abaco\tables.json`.
- v2 onward (standalone): `%APPDATA%\Abaco\tables.json`. The same format, so a v1 file is read unchanged.
- The path does not include the Revit year. `C:\ProgramData\Autodesk\Revit\Addins\<year>` is for add-in manifests only, never for settings.

**Scope**
- One file for all categories. Each category and mode (standard or curtain) is one saved object, keyed by its English built-in category name.
- Versioned with `"v": 1`. Unknown fields are ignored. Missing fields take template defaults.
- Saved: fields, levels, filter, formatting (including the row number option), appearance, the Revit and Excel options, and custom calculated fields with their formulas.
- Saved on Run and on window close, not on every change.
- A formula that refers to a missing field is kept and shows `#ERROR` until the field is restored.
- Reset restores template defaults for the current selection. Custom definitions are kept on Reset. Row numbers go back to off.
- A corrupt or old-version file falls back to defaults without an error.

**Open within this phase:** whether a missing field is kept (current proposal) or dropped with a warning when the table is opened in a different project. Settled before the code is written.

**Done when:** closing and reopening restores each category's arrangement, and a corrupt file falls back cleanly.

### Phase 10: Notes and comments sync with Excel (v4)

**Goal:** a notes or comments column in the Excel tab stays in step with the matching model parameter.

**Status:** planned for v4. Depends on Phase 8, because its source is a text model parameter.

**Scope**
- **Source:** a text model parameter from Phase 8, instance kind, one value per element.
- **Element identity:** the element's IfcGUID, which the reader already loads. Element Id is not stable across models and copies, so it is only a fallback.
- **Direction (open):** Excel to model, model to Excel, or both. Proposed: both, with an explicit Sync action. No automatic writes.
- **Conflicts:** if a value changed on both sides since the last sync, both values are shown, and the user chooses. Nothing is overwritten silently.
- **Last-synced snapshot (open):** stored in the table settings, or on a hidden sheet in the workbook. It is what makes a change detectable.
- **Writing to the model:** in a transaction, after a confirmation that states how many elements change.
- **Excel side:** the notes column is found by its heading. Rows are matched by IfcGUID, and rows that no longer exist are reported, not deleted.

**Done when:** a round trip (edit in Excel, sync to the model, change in the model, sync back) works on the test project, and a conflict is shown rather than overwritten.

### Phase 11: Arrays and `len()` in formulas (v4)

**Goal:** arrays and `len()` in formulas.

**Status:** planned for v4. In v1, `LEN` keeps its message "not available until version 4", and `[ ]` is not accepted.

**Scope**
- **Syntax:** array literals `[a, b, c]`, where each item is an expression, including field references. `len(x)` takes an array or a text.
- **Type checker:** an array has an element type. `len` returns a number. Items of one array must share a type when the types are known.
- **Save-time checks:** mixed item types in one array are refused when known. `len` of a number is refused. An empty array literal `[]` is refused, since it has no type.
- **Run time:** an element whose array items differ in type shows `#ERROR` for that element.
- **Arithmetic on arrays** (element by element) is out of scope unless decided later.
- **Keyboard:** `[ ]` and `LEN(` are added to the keys, with tooltips.

**Depends on:** the grammar and checker in Phase 5, and the evaluator in Phase 6.

**Done when:** tests cover array literals, `len` on arrays and text, mixed-type arrays refused at save, and the dry run on sample records.

### Phase 12: Row numbers (formatting option)

**Goal:** a numbering column that shows each visible data row as 1 to N.

**Status:** planned for v1. It is a formatting option, not a field.

**What it is**
- It is **not** a field. It is not in the field catalogue, the Add parameter list, the Fields tab, the filter or the sort levels. A filter or sort cannot use it, because it is computed after both.
- It is a **number option on the Formatting tab**: on or off, and a heading (default "No."). Turning it on inserts a numbering column at the left of the table, in both outputs.
- It numbers **visible data rows** from 1 to N. It is recalculated on every build, after sorting, grouping, filtering and blank-row insertion. It holds no link to an element or row.
- Header, footer, summary and blank rows get no number and do not advance the count.
- In itemized tables, each element row is a data row and gets a number.

**Pipeline**
- Added as the last stage before output. The numbers follow the final order of the table.
- Stage 7 (output split) keeps the number column in both the Revit and Excel outputs.

**Revit output:** static text, written at each build. A rebuild renumbers.

**Excel output:** live. A formula `SUBTOTAL(3, $A$3:A3)` in the index column is circular, because its range includes its own cell. The index therefore uses a hidden helper column:
- Column H (hidden, Excel only) holds `1` on each data row and is empty on header, footer, summary and blank rows.
- Each data row's index cell is `=SUBTOTAL(109,$H$3:H3)`. SUBTOTAL function 109 ignores rows hidden by a filter and rows hidden by hand, and it counts only the non-empty helper cells. The result is 1 to N across visible data rows, and it renumbers after any re-sort in Excel.
- The helper column is placed after the last table column, so it does not shift the table. The helper is hidden and labelled in the workbook notes.
- **Untested.** Test this in Excel before the release notes rely on it.

**Settings**
- One value: `rowNumbers: {"on": bool, "heading": text}`, saved with the table settings (Phase 9). Reset sets it to off.

**Done when:** numbers run from 1 to N across visible data rows, with no gaps across blocks, headers, footers and blank rows, in both outputs. In Excel, the numbers renumber after a re-sort and after a filter.

### Phase 13: Testing and release (v1)

**Goal:** a reliable install and a checklist that catches regressions.

**Automated (no Revit)**
- Update `test_pipeline.py`, `test_outputs.py` and `test_ui.py` to the current structure.
- Add tests for appearance, filters and measurement. Formula and evaluator tests exist; run them under IronPython 2.7 in the AbacoTest button, including `STRING` of a float.
- Add tests for row numbers: numbering across blocks, skipping header, footer, summary and blank rows, and the Excel helper column formula text.
- Add tests for Phase 9: round trip, corrupt file, old version, and Reset keeping custom definitions.
- Run every test file with `python3` on each change.
- Passing on 14 October 2026 under `tests/run_all.py`: custom 24, evaluate 30, filters 16, formula 30, formula integration 2, outputs 17, pipeline 27, records 9, ui 14, units 10.

**Manual checklist (Revit 2024 and 2027; spot-check 2025 and 2026)**
1. The extension loads, and the ribbon button is present.
2. Walls: standard and curtain modes build. The preview matches the drawing.
3. Add a calculated field. Reorder. Hide in Revit. Switch off in Excel.
4. Sort and group with header, footer and gap. Confirm the summary block at the bottom.
5. Wrap text on: the Revit drawing and the preview have the same line breaks, and no row overlaps.
6. Appearance: each element's bold, italic, underline, case, alignment, lines and background, in both previews and the Excel file.
7. Calculated field: works through filter, group, footer and summary. A divide-by-zero element shows `#ERROR`.
8. Custom field removal from the table, then Delete with its confirmation.
9. Run twice: views update in place. Shrink the table: the surplus view is emptied and reported.
10. Excel: new file, existing file, file open elsewhere (read-only error), the tab replaced and other tabs intact.
11. Floors, roofs, doors and windows tables.
12. Italian-language Revit: localised parameter names and the decimal comma.
13. Dark and light Revit UI: every window control is readable.
14. Row numbers: numbers run 1 to N across visible data rows in both outputs, with no gaps across blocks, headers, footers and blank rows. In Excel, the numbers renumber after a re-sort and after a filter.
15. Varies: a custom field on an element field (for example `{Comments} + "!"`) shows Varies on a grouped row and real values when itemized.
16. Non-metric project (cm² or ft²): model fields follow the project unit, custom headings keep the formula's unit.
17. Removing a field with × while a formula uses it shows the warning and `#ERROR`.
18. Sort and group on a calculated field, then Reset and Re-read model: the custom field stays in the window.
19. Save with a formula that gives `#ERROR` on some rows: the confirmation appears, No keeps the editor open, and Yes saves.
20. Row numbers turned on, then Reset: the option is off again, and the custom definitions are kept.
21. Settings: close and reopen Revit, and the table arrangement is restored. Corrupt the file by hand: the table falls back to defaults without an error.

**Release**
- Version in `bundle.yaml`, and a changelog that lists version 1 features and the later items.
- Install notes: pyRevit 6.5 or newer, CurrentUser attach for Revit 2027, desktop Excel for the COM writer, and the two ColorPicker DLLs in `lib/abaco/`.
- Zip of the extension folder. The later-version files are not included.
- Tag the v1 release in source control. This is the freeze point for v1 (section 6.3, item 7).

---

## 3. Decisions log

| Date | Decision |
|---|---|
| 2026-10-02 to 09 | Sort & group is one list of levels, each with Header, Footer and Gap row. |
| 2026-10-08 | Summary is a block at the bottom: bold "Summary" header, then Total, Min and Max. |
| 2026-10-08 | Footers use `SUBTOTAL` formulas, so nested footers are not counted twice. |
| 2026-10-08 | Filter has no quick links. Curtain wall stays a normal field condition. |
| 2026-10-08 | Appearance has presets. Title is centred in every preset. |
| 2026-10-08 | Alignment and heading orientation are per element in Appearance. Data rows keep their per-field alignment in Formatting. |
| 2026-10-08 | Max auto width is removed. Auto columns fit their text. |
| 2026-10-08 | Text height is set in Appearance, not Settings. Page height stays in Settings. |
| 2026-10-08 | Revit text colour is not drawn per cell. Excel and the preview draw it. |
| 2026-10-09 | Dark window follows Revit's UI theme, from Revit 2025. |
| 2026-10-09 | Colour picker is PixiEditor ColorPicker, with the hex prompt as a fallback. |
| 2026-10-09 | Custom field kinds: calculated and model parameter. Notes are a text model parameter. |
| 2026-10-09 | Literal errors refuse the save. Element errors save with a warning and `#ERROR`. |
| 2026-10-09 | Recalculation is live from loaded values. Model re-read only on Re-read model, or a category or table type change. |
| 2026-10-09 | Dry run loads only the fields a formula refers to, once, until Re-read model. |
| 2026-10-09 | × in the table moves a field back to Add parameter. Delete removes a custom field everywhere, after confirmation. |
| 2026-10-13 | Formulas: one expression in version 1, `IF(c, a, b)`. Chains and blocks are deferred. |
| 2026-10-13 | Fields are `{Label}` in the editor and `{key}` stored. Arrays are `[ ]`, v4. |
| 2026-10-13 | `ABS(x)` replaces absolute-value bars. Reserved words: AND OR IF ELIF ELSE TRUE FALSE SENSITIVE MIN MAX SQRT ROOT ABS INT FLOAT STRING LEN. |
| 2026-10-13 | Keywords and function names are case-insensitive, shown in capitals. The editor converts after a complete word, never inside `{ }` or `" "`. |
| 2026-10-13 | Yes/No fields are booleans in formulas. Boolean results show `#TRUE` and `#FALSE`. Empty is `#NONE`. An error wins over NONE. |
| 2026-10-13 | Units: the exponent of `m` is tracked; suffixes `m`, `m²`, `m³` in version 1; a literal `0` fits any unit; count is dimensionless in products. |
| 2026-10-13 | Calculated fields are evaluated per row after grouping and recomputed on every table rebuild. |
| 2026-10-13 | Division by zero is `#ERROR`. `INT` rounds half away from zero. `STRING` keeps a literal's typed text. |
| 2026-10-13 | Units and decimals: the project default comes from Revit's Project Units for each dimension. The Formatting tab can override the unit and decimal places per field. Stored values stay in base units; conversion happens only at output. |
| 2026-10-14 | A Varies input gives a Varies result, not #NONE, so that itemizing recalculates real values. Priority: error, NONE, VARIES. |
| 2026-10-14 | NONE AND FALSE is FALSE, and NONE OR TRUE is TRUE: a deciding value wins on either side. |
| 2026-10-14 | Filters on calculated fields run after grouping, on row values. A VARIES row is kept. |
| 2026-10-14 | Units: model fields start from the project unit and decimals. Custom fields start from the unit their formula computes in; the project sets only their decimals. |
| 2026-10-14 | Phase 6 closed: Revit check 26 of 26 on Doors and Walls, project units read from the model. |
| 2026-10-14 | A bare field is accepted as the condition of IF: TRUE when it has a value, FALSE when empty, its own value for Yes/No. No `HASVALUE` function. |
| 2026-10-14 | The custom field editor is a separate modal window over the Tables window, with its own XAML and code file. |
| 2026-10-14 | Notes / comments is selectable in the editor so the layout can be reviewed. Save is blocked while it is selected. |
| 2026-10-14 | Delete removes a custom field everywhere. Formulas that use it keep their text and show `#ERROR`; the confirmation names them. |
| 2026-10-14 | Table fields are a selectable list with no include checkbox. Removal is by ×, and up and down use an icon column. |
| 2026-10-14 | Edit and Delete follow the list clicked last. Both are enabled for custom fields only. |
| 2026-10-14 | Save runs the dry run. If any row gives `#ERROR`, the user confirms before saving. |
| 2026-10-14 | Icons are inline WPF path geometry, filled with the theme's Ink brush, so they follow dark mode. |
| 2026-10-14 | Row numbers are a formatting option, not a field. They number visible data rows 1 to N, recalculated on every build. Excel uses a hidden helper column with `SUBTOTAL(109, …)`, because a self-referencing range is circular. Restart per block moved to later. |
| 2026-10-14 | Phase 9 (saved settings) stays in v1. Settings file: `%APPDATA%\pyRevit\Abaco\tables.json` in v1, `%APPDATA%\Abaco\tables.json` from v2. Same format, `"v": 1`. |
| 2026-10-14 | Roadmap: v1 is the MVP (pyRevit). v2 is a standalone add-in with a native dockable pane and property panels, decided after MVP feedback and a prototype. v3 is a full C# port, only if needed. v4 adds Phases 8, 10 and 11. |
| 2026-10-14 | Phases 8, 10 and 11 (model parameters, notes sync, arrays and `len()`) moved to v4. Version 1 ships with calculated fields only. Notes / comments stays disabled in the editor until v4. |
| 2026-10-14 | The port is not a commitment. Native feel is the reason for v2 and does not by itself require porting the core. |
| 2026-10-14 | No pyRevit fallback in v2. Distribution is a signed installer with an Authenticode certificate. |

---

## 4. Open decisions

Ordered by when they must be settled.

**Before v1 release**
1. **Phase 9 missing fields:** keep a field that no longer exists in the project (current proposal), or drop it with a warning.

**Before v2 starts (see section 6.3)**
2. **Prototype result:** has the dockable pane prototype been built, and does the native feel solve the problem? Go or no-go for v2.
3. **Runtime for the hybrid:** is shipping a CPython runtime with the signed installer acceptable?
4. **Text measurement across engines:** how the C# side is checked to produce the same widths as `measure.py`.
5. **Support matrix:** ship v2 to Revit 2024 to 2027 at once, or start with 2025.
6. **Certificate:** which Authenticode certificate, from which CA, and who holds the signing key.
7. **Settings migration:** confirm a v1 `tables.json` is read unchanged by v2, and what happens to a file that fails the check.
8. **v1 maintenance after v2 starts:** freeze at a release tag and fix critical bugs only, or keep fixing the Python core.

**Before v4 starts (see Phases 8, 10 and 11)**
9. **Test project:** a copy with shared parameters and custom families.
10. **Project parameters:** the Revit call for a true non-shared project parameter is to be checked on the test copy before Phase 8 commits to it.
11. **Notes sync direction:** both ways with an explicit Sync action (proposed), or one way only.
12. **Notes sync snapshot:** stored in the table settings, or on a hidden sheet in the workbook.

---

## 5. Later versions

Superseded by section 6 for the roadmap. The items that were here are now in section 6.1 (versions) and section 6.5 (deferred).

---

## 6. Roadmap and v2 decisions

Last updated: 14 October 2026

This section records the roadmap as agreed. Decisions marked **settled** are agreed. Items marked **open** must be settled before v2 starts, because v2 cannot be planned without them.

### 6.1 Versions

| Version | Scope | Status |
|---|---|---|
| **v1 (MVP)** | pyRevit extension. Phases 0, 9, 12 and 13 finished, on top of Phases 1 to 7. | In progress. Treat as the MVP. |
| **v2** | Standalone Revit add-in on .NET Framework 4.8 with a native dockable pane and property panels. Hybrid: C# shell, Python core behind a JSON boundary. | Decide after MVP feedback. Open items in 6.3 must be settled first. |
| **v3** | Full C# port of the Python core, verified against the Python suite and golden fixtures. | Decide after v2 is in use. |
| **v4** | Custom model parameters (Phase 8), notes sync with Excel (Phase 10), arrays and `len()` (Phase 11), built on the standalone core. | Follows v2 or v3, depending on which core it is built on. |

### 6.2 Settled decisions

- **Port strategy.** The Python core is not ported until there is user evidence that the port is needed. The port is not a commitment in the plan.
- **Dockable pane.** The native feel (dockable pane, property panels) is the main reason for v2. It is a shell requirement and does not require porting the core.
- **Prototype first.** Before v2 is committed, build a small C# add-in with one dockable pane that hosts the existing `ui.xaml` with a fixed table, and drives it through `ExternalEvent`. Days of work. Its result decides whether v2 goes ahead as the hybrid.
- **No pyRevit fallback in v2.** The standalone add-in replaces pyRevit.
- **Distribution.** Signed installer with an Authenticode certificate. Without one, Windows SmartScreen warns on every install.
- **Settings file path.**
  - v1 (pyRevit): `%APPDATA%\pyRevit\Abaco\tables.json`
  - v2 onward (standalone): `%APPDATA%\Abaco\tables.json`
  - Same JSON format in both. The field `"v": 1` allows migration on first run. The path must not include the Revit year, because the settings would be lost on upgrade.
  - `C:\ProgramData\Autodesk\Revit\Addins\<year>` holds only the add-in manifests, not user data. It is not used for settings.
- **Hybrid boundary (if v2 is hybrid).** One function, JSON in, JSON out, with no Revit objects crossing it. Kept narrow, so it can be removed cleanly in v3.
- **Golden fixtures (if v3 happens).** Settings JSON in and expected table JSON out, generated from Python and checked in C#. A mismatch fails the build.

### 6.3 Open items for v2

These must be settled before v2 starts. Each one changes how v2 is built.

1. **Prototype result.** Has the dockable pane prototype (6.2) been built, and does the native feel solve the problem? Go or no-go for v2.
2. **Runtime for the hybrid.** Is shipping a CPython runtime with the signed installer acceptable to you and to your users or IT team? If not, v2 becomes a full port, and the plan changes to v2 = port.
3. **Text measurement across engines.** `measure.py` uses `System.Drawing` through IronPython. In the hybrid, the C# side must produce the same widths, or the drawing and the preview wrap differently. Decide how this is checked before the boundary is designed.
4. **Support matrix.** Revit 2024 to 2027 each need a build and a test run. Decide whether v2 ships to all four at once, or starts with 2025 and adds the others.
5. **Certificate.** Which Authenticode certificate, from which CA, and who holds the signing key.
6. **Settings migration.** Confirm that a v1 `tables.json` is read unchanged by v2, and decide what happens to a file that fails the check.
7. **v1 maintenance after v2 starts.** Freeze at a release tag and fix critical bugs only, or keep fixing the Python core. This decides whether bug fixes are written twice.

### 6.4 Risks

- **Port drift.** If v2 and v3 both produce tables, they must match. Golden fixtures are the check.
- **Formula edge rules.** NONE, VARIES, the shortest `STRING` form and `INT` rounding are the most likely source of drift. Port and test these first.
- **Python runtime in a signed installer.** It adds size, signing scope and support work. Measure it on the prototype.
- **Scope creep before v2.** Adding features to v1 while the shell is undecided makes the later port larger. Keep v1 to the MVP list in 6.1.

### 6.5 Deferred

These items are not scheduled. They move to a later version or stay deferred, unless user feedback brings them forward.

- Per-element typing of custom model parameter values in the preview.
- Drag and drop reordering of fields and levels.
- Direct `.xlsx` writer, if Excel COM proves unreliable. Also the answer for machines without Excel.
- Shared presets across a team.
- Revit text colour per cell, through filled-region labels.
- Formula chains `IF(c): v; ELIF (c): v; ELSE: v;` and blocks.
- `ROUND(x, n)`, `STRING(x, n)` with a fixed decimal count, and trigonometric functions.
- Formula units `°`, `rad`, `K`, `kg`, `N`, `J`, `W`.
- Restart row numbers at each block of a chosen level (formatting option on the row number column).