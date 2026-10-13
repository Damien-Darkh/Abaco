# Abaco Tables: Development Plan

Last updated: 13 October 2026

- **Target:** Revit 2024, 2025, 2026 and 2027, with pyRevit 6.5 or newer on every machine.
- **Status:** the extension runs in Revit 2025 test sessions. It reads the model, builds the table, writes the Excel tab, and creates drafting views and sheets. The Settings, Fields, Filter, Sort & group, Formatting and Appearance tabs are built. Custom fields are designed but not built.
- **UI reference:** the approved mockup, since changed in several places. The Preview tab as built is the reference.

---

## 0. Overview

### 0.1 Folder layout

```
Abaco.extension/
  lib/abaco/
    records.py          model data, neutral (no Revit)
    revit_reader.py     the only module that reads the Revit API
    pipeline.py         settings -> table (no Revit)
    layout.py           table -> drawing geometry, paged (no Revit)
    measure.py          text measurement for the layout (System.Drawing)
    drafting.py         draws views and sheets (Revit)
    sheet.py            table -> Excel sheet model (no Excel)
    excel_writer.py     Excel COM writer
    runner.py           glue: records + settings -> results, drawing, Excel
    preview.py          As Excel grid and As Revit canvas
    appearance.py       presets, styles, case, alignment (no Revit)
    ui_state.py         window state and row items (no WPF on CPython)
    filters.py          filter conditions (no Revit)
    filter_ui.py        Filter tab controller
    color_picker.py     PixiEditor colour picker, with hex fallback
    ui_theme.py         light and dark copy of ui.xaml, following Revit 2025
    ColorPicker.dll, ColorPicker.Models.dll
    formula.py          formula tokenizer, parser, unit and type checker (no Revit)
    evaluate.py         formula evaluator, per row (no Revit)
    icons/              SVG source files (reference only; icons are inline in ui.xaml)
  Abaco.tab/Tables.panel/AbacoTables.pushbutton/
    script.py           window code
    ui.xaml             window
  Abaco.tab/Tables.panel/AbacoTest.pushbutton/
  Abaco.tab/Tables.panel/Phase3Check.pushbutton/   temporary, delete after Phase 13
  tests/                records, pipeline, outputs, ui, filters, measure, formula, evaluate; formula and evaluate done, others to update (Phase 13)
```

`table_builder.py` is retired. Delete it once Phase 0 passes.

### 0.2 Guiding rules

1. **One source of truth.** The preview, the Revit drawing and the Excel file all read the same pipeline output. What you see is what is written.
2. **Pure Python wherever possible.** Pipeline, layout, formula and evaluator have no Revit dependency, so they are tested outside Revit.
3. **Read the model deliberately.** Changing a setting recomputes in memory. The model is read again only by Re-read model, or when the category or table type changes. The one exception is the formula dry run, which loads only the fields a formula refers to (see Phase 5).
4. **Common-subset Python.** Code must run on IronPython 2.7 (pyRevit default engine) and CPython 3. No f-strings. Use `u""` literals.
5. **Revit-version-safe API use.** `ElementId.Value`, `ForgeTypeId` units, `SpecTypeId`. Never `IntegerValue`, `UnitType`, `ParameterType`.
6. **Honest limits.** Anything Revit cannot draw is said so in the UI and in this plan, and Excel carries it instead.

---

## 1. Phase summary

| Phase | Name | Status | Depends on |
|---|---|---|---|
| 0 | Baseline: runs on every target Revit version | In progress | none |
| 1 | Data layer: flat records | Done | 0 |
| 2 | Pipeline: settings to table | Done | 1 |
| 3 | Output layers: Revit drawing and Excel writer | Done (known Revit limits) | 2 |
| 4 | Window: Settings, Preview, Appearance, theme | Done, with icon column pending | 2, 3 |
| 5 | Formula language and evaluator | Done for version 1 (Revit test pending) | 2 |
| 6 | Custom fields in the table: catalogue, pipeline, calculated fields | Planned | 4, 5 |
| 7 | Custom field editor and icon column | Planned | 4, 6 |
| 8 | Custom model parameters (Revit) | Planned | 7 |
| 9 | Saved settings, per category | Planned | 4, 6, 7, 8 |
| 10 | Notes and comments sync with Excel | Planned | 8, 9 |
| 11 | Arrays and `len()` in formulas | Planned | 5, 6 |
| 12 | Row index field | Planned | 2, 11 |
| 13 | Testing and release | Planned | all |

