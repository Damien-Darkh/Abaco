# Abaco Tables: Development Plan

Port of the Dynamo graph `Abaco_Murature_Sync.dyn` to a pyRevit extension with a WPF (XAML) window, extended with
Revit-style **Fields**, **Sorting / Grouping** and **Formatting** controls.

- **Target:** Revit 2024, 2025, 2026, 2027 (pyRevit 6.4 or newer on every machine)
- **UI reference:** https://claude.ai/artifact/CMbnrBCQTZ2BVij1syXvvH (approved mockup, Preview tab)
- **Status:** v1 (Dynamo port) is written but **not yet run in Revit**. Everything below builds on it.

---

## 0. Overview

### 0.1 Where we are

```
Abaco.extension/
  lib/abaco/
    table_builder.py   model -> finished table (fixed columns, fixed sort)      [v1, untested in Revit]
    layout.py          rows -> lines/text + pages (pure Python, smoke-tested)   [v1]
    drafting.py        draws drafting views + sheets                            [v1, untested in Revit]
    excel_writer.py    Excel COM writer                                         [v1, untested in Revit]
  Abaco.tab/Tables.panel/AbacoTables.pushbutton/
    script.py          window code
    ui.xaml            window (Settings + Preview tabs)
```

### 0.2 Where we are going

The table builder stops returning a finished table. It returns **flat records**, and a **pipeline** turns records into
two outputs (one for Excel, one for Revit) according to user settings. The window edits those settings and shows a
live preview without rescanning the model.

```
Revit model
   |  (read once)
   v
[Phase 1] Records  ----------------------------------------------+
   |                                                             |
   v                                                             |
[Phase 2] Pipeline: fields -> itemize/group -> Varies -> sort -> calculations -> formatting
   |                          |
   v                          v
 Excel table             Revit table  (hidden fields removed, widths, alignment)
   |                          |
   v                          v
[Phase 3] excel_writer     drafting (+ layout)
   ^                          ^
   +------ [Phase 4] XAML window: tabs + live preview (same pipeline output) ------+
                              |
                    [Phase 5] settings saved per category
```

### 0.3 Guiding rules

1. **One source of truth.** The preview, the Revit drawing and the Excel file all read the same pipeline output. What
   you see is what is written.
2. **Pure Python wherever possible.** Pipeline and layout have no Revit dependency, so they can be unit-tested outside
   Revit with mock data.
3. **Read the model once.** Changing a setting re-runs the pipeline in memory. Only "Re-read model" rescans.
4. **Common-subset Python.** Code must run on IronPython 2.7 (pyRevit default engine), IronPython 3.4 and CPython 3.
   No f-strings, `unicode` handled via `u""` literals, no `print` statements, no `basestring` without a fallback.
5. **Revit-version-safe API use.** Only APIs available in 2024 to 2027 (for example `ElementId.Value`, ForgeTypeId units).
   Never `IntegerValue`, `UnitType`, `ParameterType`.

---

## Phase 0: Baseline: make v1 run on all four Revit versions

**Goal:** a verified starting point before anything is stacked on it.

**Why first:** v1 has never run in Revit. Building new features on unverified code multiplies debugging.

### Work

| # | Task | Detail |
|---|------|--------|
| 0.1 | Environment check | Every machine on pyRevit 6.4+. On Revit 2027, pyRevit must be attached as **CurrentUser** (all-users manifests are rejected for unsigned add-ins). |
| 0.2 | Add `bundle.yaml` | Move button title and tooltip out of inline `__title__` / `__doc__` into `bundle.yaml`, because pyRevit is progressively removing inline metadata parsing. |
| 0.3 | Smoke test on **Revit 2024** | Load, open window, category list populates, Preview works, Run creates view + sheet, Excel writes. |
| 0.4 | Smoke test on **Revit 2027** | Same checklist. If 2024 and 2027 pass, 2025 and 2026 are expected to pass. |
| 0.5 | Fix findings | Collect error text from the window log and pyRevit output; patch v1. |

### Known risks to watch in this phase

