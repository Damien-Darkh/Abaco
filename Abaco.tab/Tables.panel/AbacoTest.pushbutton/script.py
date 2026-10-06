# -*- coding: utf-8 -*-
"""
Abaco Automated Test
Runs the REAL AbacoTables.pushbutton/script.py once for each requested
category, automatically supplying the category selection.
The original script.py is NOT duplicated here.

Categories:
Ceilings
Curtain Wall Panels
Curtain Wall Mullions
Doors
Floors
Roofs
Rooms
Walls
Windows

For Walls, the original script.py automatically checks both:
- standard walls
- curtain walls
"""

import imp
import os
import traceback
from pyrevit import forms, revit, script

doc = revit.doc
out = script.get_output()

# ============================================================================
# Locate the real AbacoTables.pushbutton/script.py
# ============================================================================
HERE = os.path.dirname(__file__)
ABACO_TABLES_DIR = os.path.abspath(
    os.path.join(HERE, "..", "AbacoTables.pushbutton")
)
ABACO_SCRIPT_PATH = os.path.join(ABACO_TABLES_DIR, "script.py")

# ============================================================================
# Categories we want to test
# ============================================================================
REQUESTED_CATEGORIES = [
    u"Ceilings",
    u"Curtain Wall Panels",
    u"Curtain Wall Mullions",
    u"Doors",
    u"Floors",
    u"Roofs",
    u"Rooms",
    u"Walls",
    u"Windows",
]


# ============================================================================
# Helpers
# ============================================================================
def _normalise(value):
    """Normalise category names for matching."""
    if value is None:
        return u""
    value = unicode(value)

    # Make matching tolerant of whitespace/case.
    return u" ".join(value.lower().split())


def _find_category_label(requested, labels):
    """Find the actual label returned by rr.list_model_categories().

    First tries an exact match.
    Then allows common Revit naming variations.
    """
    wanted = _normalise(requested)

    # Exact match
    for label in labels:
        if _normalise(label).split(u"  (")[0] == wanted:
            return label

    # Match category name before the "(count)" suffix.
    for label in labels:
        clean = label.split(u"  (")[0]
        if _normalise(clean) == wanted:
            return label

    # A few tolerant aliases.
    aliases = {
        _normalise(u"Curtain Wall Panels"): [
            u"curtain wall panels",
            u"curtain panels",
        ],
        _normalise(u"Curtain Wall Mullions"): [
            u"curtain wall mullions",
            u"curtain mullions",
        ],
    }

    alternatives = aliases.get(wanted, [])

    for alternative in alternatives:
        for label in labels:
            clean = label.split(u"  (")[0]
            if _normalise(clean) == alternative:
                return label

    return None


def _load_abaco_script():
    """Load the REAL AbacoTables.pushbutton/script.py.

    The module is imported rather than copied. This means the automated test
    always exercises the actual production script.
    """
    if not os.path.exists(ABACO_SCRIPT_PATH):
        raise IOError(
            "Could not find AbacoTables.pushbutton/script.py:\n\n{}".format(
                ABACO_SCRIPT_PATH
            )
        )

    return imp.load_source("abaco_tables_real_script", ABACO_SCRIPT_PATH)


def _make_selector(target_label):
    """Create a replacement for forms.SelectFromList.show().

    The real script calls:

        forms.SelectFromList.show(
            labels,
            title="Records check: pick a category",
            multiselect=False
        )

    We intercept that call and return the category that the automated
    test currently wants to execute.
    """

    def select_from_list(items, title=None, multiselect=False, **kwargs):
        # Make sure the requested category actually exists in the list
        # presented by script.py.
        if target_label in items:
            return target_label

        # Try matching without the count suffix.
        target_clean = target_label.split(u"  (")[0]

        for item in items:
            item_clean = item.split(u"  (")[0]
            if _normalise(item_clean) == _normalise(target_clean):
                return item

        raise RuntimeError(
            "Automated test could not select category:\n{}".format(target_label)
        )

    return select_from_list


def _run_category(abaco_script, category_label):
    """Execute the REAL script.py main() for one category.

    No duplicate table-building logic is used here.
    """
    # Save the original picker method
    original_selector = forms.SelectFromList.show

    try:
        # Wrap in classmethod so IronPython handles invocation properly without treating 'items' as 'self'
        mock_func = _make_selector(category_label)
        forms.SelectFromList.show = classmethod(
            lambda cls, items, **kwargs: mock_func(items, **kwargs)
        )

        # Run the real script.py
        abaco_script.main()

    finally:
        # Always restore pyRevit's real selector
        forms.SelectFromList.show = original_selector