Phases 5 to 8 are the custom field work. Phase 7 comes before Phase 8, so the editor can be tested before any model parameter is written.

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
- Confirm Excel COM works on each version. Decision gate: if Excel COM fails on a newer version, the direct `.xlsx` writer moves from v2 into the plan.
- Attach pyRevit as CurrentUser for Revit 2027 (all-users manifests are rejected for unsigned add-ins).
- Delete `table_builder.py`.

**Done when:** Revit 2024 and 2027 pass the checklist with no unhandled errors.

### Phase 1: Data layer

**Goal:** read the model once into records that hold every value the pipeline may need.

**Done**
- `records.py`: element, type and layer data; field catalogue with scope and kind; display labels that keep twin parameters apart.
- `revit_reader.py`: reads core values, scans the catalogue, loads values on demand and caches them.
- `test_records.py`: 9 tests pass.

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
- `test_pipeline.py` rewritten for the level list, curtain walls as a filter, and collapsed gap rows (26 tests)


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
- **Colour picker:** PixiEditor ColorPicker is wired in, with the hex prompt as a fallback. It needs `ColorPicker.dll` and `ColorPicker.Models.dll` in `lib/abaco/`.

**To do**
- Verify the colour picker opens and returns a colour in Revit 2025 (the fallback is what runs until then).
- Icon column in Add parameter (Add, Custom field, Edit, Delete), with the SVG icons inline in `ui.xaml`. The custom field icon waits for the sigma SVG to be placed.
- Two-column Add parameter area, with the list as a `ListBox` so it has a selection.
- Remove the Max auto width remnants if any remain.

**Done when:** every tab behaves as described, and Run output matches the As Excel and As Revit previews.

### Phase 5: Formula language and evaluator

**Goal:** a formula can be written, checked and evaluated, with no Revit and no UI.

**Status:** done for version 1. The full specification is `phase5.md`. `test_formula.py` (29 tests) and `test_evaluate.py` (24 tests) pass with `python3`. Not yet run under IronPython 2.7: that happens in the Revit test (Phase 13).

**Version 1 scope**
- **Grammar:** one expression. No chains, no blocks, no arrays. Chains `IF(c): v; ELIF (c): v; ELSE: v;` and blocks are version 2.
- **Fields:** written `{Label}` in the editor, stored as `{key}`. `[ ]` is kept for arrays (Phase 11).
- **Operators:** comparison `= != < > <= >=` (no chaining); logic `AND`, `OR` (booleans only, short-circuit); arithmetic `+ - * / %` and `^` (right-associative, whole-number literal exponent when the value has a unit); unary minus; grouping `( )`. `+` also joins two texts. `|x|` is dropped: use `ABS(x)`.
- **Functions:** `IF(c, a, b)` (lazy, both branches one type and unit), `MIN`, `MAX`, `SQRT`, `ROOT(x, n)`, `ABS`, `INT` (rounds half away from zero; a text gives its length), `FLOAT`, `STRING` (a literal keeps its typed text, other numbers use the shortest plain form), `SENSITIVE` (case-sensitive text comparison, on one side of `=` or `!=`). `LEN` is reserved and says "not available until version 2". `ROUND(x, n)` comes in version 2 or 3.
- **Keywords:** case-insensitive, shown in capitals everywhere. Reserved: `AND OR IF ELIF ELSE TRUE FALSE SENSITIVE MIN MAX SQRT ROOT ABS INT FLOAT STRING LEN`.
- **Units:** the exponent of `m` is tracked (`m` 1, `m²` 2, `m³` 3). `*` and `/` add and subtract exponents. `+`, `-`, `%` and comparisons need equal exponents; a literal `0` fits any unit. Suffixes `m`, `m²`, `m³` follow a number or a count (`{Count} m` is a length). A count plus a plain number stays a count. `MIN` and `MAX` with different units are refused at save time.
- **Booleans:** `TRUE` and `FALSE` in any letter case. Yes/No fields are booleans in formulas. A boolean result shows as `#TRUE` or `#FALSE`.
- **Empty and errors:** an empty value is `NONE`, shown `#NONE`. Arithmetic, functions and comparisons with NONE give NONE. `FALSE AND x` is FALSE and `TRUE OR x` is TRUE whatever `x` is. An error wins over NONE. Division or remainder by zero and an even root of a negative are `#ERROR` (reasons `div0`, `sqrt_neg`). Other run-time reasons: `ref` (row has no such field), `type` (a row value of the wrong type), `range` (result not a finite number).
- **Numbers:** `=` and `!=` use a tolerance of 1e-6, as filters do. Formulas run on full-precision values, not the rounded display values. `%` follows Python.
- **Save-time checks, which refuse the save:** syntax with position; unknown field with the nearest match; circular reference with the full loop; unit mismatch; type mismatch; `AND` or `OR` on a non-boolean; literal division or remainder by zero; `SQRT` or even `ROOT` of a negative literal; a key containing `}`. Each error carries a position, a reason code (`syntax`, `unit`, `type`, `ref`, `div0`, `sqrt_neg`) and a suggested fix.
- **Save-time dry run, which saves with a warning:** the formula is evaluated for every row. Failures are counted per reason, with up to three examples. Failing rows show `#ERROR`.
- **Dry-run loading:** the dry run loads only the fields the formula refers to, the first time they are needed, and caches them until Re-read model.