- **Excel COM late binding** across the runtime changes (Revit 2025 and again 2027). Untested everywhere.
- `Activator.CreateInstance.Overloads[Type]` on IronPython 3.4 / CPython.
- XAML event binding (`Click="..."`) under each engine.
- `DataGridTextColumn` + `Binding("[0]")` on `List[object]` rows.

### Decision gate

If Excel COM fails on a newer version, add a **fallback writer** that creates the `.xlsx` directly (zip + XML, no Excel
needed). Cost: preserving other tabs in an existing workbook is harder. Decide after the test result.

### Done when

- Both 2024 and 2027 complete the checklist (see section 6) with no unhandled errors.
- `bundle.yaml` in place.

---

## Phase 1: Data layer: flat records

**Goal:** read the model once into a neutral structure that holds *every* value the pipeline might need.

**Replaces:** the grouping + row-building logic inside `table_builder.build_table`.

### 1.1 Record model

Three levels of data per record, matching how the table is built today:

| Level | Examples | Notes |
|-------|----------|-------|
| **Element** | Element Id, Comments, Mark, instance parameters, Level / Base Constraint | One per Revit element. Needed for *Itemize every instance* and *Varies*. |
| **Type** | Type Mark, Type Name, Family, Fire Rating, Assembly Code, Keynote, Manufacturer, shared type parameters | One per element type. |
| **Layer** | Order, Material, Thickness, Function, Material Area | Only for compound-structure types (walls, floors, roofs, ceilings). |

Each element record stores: its type key, its element values, and (for layered types) its per-material areas.
Type values and layer lists are stored once per type, not repeated per element.

### 1.2 Field catalogue

A *field* is anything that can become a column. Each field has:

| Property | Meaning |
|----------|---------|
| `key` | Stable identifier. Built-in parameters use the `BuiltInParameter` name; shared parameters use the GUID; project parameters use the parameter `ElementId`. **Never the display name** (display names are localised: an Italian Revit shows different names). |
| `label` | Default heading (localised display name). |
| `scope` | `element`, `type` or `layer`. |
| `kind` | `text`, `number`, `integer`, `yesno`, `length`, `area`, `elementid`. |
| `unit` | For length/area: target unit (metres, square metres). |

The catalogue is built by scanning parameters on the selected category's elements and types (the "214 available" count
in the mockup). Built-in fields from v1 (Type Mark, Wall Type Name, Order, Material, Thickness, Function, Material Area,
Base Constraint, Count, Length, Height, Width, Family) are always present.

### 1.3 Unit and value conversion

- Lengths and areas are converted with `UnitUtils.ConvertFromInternalUnits` and `UnitTypeId` (ForgeTypeId API only).
- Numbers keep full precision in the record. **Rounding is a formatting concern (Phase 2), not a data concern.**
- `YesNo` becomes `Yes` / `No`; `ElementId` parameters resolve to the element's name; missing values are `None`.
- Existing v1 conversions (feet to metres, sq ft to sq m) are kept so results match the Dynamo graph.

### 1.4 Table shapes

The three v1 shapes remain as **templates** that define the default field set and default sort:

| Template | Applies to | Default fields |
|----------|-----------|----------------|
| Layered | Types with compound structure | Type Mark, Wall Type Name, Order, Material, Thickness, Function, Material Area, Base Constraint |
| Curtain wall | Walls where `Kind == Curtain` | Type Mark, Wall Type Name, Count, Total Length, Height, Area, Base Constraint |
| Simple | Doors, windows, other families | Type Mark, Family, Type Name, Width, Height, Count, Level |

### 1.5 Edge cases to handle explicitly

- Stacked walls (no compound structure): one row, material shown as `(no layers)`.
- Layers with no material: `None / Air`.
- Elements without a level: empty level, still grouped.
- Same parameter name existing as both type and instance parameter: distinct `key`, shown with a scope tag.
- Linked-model elements: excluded (as in v1).

### 1.6 Deliverables

- `lib/abaco/records.py`: record classes (pure Python, no Revit imports).
- `lib/abaco/revit_reader.py`: reads Revit into records and builds the field catalogue (the only module touching the API).
- `table_builder.py` retired (its logic moves into reader + pipeline).

### Done when

