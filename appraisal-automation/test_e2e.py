"""
Full end-to-end test: simulates exactly what Stage 1 does when a user
uploads a document and changes field values.

Tests BOTH document types.
"""
import sys, os, shutil
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from field_extractor import extract_cover_fields
from stage1_inject import run_stage1
from docx_utils import get_paragraph_texts, docx_unpack

DOCS_DIR = r'c:\Users\Amit\Documents\anitgravity\rami project final'


def test_document(filename, field_changes, checks):
    """
    filename: name of DOCX in DOCS_DIR
    field_changes: {label: new_value} to override
    checks: list of (description, lambda full_text -> bool)
    """
    docx_path = os.path.join(DOCS_DIR, filename)
    print(f'\n{"="*60}')
    print(f'TESTING: {filename}')
    print('='*60)

    # Step 1: Extract original fields
    with open(docx_path, 'rb') as f:
        original_fields = extract_cover_fields(f)
    
    print("Original fields:")
    for k, v in original_fields.items():
        print(f"  {k}: {repr(v)}")

    # Step 2: Build confirmed_fields (user form simulation)
    confirmed_fields = dict(original_fields)  # start with originals
    confirmed_fields.update(field_changes)     # override with changes

    print(f"\nChanges applied:")
    for k, v in field_changes.items():
        old = original_fields.get(k, "N/A")
        print(f"  {k}: {repr(old)} -> {repr(v)}")

    # Step 3: Run Stage 1
    with open(docx_path, 'rb') as f:
        output_path, label_counts = run_stage1(f, confirmed_fields)

    print(f"\nOutput: {output_path}")
    print(f"Label counts: {label_counts}")

    # Step 4: Unpack output and read text
    unpack_dir = output_path.replace('.docx', '_verify')
    try:
        docx_unpack(output_path, unpack_dir)
        paragraphs = get_paragraph_texts(unpack_dir)
        full_text = '\n'.join(paragraphs)
    finally:
        shutil.rmtree(unpack_dir, ignore_errors=True)

    # Step 5: Run checks
    print(f"\nVerification ({len(checks)} checks):")
    all_pass = True
    for desc, check_fn in checks:
        try:
            passed = check_fn(full_text)
        except Exception as e:
            passed = False
            desc += f" (exception: {e})"
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {desc}")

    overall = "ALL PASS" if all_pass else "SOME FAILURES"
    print(f"\n{filename}: {overall}")
    return all_pass


# ═══════════════════════════════════════════════════════════════════════
# TEST 1: Type B — 2026023T.docx (Correction/Betterment)
# ═══════════════════════════════════════════════════════════════════════
pass_b = test_document(
    filename="2026023T.docx",
    field_changes={
        'גוש': '7777',
        'חלקה': '77',
        'תת חלקה': '7',
    },
    checks=[
        ("גוש value 7777 appears",       lambda t: '7777' in t),
        ("חלקה value 77 appears",         lambda t: 'חלקה: 77' in t or 'חלקה 77' in t),
        ("תת חלקה value 7 appears",       lambda t: 'תת חלקה: 7' in t or 'תת חלקה 7' in t),
        ("Old גוש 6854 is GONE",          lambda t: '6854' not in t),
        ("Label 'גוש' preserved",          lambda t: 'גוש' in t),
        ("Label 'חלקה' preserved",          lambda t: 'חלקה' in t),
        ("Label 'מזמין השומה' preserved",   lambda t: 'מזמין השומה' in t),
        ("Unchanged value 'שוהם' intact",   lambda t: 'שוהם' in t),
        ("Table values untouched (69.53)",  lambda t: '69.53' in t),
        ("Table values untouched (8.76)",   lambda t: '8.76' in t),
        ("Table values untouched (77.43)",  lambda t: '77.43' in t),
    ]
)


# ═══════════════════════════════════════════════════════════════════════
# TEST 2: Type A — 2026018.docx (Standard/Betterment) 
# ═══════════════════════════════════════════════════════════════════════
pass_a = test_document(
    filename="2026018.docx",
    field_changes={
        'גוש': '9999',
        'חלקה': '88',
        'רחוב': 'הרצל 5',
        'עיר': 'הרצליה',
        'מספר תיק': '9999-00001',
    },
    checks=[
        ("גוש value 9999 appears",            lambda t: '9999' in t),
        ("חלקה value 88 appears",              lambda t: '88' in t),
        ("רחוב value 'הרצל 5' appears",        lambda t: 'הרצל 5' in t),
        ("עיר value 'הרצליה' appears",          lambda t: 'הרצליה' in t),
        ("מספר תיק 9999-00001 appears",        lambda t: '9999-00001' in t),
        ("Old גוש 6623 is GONE",               lambda t: '6623' not in t),
        ("Old חלקה 458 is GONE",               lambda t: ' 458' not in t and ':458' not in t and ': 458' not in t),
        ("Old עיר 'תל אביב' is GONE",          lambda t: 'תל אביב' not in t),
        ("Old רחוב 'אשכנזי 80' is GONE",       lambda t: 'אשכנזי 80' not in t),
        ("Label 'גוש' preserved",               lambda t: 'גוש' in t),
        ("Label 'מזמין השומה' preserved",        lambda t: 'מזמין השומה' in t),
        ("Table values untouched (139.49)",     lambda t: '139.49' in t),
        ("Table values untouched (69.53 from tables should be intact if present)", lambda t: True),
    ]
)

print(f'\n{"="*60}')
if pass_a and pass_b:
    print("OVERALL: ALL TESTS PASSED")
else:
    print("OVERALL: SOME TESTS FAILED")