**Deliverables (done):** `formula.py`, `evaluate.py`, `test_formula.py`, `test_evaluate.py`, all runnable with `python3`.

**Still to verify in Revit (Phase 13):** both files under IronPython 2.7; `repr()` of a float gives the shortest round-trip text there, which `STRING` relies on.

**Done when (met for version 1):** the suites cover precedence, nesting, every save-time check, every run-time `#ERROR` case, and the dry run on sample rows.

### Phase 6: Custom fields in the table

**Goal:** calculated fields work in the table like any other field.

Status (13 October 2026): catalogue, storage, pipeline stage and UI hooks are done. Custom fields appear in Add parameter, survive Reset, Re-read model and table type changes, and enable Edit and Delete on their rows. Tests: test_custom.py (21), test_ui.py (14). Still open: decimals from project settings (Open decision 5), a Revit test of filters on calculated fields, and Edit and Delete handlers (Phase 7).

**Scope**
- Custom fields enter the catalogue with type and scope, and are marked as custom. The result type comes from the checked formula.
- **Evaluation is per row, after grouping.** A formula sees the row's cell values: a group's `Count`, the summed `Area` and `Total Length`, shared values. So `{Area} / {Count}` is the average area per element and `{Area} * 2` doubles the group's summed area. `evaluate.calculate_row()` runs the fields in `topological_order()`; a circular reference is refused with the loop shown.
- **Live behaviour:** calculated fields are recomputed every time the table is rebuilt: filter, group, sort, formatting or field changes. A row carries every field its formulas use, including fields hidden in Revit or not included in the table. Nothing recomputes when the window is closed.
- **Sort, group, footers, summary:** the calculated value is a row value, so it can be sorted on and can start a new block when it changes. It cannot split a row (it exists only after the rows are built). Footers and the summary skip `#NONE`, `#ERROR`, `#TRUE` and `#FALSE`, as they skip `Varies`. The pipeline shows `evaluate.to_cell()` and formats numbers with the column decimals.
- **Filter:** conditions on model fields run on elements before grouping, as in Phase 4. Conditions on calculated fields run after grouping, on row values (to confirm, see Open decisions 4).
- **Removal:** a field removed from the table with × returns to Add parameter. Formulas that use it show `#ERROR` (reason `ref`), and the removal warning lists them.
- **Names:** custom field names are checked against existing labels when created or edited.

**Done when:** a calculated field works through filter, group, sort, footer, summary and Excel, and a removal shows the warning and `#ERROR`.

### Phase 7: Custom field editor and icon column

**Goal:** create, edit and delete custom fields from the window.

**Status:** the editor window (XAML) is designed and accepted. The code-behind (save checks, first failing row, editor capitalisation, field and key insertion) is not written.

**Scope**
- **Icon column** in Add parameter, with four icons (SVG, 16 × 16, colours from the SVG):
  - **Add:** adds the selected parameter to the table.
  - **Custom field:** opens the editor.
  - **Edit:** edits the selected custom field: name and formula. Greyed out for model parameters.
  - **Delete:** deletes the selected custom field from the table, the parameter list, the catalogue and every saved reference (sort levels, filter conditions, formatting), after a confirmation. Greyed out for model parameters.
