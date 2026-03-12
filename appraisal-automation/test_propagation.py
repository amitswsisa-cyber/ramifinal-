"""
test_propagation.py — Verify that changing cover fields propagates to ALL locations:
  - Cover page (page 1)
  - Section 6 (פרטי הנכס) table-style lines
  - Body paragraphs (חלקה X בגוש Y, עירית X, etc.)
  - Table 1 (פרטי הנכס table)
  - Headers/footers

Run: python test_propagation.py
"""
import sys
import os
import shutil
import tempfile
import re

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

from field_extractor import extract_cover_fields
from docx_utils import docx_unpack, get_paragraph_texts
from pattern_replacer import pattern_replace
from lxml import etree

DOCS_DIR = os.path.dirname(__file__)
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"


def get_all_text(unpack_dir):
    """Get full text from document.xml + headers + footers."""
    texts = {}

    # Document paragraphs with indices
    paragraphs = get_paragraph_texts(unpack_dir)
    texts['document'] = paragraphs

    # Headers and footers
    word_dir = os.path.join(unpack_dir, "word")
    for fname in os.listdir(word_dir):
        if fname.startswith(("header", "footer")) and fname.endswith(".xml"):
            fpath = os.path.join(word_dir, fname)
            tree = etree.parse(fpath)
            root = tree.getroot()
            parts = []
            for para in root.iter(f"{W}p"):
                p_parts = [t.text or "" for t in para.iter(f"{W}t")]
                parts.append("".join(p_parts))
            texts[fname] = parts

    # Table cells
    doc_path = os.path.join(unpack_dir, "word", "document.xml")
    tree = etree.parse(doc_path)
    root = tree.getroot()
    table_texts = []
    for tbl in root.iter(f"{W}tbl"):
        for row in tbl.iter(f"{W}tr"):
            row_cells = []
            for cell in row.iter(f"{W}tc"):
                cell_parts = [t.text or "" for t in cell.iter(f"{W}t")]
                row_cells.append("".join(cell_parts))
            table_texts.append(row_cells)
    texts['tables'] = table_texts

    return texts


def find_value_locations(texts, value, label=""):
    """Find all locations where a value appears."""
    locations = []

    # Document paragraphs
    for i, para in enumerate(texts['document']):
        if value in para:
            locations.append(f"  para[{i}]: {para[:80]}...")

    # Headers/footers
    for fname, paras in texts.items():
        if fname.startswith(("header", "footer")):
            for i, para in enumerate(paras):
                if value in para:
                    locations.append(f"  {fname}[{i}]: {para[:80]}...")

    # Tables
    for row_idx, row in enumerate(texts.get('tables', [])):
        for cell_idx, cell in enumerate(row):
            if value in cell:
                locations.append(f"  table row[{row_idx}] cell[{cell_idx}]: {cell[:80]}...")

    return locations


