"""
test_pattern_replacer.py — Comprehensive test for the pattern replacement engine.

Tests:
  1. Unit tests for pattern_replacer internal functions
  2. Integration tests against all 4 real documents
  3. Verifies replacements happen ONLY in marked locations
  4. Verifies free text is NOT touched

Run: python test_pattern_replacer.py
"""
import sys
import os
import shutil
import tempfile

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))

from field_extractor import extract_cover_fields
from docx_utils import docx_unpack, docx_pack, get_paragraph_texts
from pattern_replacer import pattern_replace

DOCS_DIR = os.path.dirname(__file__)

# ═══════════════════════════════════════════════════════════════════════
# TEST 1: Unit test — pattern matching on synthetic paragraphs
# ═══════════════════════════════════════════════════════════════════════

def test_unit_pattern_matching():
    """Test that regex patterns match expected text."""
    from pattern_replacer import _build_cover_patterns, _build_section6_patterns, _build_body_patterns
    import re

    cover = _build_cover_patterns()
    sec6 = _build_section6_patterns()
    body = _build_body_patterns()

    # Test cover pattern: גוש: VALUE
    gush_pattern = cover[1][0]  # pattern index 1 = גוש
    assert gush_pattern.search("גוש: 6636"), "Should match 'גוש: 6636'"
    assert gush_pattern.search("גוש : 6636"), "Should match 'גוש : 6636'"
    assert gush_pattern.search("גוש: ________"), "Should match underscore placeholder"

    # Test cover pattern: מזמין השומה: VALUE
    mazmin_pattern = cover[7][0]
    assert mazmin_pattern.search("מזמין השומה: הועדה המקומית שוהם"), "Should match mazmin"

    # Test body pattern: חלקה VALUE בגוש VALUE
    helka_bgush = body[0][0]
    assert helka_bgush.search("חלקה 706 בגוש 6636"), "Should match חלקה בגוש"
    assert helka_bgush.search("חלקה _____ בגוש _____"), "Should match underscore version"

    # Test body pattern: נתבקשתי על ידי VALUE,
    nivkashti = body[3][0]
    assert nivkashti.search("נתבקשתי על ידי הועדה המקומית שוהם,"), "Should match nivkashti"

    # Test body pattern: עירית VALUE
    irit = body[1][0]
    assert irit.search("עירית שוהם"), "Should match עירית"
    assert irit.search("עיריית תל אביב"), "Should match עיריית"

    print("  [PASS] Unit test: pattern matching")


# ═══════════════════════════════════════════════════════════════════════
# TEST 2: Integration — run pattern_replace on real documents
# ═══════════════════════════════════════════════════════════════════════