- **Greyed out** means opacity 0.35 on the icon. Colours do not change.
- **The × in the table list** returns a field to Add parameter. It does not delete it.
- **Editor, Field card:** name (unique in the table) and kind: **Calculated** or **Notes / comments**. Notes / comments is shown but disabled until Phase 8, because it is a text model parameter. Choosing Notes hides the formula, keys, fields and example cards.
- **Result unit** is derived from the checked formula and shown read-only. **Decimal places** are always automatic (see Open decisions 5). There is no unit or decimals control.
- **Formula box:** a single line (no Enter). Keywords and function names are converted to capitals on the keystroke after the word is complete (`True` becomes `TRUE` when the next key is a separator). A word that continues into a longer name (`True_key`) is left alone. Nothing is converted inside `{ }` or `" "`, and units (`m`, `m²`, `m³`) are never converted. `formula.to_caps()` does the transform.
- **Status and preview:** the status line shows the check result (valid, or the first error with its fix). The "Where it fails" box appears only when the formula or a row has an error, with the first failing row and its reason, from `evaluate.dry_run()`.
- **Virtual keyboard:** a fixed two-column grid that does not scroll. Left: arithmetic and `%`, brackets, `,`, `=` and `^`, comparisons, then `SQRT` and `ROOT`. Right: `AND OR TRUE FALSE`; units `m m² m³` (always active, the checker explains misuse); `IF MIN MAX ABS`; `INT FLOAT STRING SENSITIVE`. Keys insert capitals. Each button has a tooltip with its use and an example, using full labels and units, for example `{Height (m)} > 3 m`.
- **Field picker:** lists the table fields only. Double-click or Insert field puts `{Label}` at the cursor as one item. The saved formula stores keys (`formula.to_stored()`), the editor shows labels (`formula.to_editor()`).
- **Example:** built by code from the table's own fields, with the units the checker needs.
- **Save:** runs the Phase 5 checks, refuses to save on a save-time error, saves with a warning on row errors, and adds the new field to the table fields.

**Done when:** a calculated field can be created, edited, removed from the table, and deleted, with the confirmation and clean-up described above.

### Phase 8: Custom model parameters (Revit)

**Goal:** create project parameters in the model and fill them from the table.

**Scope**
- **Kinds:** instance or type. Chosen at creation.
- **Shared or project:** a shared parameter is used only from the project's existing parameter file. If the project has none, the shared option is greyed out and project parameters are created. No file is ever created.
- **Categories:** created for every category chosen at creation. The assignment can be edited later.
- **Values:** filled from a formula or a constant, in a transaction, after a confirmation.
- **Delete:** removes the parameter from the extension and the model, after a confirmation that states it cannot be undone in Revit.
- **Name clashes:** checked against existing parameters in the project.

**Test project:** a copy of a real project with shared parameters, custom families and the categories in use.

**Done when:** a parameter created on the copy is readable by Abaco, filled from a formula, and removed cleanly.

### Phase 9: Saved settings, per category

**Goal:** the table arrangement survives between sessions.

**Scope**
- One saved object per category and mode (standard or curtain).
- Stored as JSON next to the user's pyRevit config, not in the Revit project.
- Versioned with `"v": 1`. Unknown fields are ignored. Missing fields take template defaults.
- Saved: fields, levels, filter, formatting, appearance, the Revit and Excel options, and custom fields with their formulas.
- A custom model parameter is referenced by its GUID and category list. If it no longer exists in the project, the field is kept and flagged "not found".
- A formula that refers to a missing field is kept and shows `#ERROR` until the field is restored.
- Reset restores template defaults for the current selection.
- A corrupt or old-version file falls back to defaults without an error.

**Done when:** closing and reopening restores each category's arrangement, and a corrupt file falls back cleanly.

### Phase 10: Notes and comments sync with Excel

**Goal:** a notes or comments column in the Excel tab stays in step with the matching model parameter.

**Scope**
- **Source:** a text custom model parameter from Phase 8, instance kind, one value per element.
- **Element identity:** the key is the element's IfcGUID, which the reader already loads. Element Id is not stable across models and copies, so it is only a fallback.
- **Direction (open):** Excel to model, model to Excel, or both. Proposed: both, with an explicit Sync action. No automatic writes.
- **Conflicts:** if a value changed on both sides since the last sync, both values are shown, and the user chooses. Nothing is overwritten silently.
- **Last-synced snapshot (open):** stored in the table settings, or on a hidden sheet in the workbook. It is what makes a change detectable.
- **Writing to the model:** in a transaction, after a confirmation that states how many elements change.
- **Excel side:** the notes column is found by its heading. Rows are matched by IfcGUID, and rows that no longer exist are reported, not deleted.

