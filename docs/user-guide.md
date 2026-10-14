# Abaco Tables: user guide

This guide covers every tab of the Abaco Tables window. For a quick start, see the [README](../README.md).

![Abaco Tables main window](images/main-window.png)
<!-- Placeholder: full window, Preview tab open, Walls category -->

---

## Settings tab

![Settings tab](images/settings-tab.png)
<!-- Placeholder: Settings tab with category, table type, title block and Excel path filled in -->

**Source**
- **Table type.** *Schedule / Quantities* gives one row per type, level and size. *Material takeoff* expands each layered type into its layers. A takeoff on a category with no layered types is built as a schedule, with a message.
- **Category.** Every model category that has elements in the project. For curtain walls, use a filter in the Preview tab.

**Table**
- **Title.** Shown above the table. Leave blank for `Abaco <Category>`.
- **Table name.** The Excel tab name, and the key Abaco uses to find the Revit views again on the next run. Excel allows up to 31 characters.

**Revit**
- **Sheet number prefix.** Used for new sheets only, for example `AM` gives `AM-01`, `AM-02`.
- **Title block.** The sheet template. Choose *(no title block)* to create views without sheets.
- **Max table height (mm).** Longer tables split across views. A block is never split.

**Excel**
- **Workbook.** The `.xlsx` file. Abaco creates it if missing. The chosen tab is replaced; other tabs are not touched.

---

## Preview tab

The Preview tab has two parts. The left side holds the edit tabs. The right side shows the table: *As Excel* (a grid of styled cells) or *As Revit* (a drawing of the table on the page). Both are built from the same data.

Click **Re-read model** after you change the model. Abaco reads the model again only on this command, or when the category or table type changes.

### Fields

![Fields tab](images/fields-tab.png)
<!-- Placeholder: Fields tab showing table fields with ↑ ↓ × icons and Add parameter list -->

- **Table fields** are the columns, in order. Select one, then use the arrows to move it, or × to remove it. Removed fields return to *Add parameter*.
- **Add parameter** lists the parameters found on the category. Search, select, then click the add icon.
- **Custom field** opens the field editor to create a calculated column.
- **Edit** and **Delete** apply to custom fields only.
- **Reset** restores the default fields for the category. Custom fields are kept.

### Filter

![Filter tab](images/filter-tab.png)
<!-- Placeholder: Filter tab with two conditions joined by AND -->

Each condition is a field, an operator and a value. Choose **All (AND)** or **Any (OR)** to combine them.

- Conditions on **model fields** run on the elements before grouping, so counts and totals include only matching elements.
- Conditions on **calculated fields** run after grouping, on the row values. A row whose value is *Varies* is kept, because some of its elements may match.
- A condition with an empty value is ignored until you fill it in. A condition that cannot be used shows a message under it.

### Sort and group

![Sort and group tab](images/sort-group-tab.png)
<!-- Placeholder: Sort & group tab with two levels, Header and Footer ticked -->

- **Levels** sort the rows. The first level is the outermost.
- **Header** adds a bold row with the group value above each block.
- **Footer** adds a totals row at the end of each block. Choose what the footer calculates: per field (the field's own calculation), totals, minimum, maximum, or minimum and maximum.
- **Gap row** adds a blank row after the level's blocks.
- **Header summary (Total, Min, Max)** adds a summary at the bottom of the table.
- **Itemize every instance** shows one row per element, instead of merging identical elements.

Footers use `SUBTOTAL` in Excel, so a grand total never counts a value twice.

### Formatting

![Formatting tab](images/formatting-tab.png)
<!-- Placeholder: Formatting tab with a field selected, showing heading, alignment and calculation -->

Select a field to format it.

- **Heading.** The column heading. Leave it as the field name to use the default.
- **Alignment (data).** Left, centre or right, for the cells of this field.
- **Column width (Revit).** Auto, or a fixed width in mm.
- **Calculation.** Totals, minimum, maximum, or both, for this field in footers and the summary.
- **Hidden field (Revit).** Leaves the column out of the Revit drawing.
- **Show in Excel.** Writes or leaves out the column in the workbook.

A column hidden in Revit and switched off in Excel is still available for sorting and filtering.

### Appearance

![Appearance tab](images/appearance-tab.png)
<!-- Placeholder: Appearance tab with Office theme selected, zebra on -->

- **Theme.** Black & white, Office, Accent, or Custom. Changing any setting switches the theme to Custom.
- **Font and size.** Any font installed on the machine. Size is the text height in mm.
- **Elements.** Title, heading row, group header rows, summary header, summary rows and data rows. Each has bold, italic, underline, case, text and background colour, and lines.
- **Alignment and orientation.** For headings and summary rows. Data rows use the alignment set in Formatting.
- **Zebra striping, lines and gridlines.** Lines can be outer, inner or both.
- **Wrap text.** Wraps long cells onto several lines. Revit and the preview use the same line breaks.
- **Excel only.** Freeze the title and heading rows, and show gridlines.

Revit draws text in black, and does not draw text colour. Excel and the preview show it.

### Row numbers

Row numbers add a numbering column that counts the visible data rows from 1. Header, footer, summary and blank rows get no number. The numbers follow the final order, so they change after sorting or filtering.

In Excel, numbers recalculate when you re-sort or filter the sheet. In Revit, they are set at each run.

---

## Running the table

1. Click **Run** at the bottom of the window.
2. The log shows what was written: views created or updated, sheets, and the Excel tab.
3. Check the Revit views and the Excel tab. The first run creates sheets. Later runs update the same views in place.

If the table grows past the page height, Abaco adds a new view. If it shrinks, the surplus view is emptied and reported in the log.

---

## Troubleshooting

| Message | What to do |
|---|---|
| *No elements match the filter* | Change or clear the conditions in the Filter tab. |
| *The Excel file is open somewhere else (read-only)* | Close the workbook in Excel, then run again. |
| *Table is too big for the title block* | Reduce the number of columns, narrow the fixed widths, or choose a larger title block. |
| *Value shows #ERROR* | The formula could not be calculated for that row. Hover over the warning in the log, or open the field editor to see the first failing row. |
| *Varies* | The elements in one row have different values for that field. Itemize the table, or add a calculation. |
| *Excel: Excel is not installed or not registered* | Install desktop Excel, or run the table to Revit only. |

If a message is not listed here, copy the log text from the bottom of the window when you report the issue.

---

## Formulas

Custom fields use the formula language described in the [formula reference](formulas.md).