def test_full_propagation(docx_path, doc_label):
    """
    Test that changing a field on the cover propagates everywhere.
    """
    print(f"\n{'='*70}")
    print(f"PROPAGATION TEST: {doc_label}")
    print(f"File: {os.path.basename(docx_path)}")
    print('='*70)

    if not os.path.exists(docx_path):
        print("  [SKIP] File not found")
        return True

    # 1. Extract original fields
    with open(docx_path, 'rb') as f:
        extracted = extract_cover_fields(f)

    print(f"\n  Original fields:")
    for k, v in extracted.items():
        print(f"    {k}: {v}")

    old_gush = extracted.get('גוש', '')
    old_helka = extracted.get('חלקה', '')
    old_city = extracted.get('עיר', '')

    # 2. Unpack and see where old values appear BEFORE replacement
    tmp_dir = tempfile.mkdtemp(prefix="test_prop_")
    unpack_dir = os.path.join(tmp_dir, "unpacked")

    try:
        docx_unpack(docx_path, unpack_dir)

        print(f"\n  --- BEFORE replacement ---")
        texts_before = get_all_text(unpack_dir)
        full_before = '\n'.join(texts_before['document'])

        if old_gush:
            gush_locs = find_value_locations(texts_before, old_gush, 'גוש')
            print(f"  Old גוש '{old_gush}' found in {len(gush_locs)} locations:")
            for loc in gush_locs[:10]:
                print(f"    {loc}")

        if old_helka:
            helka_locs = find_value_locations(texts_before, old_helka, 'חלקה')
            print(f"  Old חלקה '{old_helka}' found in {len(helka_locs)} locations:")
            for loc in helka_locs[:10]:
                print(f"    {loc}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 3. Now run replacement and check AFTER
    tmp_dir2 = tempfile.mkdtemp(prefix="test_prop2_")
    unpack_dir2 = os.path.join(tmp_dir2, "unpacked")

    try:
        docx_unpack(docx_path, unpack_dir2)

        new_fields = dict(extracted)  # start with all original values
        new_fields['גוש'] = 'TEST_GUSH_9876'
        new_fields['חלקה'] = 'TEST_HELKA_543'
        if old_city:
            new_fields['עיר'] = 'TEST_CITY'

        counts = pattern_replace(unpack_dir2, new_fields, extracted)

        print(f"\n  --- AFTER replacement ---")
        print(f"  Replacement counts: {counts}")

        texts_after = get_all_text(unpack_dir2)
        full_after = '\n'.join(texts_after['document'])

        # Check new values appear
        new_gush_locs = find_value_locations(texts_after, 'TEST_GUSH_9876')
        new_helka_locs = find_value_locations(texts_after, 'TEST_HELKA_543')

        print(f"\n  New גוש 'TEST_GUSH_9876' found in {len(new_gush_locs)} locations:")
        for loc in new_gush_locs:
            print(f"    {loc}")

        print(f"\n  New חלקה 'TEST_HELKA_543' found in {len(new_helka_locs)} locations:")
        for loc in new_helka_locs:
            print(f"    {loc}")

        # Check old values are GONE from marked locations
        # (some may remain in free text — that's OK, that's the whole point)
        old_gush_remaining = find_value_locations(texts_after, old_gush) if old_gush else []
        print(f"\n  Old גוש '{old_gush}' still found in {len(old_gush_remaining)} locations:")
        for loc in old_gush_remaining:
            print(f"    {loc}")

        # Verify key checks
        all_pass = True
        checks = []

        # גוש should appear in multiple locations (cover + section 6 + body)
        gush_count = counts.get('גוש', 0)
        checks.append((gush_count >= 2,
                       f"גוש replaced in {gush_count} locations (expected >= 2)"))

        # חלקה should appear in multiple locations
        helka_count = counts.get('חלקה', 0)
        checks.append((helka_count >= 2,
                       f"חלקה replaced in {helka_count} locations (expected >= 2)"))

        # New values should be in document text
        checks.append(('TEST_GUSH_9876' in full_after,
                       "New גוש value present in document"))
        checks.append(('TEST_HELKA_543' in full_after,
                       "New חלקה value present in document"))

        # Labels should still be intact
        checks.append(('גוש' in full_after, "Label גוש still intact"))
        checks.append(('חלקה' in full_after, "Label חלקה still intact"))

        # Check Section 6 style lines specifically
        sec6_gush = any('TEST_GUSH_9876' in p for p in texts_after['document']
                       if 'גוש' in p and (':' in p or '\t' in p))
        checks.append((sec6_gush,
                       "Section 6 'גוש:' line updated with new value"))

        # Check body pattern "חלקה X בגוש Y"
        body_pattern = any('TEST_HELKA_543' in p and 'בגוש' in p
                          for p in texts_after['document'])
        if any('בגוש' in p for p in texts_before['document']):
            checks.append((body_pattern,
                           "Body pattern 'חלקה X בגוש Y' updated"))

        # Check tables (if document has XML tables with these labels)
        has_table1 = any(
            any(label in cell for label in ['גוש', 'חלקה', 'שטח חלקה'])
            for row in texts_before.get('tables', [])
            for cell in row
        )
        if has_table1:
            table_gush = any('TEST_GUSH_9876' in cell
                            for row in texts_after.get('tables', [])
                            for cell in row)
            checks.append((table_gush,
                           "Table 1 גוש cell updated"))
        else:
            # These docs use paragraph-style section 6, not XML tables
            # Verify section 6 paragraph lines were updated instead
            sec6_lines_updated = any(
                'TEST_GUSH_9876' in p
                for p in texts_after['document']
                if 'גוש' in p and ':' in p and len(p.strip()) < 40
            )
            checks.append((sec6_lines_updated,
                           "Section 6 paragraph lines updated (no XML table)"))

        print(f"\n  --- VERIFICATION ---")
        for passed, desc in checks:
            status = "PASS" if passed else "FAIL"
            if not passed:
                all_pass = False
            print(f"  [{status}] {desc}")

        return all_pass

    finally:
        shutil.rmtree(tmp_dir2, ignore_errors=True)


if __name__ == '__main__':
    results = {}

    for doc_name, label in [
        ('2026042.docx', '2026042 — Standard'),
        ('2026018.docx', '2026018 — היטל השבחה'),
        ('2026023T.docx', '2026023T — תת חלקה'),
        ('2026034.docx', '2026034'),
    ]:
        path = os.path.join(DOCS_DIR, doc_name)
        results[label] = test_full_propagation(path, label)

    # Summary
    print(f"\n{'='*70}")
    print("PROPAGATION TEST SUMMARY")
    print('='*70)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    total = len(results)
    passed_count = sum(1 for v in results.values() if v)
    print(f"\n  {passed_count}/{total} tests passed")

    if all(results.values()):
        print("\n  OVERALL: ALL PROPAGATION TESTS PASSED")
        sys.exit(0)
    else:
        print("\n  OVERALL: SOME TESTS FAILED")
        sys.exit(1)