**Done when:** a round trip (edit in Excel, sync to the model, change in the model, sync back) works on the test project, and a conflict is shown rather than overwritten.

### Phase 11: Arrays and `len()` in formulas

**Goal:** arrays and `len()` in formulas, after the custom field features are working.

**Scope**
- **Syntax:** array literals `[a, b, c]`, where each item is an expression, including field references. `len(x)` takes an array or a text.
- **Type checker:** an array has an element type. `len` returns a number. Items of one array must share a type when the types are known.
- **Save-time checks:** mixed item types in one array are refused when known. `len` of a number is refused. An empty array literal `[]` is refused, since it has no type.
- **Run time:** an element whose array items differ in type shows `#ERROR` for that element.
- **Arithmetic on arrays** (element-by-element) is out of scope unless decided later.
- **Keyboard:** `[ ]` and `LEN(` are added, with tooltips. `LEN` is already reserved in version 1 and reports "not available until version 2".

**Depends on:** the grammar and checker in Phase 5, and the evaluator in Phase 6.

**Done when:** tests cover array literals, `len` on arrays and text, mixed-type arrays refused at save, and the dry run on sample records.

### Phase 12: Row index field

**Goal:** a built-in field that numbers the table's rows from 1.

**Scope**
- Added from Add parameter like any other field, and works in Revit and Excel.
- Numbers the data rows from 1 with no gaps. Header, footer, summary and blank rows get no number.
- Numbered after sorting and grouping, so the numbers follow the order the table shows.
- Itemized tables number each element's row.
- Excel stores the numbers as values, so re-sorting the sheet by hand does not renumber them. A live formula is an option (open).

**Open**
- Restart at 1 in each block, or run through the whole table? Currently written as continuous.

**Depends on:** the pipeline in Phase 2, and the built-in field work in Phase 11.

**Done when:** the numbers run from 1 with no gaps across blocks, headers and footers, in both outputs.

### Phase 13: Testing and release

**Goal:** a reliable install and a checklist that catches regressions.

**Automated (no Revit)**
- Update `test_pipeline.py`, `test_outputs.py` and `test_ui.py` to the current structure.
- Add tests for appearance, filters and measurement. Formula and evaluator tests exist; run them under IronPython 2.7 in the AbacoTest button, including `STRING` of a float.
- Run every test file with `python3` on each change.
- All nine test files pass under `tests/run_all.py` (custom 21, evaluate 26, filters 15, formula 29, formula integration 2, outputs 15, pipeline 26, records 9, ui 14). Run with `python3 tests/run_all.py` after every change.

**Manual checklist (Revit 2024 and 2027; spot-check 2025 and 2026)**
1. The extension loads, and the ribbon button is present.
2. Walls: standard and curtain modes build. The preview matches the drawing.
3. Add a shared parameter. Reorder. Hide in Revit. Switch off in Excel.
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
14. Index: numbers run from 1 with no gaps across blocks, headers and footers, in both outputs.