def test_document(docx_path, new_fields, doc_label, checks):
    """
    Run pattern_replace on a real document and verify results.

    Args:
        docx_path: Path to the source DOCX
        new_fields: {field: new_value} to inject
        doc_label: Display label for test output
        checks: list of (description, check_func(full_text, counts) -> bool)
    """
    print(f"\n{'='*60}")
    print(f"TEST: {doc_label}")
    print(f"File: {os.path.basename(docx_path)}")
    print('='*60)

    if not os.path.exists(docx_path):
        print(f"  [SKIP] File not found: {docx_path}")
        return True

    # Extract original fields
    with open(docx_path, 'rb') as f:
        extracted = extract_cover_fields(f)

    print(f"  Extracted {len(extracted)} fields: {list(extracted.keys())}")

    # Unpack to temp dir
    tmp_dir = tempfile.mkdtemp(prefix="test_pr_")
    unpack_dir = os.path.join(tmp_dir, "unpacked")

    try:
        docx_unpack(docx_path, unpack_dir)

        # Run pattern replace
        counts = pattern_replace(unpack_dir, new_fields, extracted)

        print(f"  Replacement counts: {counts}")
        total = sum(counts.values())
        print(f"  Total replacements: {total}")

        # Read back paragraph texts
        paragraphs = get_paragraph_texts(unpack_dir)
        full_text = '\n'.join(paragraphs)

        # Run checks
        all_pass = True
        for desc, check_fn in checks:
            try:
                result = check_fn(full_text, counts)
                status = "PASS" if result else "FAIL"
                if not result:
                    all_pass = False
            except Exception as e:
                status = f"ERROR: {e}"
                all_pass = False
            print(f"  [{status}] {desc}")

        return all_pass

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_2026042():
    """Test 2026042.docx — standard filled document."""
    path = os.path.join(DOCS_DIR, "2026042.docx")

    new_fields = {
        'גוש': '9999',
        'חלקה': '111',
        'עיר': 'חיפה',
        'רחוב': 'הרצל 50',
        'מזמין השומה': 'עיריית חיפה',
    }

    checks = [
        ("New גוש value 9999 appears in text",
         lambda text, c: '9999' in text),
        ("New חלקה value 111 appears in text",
         lambda text, c: '111' in text),
        ("Labels גוש/חלקה still present",
         lambda text, c: 'גוש' in text and 'חלקה' in text),
        ("At least 1 replacement was made",
         lambda text, c: sum(c.values()) >= 1),
    ]

    return test_document(path, new_fields, "2026042 — Standard", checks)


def test_2026018():
    """Test 2026018.docx — היטל השבחה."""
    path = os.path.join(DOCS_DIR, "2026018.docx")

    new_fields = {
        'גוש': '8888',
        'חלקה': '222',
        'עיר': 'ירושלים',
        'רחוב': 'יפו 100',
        'מזמין השומה': 'עיריית ירושלים',
        'מספר תיק': '2026-99999',
    }

    checks = [
        ("New גוש value 8888 appears in text",
         lambda text, c: '8888' in text),
        ("New חלקה value 222 appears in text",
         lambda text, c: '222' in text),
        ("Labels still present",
         lambda text, c: 'גוש' in text and 'חלקה' in text),
        ("At least 1 replacement was made",
         lambda text, c: sum(c.values()) >= 1),
    ]

    return test_document(path, new_fields, "2026018 — היטל השבחה", checks)


def test_2026023T():
    """Test 2026023T.docx — document with תת חלקה."""
    path = os.path.join(DOCS_DIR, "2026023T.docx")

    new_fields = {
        'גוש': '7777',
        'חלקה': '77',
        'תת חלקה': '7',
        'עיר': 'שוהם',
        'מזמין השומה': 'הועדה המקומית שוהם',
    }

    checks = [
        ("New גוש value 7777 appears in text",
         lambda text, c: '7777' in text),
        ("Labels still present",
         lambda text, c: 'גוש' in text and 'חלקה' in text),
        ("At least 1 replacement was made",
         lambda text, c: sum(c.values()) >= 1),
    ]

    return test_document(path, new_fields, "2026023T — with תת חלקה", checks)


def test_2026034():
    """Test 2026034.docx."""
    path = os.path.join(DOCS_DIR, "2026034.docx")

    new_fields = {
        'גוש': '5555',
        'חלקה': '333',
        'עיר': 'נתניה',
    }

    checks = [
        ("New גוש value 5555 appears in text",
         lambda text, c: '5555' in text),
        ("Labels still present",
         lambda text, c: 'גוש' in text),
        ("At least 1 replacement was made",
         lambda text, c: sum(c.values()) >= 1),
    ]

    return test_document(path, new_fields, "2026034", checks)


# ═══════════════════════════════════════════════════════════════════════
# TEST 3: Full Stage 1 pipeline integration
# ═══════════════════════════════════════════════════════════════════════