# ============================================================================
# Main
# ============================================================================
def main():
    if not doc or doc.IsFamilyDocument:
        forms.alert("Open a Revit project first.", exitscript=True)
        return

    out.set_title("Abaco Automated Test")

    out.print_md("# Abaco automated test")
    out.print_md("")
    out.print_md("**Testing:** `AbacoTables.pushbutton/script.py``")
    out.print_md("")
    out.print_md(
        "**One real `script.py` execution is performed for each category.**"
    )
    out.print_md("")
    out.print_md("---")

    # ------------------------------------------------------------------------
    # Load the production script.
    # ------------------------------------------------------------------------
    try:
        abaco_script = _load_abaco_script()

    except Exception:
        out.print_md("## FAILED TO LOAD SCRIPT")
        out.print_md("```text\n{}\n```".format(traceback.format_exc()))
        forms.alert(
            "Could not load:\n\n{}".format(ABACO_SCRIPT_PATH),
            title="Abaco Automated Test",
        )
        return

    # ------------------------------------------------------------------------
    # Ask the REAL revit_reader for the available categories.
    # ------------------------------------------------------------------------
    try:
        cats = abaco_script.rr.list_model_categories(doc)

    except Exception as ex:
        out.print_md("## FAILED TO READ CATEGORIES")
        out.print_md("```text\n{}\n```".format(traceback.format_exc()))
        forms.alert(
            "Could not read Revit model categories.\n\n{}".format(ex),
            title="Abaco Automated Test",
        )
        return

    available_labels = [u"%s  (%d)" % (name, count) for name, count, cat in cats]

    out.print_md(
        "**Categories reported by `revit_reader`: {}**".format(
            len(available_labels)
        )
    )
    out.print_md("")

    # ------------------------------------------------------------------------
    # Run every requested category.
    # ------------------------------------------------------------------------
    passed = 0
    failed = 0
    skipped = 0

    results = []

    for requested in REQUESTED_CATEGORIES:
        out.print_md("---")
        out.print_md("## {}".format(requested))

        # Find the label exactly as script.py will receive it.
        actual_label = _find_category_label(requested, available_labels)

        if actual_label is None:
            skipped += 1
            out.print_md(
                "**SKIPPED:** category was not returned by "
                "`revit_reader.list_model_categories()`."
            )
            results.append((requested, "SKIPPED"))
            continue

        out.print_md("- Selected category: `{}`".format(actual_label))

        try:
            # --------------------------------------------------------------
            # Run the actual production script.py.
            # --------------------------------------------------------------
            _run_category(abaco_script, actual_label)

            passed += 1
            results.append((requested, "PASS"))
            out.print_md("**PASS — real script.py completed successfully.**")

        except Exception as ex:
            failed += 1
            results.append((requested, "FAIL"))
            out.print_md("**FAIL:** `{}`".format(ex))
            out.print_md("```text\n{}\n```".format(traceback.format_exc()))
            continue

    # ------------------------------------------------------------------------
    # Final summary.
    # ------------------------------------------------------------------------
    out.print_md("")
    out.print_md("---")
    out.print_md("# Final results")

    for name, status in results:
        if status == "PASS":
            marker = "PASS"
        elif status == "FAIL":
            marker = "FAIL"
        else:
            marker = "SKIP"

        out.print_md("- **{}** — {}".format(marker, name))

    out.print_md("")
    out.print_md(
        "**Passed:** {}  |  **Failed:** {}  |  **Skipped:** {}".format(
            passed, failed, skipped
        )
    )
    out.print_md("")

    if failed == 0 and skipped == 0:
        out.print_md("## ALL TESTS PASSED")
        message = (
            "Abaco automated test completed.\n\n"
            "All {} categories ran successfully.".format(
                len(REQUESTED_CATEGORIES)
            )
        )
    else:
        out.print_md("## TEST RUN COMPLETED WITH ISSUES")
        message = (
            "Abaco automated test completed.\n\n"
            "Passed: {}\n"
            "Failed: {}\n"
            "Skipped: {}".format(passed, failed, skipped)
        )

    forms.alert(message, title="Abaco Automated Test", warn_icon=(failed > 0))


if __name__ == "__main__":
    main()