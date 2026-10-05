# Abaco Tables (pyRevit extension)

Port of the Dynamo graph `Abaco_Murature_Sync.dyn`.

## Install
1. Copy the `Abaco.extension` folder anywhere (e.g. `C:\pyRevitExtensions\`).
2. pyRevit > Settings > Custom Extension Directories > add that parent folder > Save Settings and Reload.
3. A new **Abaco** tab appears with an **Abaco Tables** button.

## Layout
```
Abaco.extension/
  lib/abaco/
    table_builder.py   model -> table rows        (Dynamo node 4ebf70)
    layout.py          rows -> lines/text + pages (first half of node 3436a1, pure Python)
    drafting.py        draws views + sheets       (second half of node 3436a1)
    excel_writer.py    Excel COM writer           (node 2622c8)
  Abaco.tab/Tables.panel/AbacoTables.pushbutton/
    script.py          command + window code
    ui.xaml            WPF window
```
Project-specific defaults (Excel paths, tab names, prefixes, hidden columns, text height, page height)
are at the top of `script.py`.

Optional: drop a 96x96 `icon.png` in the pushbutton folder for a ribbon icon.
