# -*- coding: utf-8 -*-
"""Phase 1 check (temporary dev button): read the records and compare them with the v1 table builder.

Compares, for the picked category (walls: standard and curtain mode):
  layered tables  : thickness, material and material area of every layer row
  curtain tables  : count, total length, area of every row
  simple tables   : count of every row
Delete this button when Phase 2 replaces table_builder.
"""
from pyrevit import forms, script, revit

from abaco import revit_reader as rr
from abaco.table_builder import build_table
from abaco.records import (K_TYPE_MARK, K_TYPE_NAME, K_FAMILY, K_LEVEL, K_WIDTH, K_HEIGHT, K_LENGTH, K_AREA)

doc = revit.doc


def _t(v):
    return u"" if v is None else v


def _r3(v):
    return None if v is None else round(v, 3)


def _num(v):
    return None if v == u"" or v is None else float(v)


def _same(a, b):
    a, b = _num(a), _num(b)
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) < 0.0051 if False else abs(a - b) < 1e-6


def _bucket(rs, curtain, shape):
    """Group the records the way v1 groups elements for this table shape."""
    d = {}
    for el in rs.elements_in_mode(curtain):
        tr = rs.type_of(el)
        mark, name, fam, lvl = _t(tr.get(K_TYPE_MARK)), _t(tr.get(K_TYPE_NAME)), _t(tr.get(K_FAMILY)), _t(el.get(K_LEVEL))
        if shape == "layered":
            key = (mark, name, lvl)
        elif shape == "curtain":
            key = (mark, name, lvl, _r3(el.get(K_HEIGHT)))
        else:
            key = (mark, fam, name, lvl, _r3(el.get(K_WIDTH)), _r3(el.get(K_HEIGHT)))
        d.setdefault(key, []).append(el)
    return d


def _compare(rs, table, curtain, out):
    headers = table[1]
    hi = dict((h, i) for i, h in enumerate(headers))
    rows = [r for r in table[2:] if any(c != u"" for c in r)]
    shape = "curtain" if curtain else ("layered" if u"Order" in hi else "simple")
    buckets = _bucket(rs, curtain, shape)
    bad, known, checked = [], 0, 0
    last = len(headers) - 1
    for r in rows:
        if shape == "layered":
            key = (r[0], r[1], r[last])
        elif shape == "curtain":
            key = (r[0], r[1], r[last], _r3(_num(r[hi[u"Height (m)"]])))
        else:
            key = (r[0], r[1], r[2], r[last], _r3(_num(r[hi[u"Width (m)"]])), _r3(_num(r[hi[u"Height (m)"]])))
        els = buckets.get(key)
        if not els:
            bad.append(u"no records for row %s" % (key,))
            continue
        checked += 1
        if shape == "layered":
            order = r[hi[u"Order"]]
            if order == u"":
                continue                                    # (no layers) row
            tr = rs.type_of(els[0])
            lay = tr.layers[order - 1]
            exp = None
            if lay.material_id is not None:
                exp = sum(e.material_areas.get(lay.material_id, 0.0) for e in els)
            got = _num(r[hi[u"Material Area (m\u00b2)"]])
            if lay.material != r[hi[u"Material"]] or abs(lay.thickness - r[hi[u"Thickness (m)"]]) > 5e-5:
                bad.append(u"layer mismatch %s order %s" % (key, order))
            elif exp is None or got is None:
                if not (exp is None and got is None):
                    bad.append(u"area presence %s order %s: v1=%s records=%s" % (key, order, got, exp))
            elif abs(round(exp, 2) - got) > 1e-6:
                reps = sum(1 for l in tr.layers if l.material_id == lay.material_id)
                if reps > 1 and abs(round(exp * reps, 2) - got) < 0.011:
                    known += 1                              # v1 adds the same material once per layer
                else:
                    bad.append(u"area %s order %s: v1=%s records=%s" % (key, order, got, round(exp, 2)))
        elif shape == "curtain":
            cnt = len(els)
            length = round(sum(e.get(K_LENGTH) or 0.0 for e in els), 2)
            areas = [e.get(K_AREA) for e in els if e.get(K_AREA) is not None]
            area = round(sum(areas), 2) if areas else None
            if cnt != r[hi[u"Count"]] or not _same(length, r[hi[u"Total Length (m)"]]) \
                    or not _same(area, r[hi[u"Area (m\u00b2)"]]):
                bad.append(u"%s: v1 count/len/area=%s/%s/%s records=%s/%s/%s" % (
                    key, r[hi[u"Count"]], r[hi[u"Total Length (m)"]], r[hi[u"Area (m\u00b2)"]], cnt, length, area))
        else:
            if len(els) != r[hi[u"Count"]]:
                bad.append(u"%s: v1 count=%s records=%s" % (key, r[hi[u"Count"]], len(els)))
    n_rec = len(rs.elements_in_mode(curtain))
    out.print_md(u"**%s**: %d v1 rows checked, %d mismatches, %d elements in records for this mode." % (
        u"curtain walls" if curtain else u"standard", checked, len(bad), n_rec))
    if known:
        out.print_md(u"- %d layer rows differ only because v1 counts a material once per layer "
                     u"(material used in 2+ layers). Records hold the true value." % known)
    for b in bad[:25]:
        out.print_md(u"- MISMATCH: %s" % b)
    if len(bad) > 25:
        out.print_md(u"- ... and %d more" % (len(bad) - 25))


def main():
    out = script.get_output()
    cats = rr.list_model_categories(doc)
    labels = [u"%s  (%d)" % (n, c) for n, c, _ in cats]
    pick = forms.SelectFromList.show(labels, title="Records check: pick a category", multiselect=False)
    if not pick:
        return
    name, count, cat = cats[labels.index(pick)]
    out.print_md(u"## Records check: %s" % name)

    rs = rr.read_category(doc, cat, log=lambda m: None)
    for line in rs.summary_lines():
        out.print_md(u"- %s" % line)
    out.print_md(u"- Fields: %s" % u", ".join(u"%s [%s/%s]" % (f.label, f.scope, f.kind) for f in rs.fields[:40]))

    is_walls = rr.eid_val(cat.Id) == int(rr.DB.BuiltInCategory.OST_Walls)
    elements = list(rr.elements_filter(doc, cat).ToElements())
    for curtain in ([False, True] if is_walls else [False]):
        table = build_table(doc, elements, u"", curtain)
        _compare(rs, table, curtain, out)

    # on-demand values: first non-core field of each scope
    extra = [f for f in rs.fields if not f.core][:3]
    if extra:
        missing = rr.ensure_values(doc, rs, [f.key for f in extra])
        for f in extra:
            sample = [rs.value(e, f.key) for e in rs.elements[:3]]
            out.print_md(u"- on-demand '%s' (%s): first values %s" % (f.label, f.scope, sample))
        if missing:
            out.print_md(u"- could not read: %s" % missing)


if __name__ == "__main__":
    if not doc or doc.IsFamilyDocument:
        forms.alert("Open a Revit project first.", exitscript=True)
    main()