- Reader returns records for walls, curtain walls, floors, doors in a test project.
- Record counts and areas match the v1 output for the same project.
- Field catalogue lists built-in and shared parameters with correct kinds.

---

## Phase 2: Pipeline (pure Python, unit-tested here)

**Goal:** turn records plus settings into the final table(s). This is where the Fields, Sorting and Formatting tabs
get their behaviour.

### 2.1 Settings model

One serialisable structure (also what Phase 5 saves):

```json
{
  "category": "OST_Walls",
  "mode": "standard",
  "title": "Abaco Muratura",
  "fields": [
    { "key": "ALL_MODEL_TYPE_MARK", "include": true, "heading": "Type Mark",
      "align": "center", "orientation": "horizontal", "widthMm": null,
      "hiddenInRevit": false, "showInExcel": true, "calc": "none" }
  ],
  "sort": [ { "key": "WALL_BASE_CONSTRAINT", "dir": "asc", "gap": true } ],
  "itemize": false,
  "grandTotals": false,
  "revit": { "textMm": 2.5, "pageHeightMm": 490, "prefix": "AM" }
}
```

### 2.2 Pipeline stages

Executed in this order. Each stage is a pure function, tested on its own.

| Stage | Input | Output | Behaviour |
|-------|-------|--------|-----------|
| 1. Field selection | records, settings.fields | ordered column list | Included fields only, in the Fields-tab order. |
| 2. Row building | records | rows | **Grouped** (default): one row per type + level (+ size, as in v1). **Itemized**: one row per element, with an Element Id column added. Layered types expand each row into layer rows. |
| 3. Varies | grouped rows | rows with merged values | For each *element-scope* column in a group: if all elements agree, show the value; otherwise the cell is `Varies`. Type and layer values never vary within a group. Not applied when itemized. |
| 4. Sort + block | rows, settings.sort | ordered rows | Multi-level sort, asc/desc, **case-insensitive text, numeric order for numbers**. Layer **Order is always the last implicit key** so build-ups stay in sequence. Levels with *Gap row* ticked start a new block when their value changes. |
| 5. Calculations | blocks | blocks + total rows | Per field: none, total (sum), minimum, maximum, min and max. Applied **per block**; **Grand totals** adds a final row. `Varies` and empty cells are skipped. |
| 6. Formatting | blocks | typed cells | Number rounding / decimals, alignment, heading text and orientation. |
| 7. Output split | formatted table | `excel_table`, `revit_table` | Excel keeps columns with *Show in Excel*; Revit drops columns with *Hidden field (Revit)*. Hidden fields still take part in sorting and calculations. |

### 2.3 Rules decided with the user

- **Varies** is shown as the word `Varies` (italic pill in the preview). *Itemize every instance* is the Revit-style alternative.
- **Hidden field (Revit)** and **Show in Excel** are independent. A column can be in Revit only, Excel only, both, or neither (still usable for sorting).
- **Calculation options:** none, calculate totals, minimum, maximum, minimum and maximum.
- **Formatting options per field:** heading, heading orientation (horizontal / vertical), alignment (left / center / right), column width in mm (auto or fixed, Revit only), hidden field, show in Excel, calculation.

### 2.4 Open decisions (defaults assumed unless changed)

| Question | Default |
|----------|---------|
| Itemize on layered types (walls) | One block per element, repeating its layers. May produce many rows; a warning shows the row count before Run. |
| Totals in layered tables | Sum per block of the chosen column (for example total wall thickness). Material Area is not summed by default (it repeats per layer). |
| Itemize column | Adds `Element Id` as first column. |
| Number formatting | Decimals set per field; defaults reproduce v1 (thickness 3 decimals, area 2). |

### 2.5 Testing

- `tests/` folder with plain Python tests (run with `python3`, no Revit).
- Fixtures: mock records for layered walls, curtain walls, doors.
- Cases: each stage alone; default settings reproduce the v1 table exactly; sorting stability; Varies with mixed values;
  totals with empty cells; hidden / excel-only combinations; pagination boundaries.

### Done when

- Default settings on the fixtures reproduce the v1 output row-for-row.
- All stage tests pass on CPython 3 and, where available, IronPython.

---