**Release**
- Version in `bundle.yaml`, and a changelog.
- Install notes: pyRevit 6.5 or newer, CurrentUser attach for Revit 2027, desktop Excel for the COM writer, and the two ColorPicker DLLs in `lib/abaco/`.
- Zip of the extension folder.

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
| 2026-10-09 | Custom field kinds: calculated and custom model parameter. Notes are a text custom model parameter. Constant text is removed. |
| 2026-10-09 | Formula syntax: each value ends with `;`, a block ends with `};`, `else` is required. |
| 2026-10-09 | Literal errors refuse the save. Element errors save with a warning and `#ERROR`. |
| 2026-10-09 | Recalculation is live from loaded values. Model re-read only on Re-read model, or a category or table type change. |
| 2026-10-09 | Dry run loads only the fields a formula refers to, once, until Re-read model. |
| 2026-10-09 | × in the table moves a field back to Add parameter. Delete removes a custom field everywhere, after confirmation. |
| 2026-10-09 | Shared parameters: an existing file is used, and none is created. |
| 2026-10-09 | Build order: editor (Phase 7) before model parameters (Phase 8). |
| 2026-10-09 | Notes sync with Excel is Phase 10, after model parameters and saved settings. |
| 2026-10-09 | Moved to v2: per-element typing in the preview, drag and drop reordering, direct `.xlsx` writer, shared presets, Revit per-cell text colour. |
| 2026-10-09 | Arrays `[ ]` and `len()` are Phase 11, after the custom field features and before testing. |
| 2026-10-09 | Row index field is Phase 12, one of the last phases: row number from 1, data rows only, numbered after sort and grouping. |
| 2026-10-13 | Phase 5 formulas: one expression in version 1, `IF(c, a, b)`. Chains and blocks are version 2. |
| 2026-10-13 | Fields are `{Label}` in the editor and `{key}` stored. Arrays are `[ ]`, version 2. |
| 2026-10-13 | The absolute-value bars are dropped for `ABS(x)`. Reserved: AND OR IF ELIF ELSE TRUE FALSE SENSITIVE MIN MAX SQRT ROOT ABS INT FLOAT STRING LEN. |
| 2026-10-13 | Keywords and function names are case-insensitive, shown in capitals; the editor converts on the keystroke after a complete word, never inside `{ }` or `" "`. |
| 2026-10-13 | Yes/No fields are booleans in formulas. Boolean results show `#TRUE` and `#FALSE`. Empty is `#NONE`. An error wins over NONE. |
| 2026-10-13 | Units: the exponent of `m` is tracked; suffixes `m`, `m²`, `m³` in version 1; a literal `0` fits any unit; count is dimensionless in products. Version 2 units: `°`, `rad`, `K`, `kg`, `N`, `J`, `W` (`°C`, `g`, `mg` dropped). |
| 2026-10-13 | Calculated fields are evaluated per row after grouping and recomputed on every table rebuild. |
| 2026-10-13 | Division by zero is `#ERROR`. `INT` rounds half away from zero; `ROUND(x, n)` comes later. `STRING` keeps a literal's typed text. |
| 2026-10-13 | Editor: result unit derived and read-only; decimals automatic; the failing-row preview shows only on an error; kind is Calculated or Notes / comments (Notes disabled until Phase 8); keyboard is a two-column grid without scrolling. |
| 2026-10-13 | Units and decimals: the project default comes from Revit’s Project Units (Manage tab) for each dimension. The Formatting tab can override the unit and the decimal places per field. Decimal places: 0 to 4 (1234, 1234.0, 1234.00, 1234.000, 1234.0000). Units by dimension: length (mm, cm, m, Km), area (mm2, cm2, m2, Km2), volume (mm3, cm3, m3, Km3), angle (rad, °, ‘, ‘’), currency ($, €, ¥ JPY, £, ¥ CNY). Fields with no dimension (counts, ratios, yes/no, text) have no unit drop-down. Stored values stay in base units (m, m², m³, radians); conversion happens only at output, after sorting, grouping, footers and formulas.

---

## 4. Open decisions

1. **Excel notes sync direction:** both ways with an explicit Sync action (proposed), or one way only?
2. **Last-synced snapshot:** in the table settings, or on a hidden sheet in the workbook?
3. **Test project:** a copy with shared parameters and custom families is available for Phase 8 and Phase 10?
4. **Filters on calculated fields:** run after grouping, on row values (proposed), while model-field filters stay before grouping? A filter that mixes both applies the element filter first, then the row filter.
5. **`Varies` as a formula input:** a grouped row can hold the word `Varies` (or a `min - max` text) in an element field. Applied in code as proposed: the pipeline hands it to the formula as NONE, so the result is `#NONE`. Confirm.
6. **`NONE AND FALSE`:** applied in code as proposed: a deciding value (FALSE for AND, TRUE for OR) wins on either side, even against NONE, so `NONE AND FALSE` is FALSE. An error is never hidden by it. Confirm.

---

## 5. v2

Planned for v2, after version 1 is released. Arrays and `len()` are not here: they are Phase 11 in version 1.

- Per-element typing of custom model parameter values in the preview.
- Drag and drop reordering of fields and levels.
- A direct `.xlsx` writer, if Excel COM proves unreliable. This is also the answer for machines without Excel.
- Shared presets across a team.
- Revit text colour per cell, through filled-region labels, if a use case needs it.
- Formula chains `IF(c): v; ELIF (c): v; ELSE: v;` and blocks `{ ... };`.
- `ROUND(x, n)`, `STRING(x, n)` with a fixed decimal count, and trigonometric functions.
- Formula units `°`, `rad`, `K`, `kg`, `N`, `J`, `W`, with a dimension vector and scale factors.