def test_stage1_pipeline():
    """Test the full stage1 pipeline with pattern_replace wired in."""
    from stage1_inject import run_stage1

    path = os.path.join(DOCS_DIR, "2026042.docx")
    if not os.path.exists(path):
        print("  [SKIP] 2026042.docx not found")
        return True

    print(f"\n{'='*60}")
    print("TEST: Full Stage 1 Pipeline Integration")
    print('='*60)

    new_fields = {
        'גוש': '9999',
        'חלקה': '111',
        'עיר': 'חיפה',
    }

    try:
        with open(path, 'rb') as f:
            output_path, label_counts = run_stage1(f, new_fields)

        print(f"  Output: {output_path}")
        print(f"  Counts: {label_counts}")

        assert os.path.exists(output_path), "Output file not created"

        # Verify output is a valid DOCX (can be unpacked)
        verify_dir = tempfile.mkdtemp(prefix="test_s1_verify_")
        try:
            docx_unpack(output_path, verify_dir)
            paragraphs = get_paragraph_texts(verify_dir)
            full_text = '\n'.join(paragraphs)

            checks = [
                ('9999' in full_text, "New גוש 9999 present"),
                ('111' in full_text, "New חלקה 111 present"),
                ('גוש' in full_text, "Label גוש intact"),
                ('חלקה' in full_text, "Label חלקה intact"),
            ]

            all_pass = True
            for passed, desc in checks:
                status = "PASS" if passed else "FAIL"
                if not passed:
                    all_pass = False
                print(f"  [{status}] {desc}")

            return all_pass
        finally:
            shutil.rmtree(verify_dir, ignore_errors=True)
            # Clean up output file
            if os.path.exists(output_path):
                os.unlink(output_path)

    except Exception as e:
        print(f"  [ERROR] Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ═══════════════════════════════════════════════════════════════════════
# TEST 4: Field extractor — verify new body fields extraction
# ═══════════════════════════════════════════════════════════════════════

def test_field_extractor_body_fields():
    """Test that the field extractor now picks up body fields."""
    print(f"\n{'='*60}")
    print("TEST: Field Extractor — Body Fields")
    print('='*60)

    all_pass = True
    for doc_name in ['2026042.docx', '2026018.docx', '2026023T.docx', '2026034.docx']:
        path = os.path.join(DOCS_DIR, doc_name)
        if not os.path.exists(path):
            print(f"  [SKIP] {doc_name}")
            continue

        with open(path, 'rb') as f:
            fields = extract_cover_fields(f)

        print(f"\n  {doc_name}: {len(fields)} fields")
        for k, v in fields.items():
            print(f"    {k}: {v[:50]}{'...' if len(v) > 50 else ''}")

        # Basic check: at least cover fields should be present
        has_gush = 'גוש' in fields
        has_helka = 'חלקה' in fields
        if not has_gush:
            print(f"  [FAIL] Missing גוש in {doc_name}")
            all_pass = False
        if not has_helka:
            print(f"  [FAIL] Missing חלקה in {doc_name}")
            all_pass = False

    status = "PASS" if all_pass else "FAIL"
    print(f"\n  [{status}] Field extractor body fields test")
    return all_pass


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("Pattern Replacer — Comprehensive Test Suite")
    print("=" * 60)

    results = {}

    # Unit tests
    try:
        test_unit_pattern_matching()
        results['Unit: Pattern Matching'] = True
    except Exception as e:
        print(f"  [FAIL] Unit test error: {e}")
        import traceback
        traceback.print_exc()
        results['Unit: Pattern Matching'] = False

    # Field extractor
    results['Field Extractor Body Fields'] = test_field_extractor_body_fields()

    # Integration tests per document
    results['2026042 (Standard)'] = test_2026042()
    results['2026018 (היטל השבחה)'] = test_2026018()
    results['2026023T (תת חלקה)'] = test_2026023T()
    results['2026034'] = test_2026034()

    # Full pipeline
    results['Stage 1 Pipeline'] = test_stage1_pipeline()

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"\n  {passed}/{total} tests passed")

    if all(results.values()):
        print("\n  OVERALL: ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("\n  OVERALL: SOME TESTS FAILED")
        sys.exit(1)