## Phase 3: Output layers

**Goal:** make the Revit drawing and the Excel writer understand everything the pipeline now produces.

### 3.1 Layout engine (`layout.py`)

Changes from v1:

| Change | Detail |
|--------|--------|
| **Explicit header row** | Receives the header row position from the pipeline instead of searching for the text "Type Mark". Type Mark becomes an ordinary field. |
| **Per-column width** | Auto width stays (`longest text x char width + padding`, minimum 12 mm) unless a fixed width is set. |
| **Alignment** | Per column: left (x = cell left + pad), center, right. Text notes get an explicit width = column width minus padding so Revit aligns the text inside it. |
| **Total rows** | Drawn with a bold text type and a line above. |
| **Vertical headings** | Header row height increases to fit the longest rotated heading. |
| **Pagination** | Unchanged rule: whole blocks never split across pages; title and header repeat. Total rows stay with their block. |

### 3.2 Drafting (`drafting.py`)

- Text notes: set `HorizontalAlignment`; apply `TextNoteOptions.Rotation` (90 degrees) for vertical headings.
- Bold text type reused for headings, titles and total rows.
- Update-in-place behaviour from v1 stays: existing `<name> table <n>` views are cleared and redrawn, their sheet
  placement is kept; extra pages are created and reported; surplus pages are emptied and reported.
- Transaction handled by the caller; failure rolls back everything.

### 3.3 Excel writer (`excel_writer.py`)

| Change | Detail |
|--------|--------|
| Alignment | `HorizontalAlignment` per column (left -4131, center -4108, right -4152). |
| Orientation | `Orientation = 90` for vertical headings. |
| Number formats | `NumberFormat` per column from the decimals setting (for example `0.000`). |
| Total rows | Written as **real `SUM` / `MIN` / `MAX` formulas** over the block range so the workbook stays live; bold. |
| Varies | Written as text; excluded from formulas automatically (text is ignored by `SUM`). |
| Show in Excel | Handled upstream by the pipeline; writer receives only the columns to write. |
| Cleanup | Keeps v1 behaviour: wipe the tab, write, format, save, close, quit; releases the COM object. |

### 3.4 Preview rendering (supports Phase 4)

The **Revit preview is drawn from the same layout output** (lines + text per page) onto a WPF `Canvas`, scaled
(3.6 px per mm in the mockup). No second drawing logic, so the preview cannot drift from the real result.

### Done when

- A table with mixed alignments, a fixed-width column, a vertical heading and totals draws correctly in Revit.
- Excel shows matching alignment and live formulas in total rows.
- Re-running updates the existing views and leaves sheets in place.

---

## Phase 4: XAML window

**Goal:** the approved mockup as a real window.

### 4.1 Window structure

```
Window "Abaco Tables"
  Header
  TabControl (outer)
    Settings   category, wall type, title, table name, Revit output, Excel output   (as v1)
    Preview
      Left card, TabControl (inner):
        Fields             include checkbox, reorder, parameter search + suggestions, reset
        Sorting / Grouping sort levels (column, A-Z / Z-A, gap row), implicit Order row,
                           Grand totals, Itemize every instance
        Formatting         field list (badges: alignment, hidden, no-Excel, sigma) +
                           form for the selected field
      Right area:
        toolbar            [As Excel | As Revit]  live status  [Re-read model]
        As Excel           DataGrid (typed cells, Varies pills, total rows)
        As Revit           scaled paper Canvas, hidden-columns chip, width ruler in mm
  Log box
  Buttons                  Preview table | Run | Close
```

### 4.2 Behaviour

| Interaction | Result |
|-------------|--------|
| Any change on Fields / Sorting / Formatting | Pipeline re-runs on in-memory records; the active preview refreshes immediately. |
| Re-read model | Re-runs the reader (Phase 1) and refreshes. |
| As Excel / As Revit toggle | Switches the preview between `excel_table` and `revit_table`. |
| Category or wall-type change | Loads the saved settings for that selection (Phase 5), or the template defaults. |
| Run | Writes Revit and/or Excel from the same pipeline output; each output reports success or failure separately, as in v1. |
| Add parameter | Search over the field catalogue; adds the field at the end of the list. |
| Reorder | Up / down buttons first; drag and drop is an optional later improvement. |

### 4.3 Implementation notes

- Window code splits: `script.py` (entry), `ui_state.py` (settings <-> controls), `preview.py` (DataGrid and Canvas rendering).
- Controls are wired by `x:Name`; handlers by method name (pyRevit `WPFWindow`).
- Initial XAML events fire while loading, so handlers stay guarded by a ready flag (as in v1).
- Long operations pump the dispatcher so the log repaints. Moving the model read to a background thread is not done
  (Revit API calls must stay on the main thread).
- Validation before Run: view-name and Excel-tab character rules, 31-character tab limit, numeric fields accept a decimal comma.

### Done when

- All three tabs behave as in the mockup, including both preview modes.
- Changing any setting updates the preview without a model rescan.
- Run output matches what the preview showed.

---

## Phase 5: Saved settings

**Goal:** the field arrangement, sorting and formatting survive between sessions.

| Item | Decision |
|------|----------|
| Scope | One saved settings object per **category + wall-type mode** (standard / curtain). |
| Storage | A JSON file next to the user's pyRevit config (`%APPDATA%\pyRevit\`), not inside the Revit project. |
| Versioning | `"v": 1` in the file; unknown fields ignored; missing fields filled from template defaults. |
| Missing parameters | A saved field that no longer exists in the project is kept but flagged "not found" and skipped. |
| Reset | "Reset" restores template defaults for the current selection. |
| Not in this phase | Sharing presets across a team (server file, named presets). Planned after the core works. |

### Done when

- Closing and reopening the window restores the last arrangement per category.
- A corrupt or old-version file falls back to defaults without an error.

---

## Phase 6: Testing and release

### 6.1 Automated (no Revit)

- Pipeline and layout unit tests (Phases 2 and 3) run on every change with `python3`.
- XAML well-formedness check and a cross-check that every `x:Name` and event handler exists in the code.

### 6.2 Manual checklist (run on Revit 2024 and 2027; spot-check 2025, 2026)

1. Extension loads; ribbon button present.
2. Window opens; categories list shows only categories with elements.
3. Walls: standard and curtain modes build; preview matches expectations.
4. Add a shared parameter; reorder; rename heading; hide in Revit; switch off in Excel.
5. Sort by level then Type Mark; confirm gap rows; confirm layer order preserved.
6. Group with differing Comments: cell shows `Varies`. Switch on Itemize: one row per element.
7. Calculate totals on Thickness; check block totals; tick Grand totals.
8. As Revit preview matches the drawing created by Run (widths, alignment, hidden columns).
9. Run twice: views update in place, sheets untouched; shrink the table: surplus view emptied and reported.
10. Excel: new file, existing file, file open elsewhere (read-only error), tab replaced and other tabs intact, formulas live.
11. Floors, roofs, doors and windows tables.
12. Locale check on an Italian-language Revit (localised parameter names, decimal comma).

### 6.3 Release

- Version number in `bundle.yaml`; changelog.
- Install notes: pyRevit 6.4+, CurrentUser attach for Revit 2027, Excel required for the COM writer.
- Zip of the extension folder.

---

## Later (not scheduled)

- **Filter tab** (conditions with AND / OR groups, more than Revit's 8).
- **Shared presets** (named configurations stored on the server).
- **Conditional formatting** and per-column units.
- **Direct `.xlsx` writer** (no Excel needed) if COM proves unreliable.
- **Drag-and-drop** reordering of fields and sort levels.

---

## Phase order and dependencies

| Phase | Depends on | Can be tested without Revit |
|-------|-----------|-----------------------------|
| 0. Baseline | none | no |
| 1. Data layer | 0 | partly (records are pure; reader is not) |
| 2. Pipeline | 1 (record shape only) | **yes** |
| 3. Output layers | 2 | layout yes; drafting and Excel no |
| 4. XAML window | 2, 3 | XAML structure only |
| 5. Saved settings | 4 | yes |
| 6. Testing and release | all | partly |

Phases 1 (record shape) and 2 can start in parallel with Phase 0 testing, because the pipeline is pure Python.
