"""
test_extractor.py — Integration test for field_extractor.py
Run: python test_extractor.py
"""
import sys
import importlib
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

import field_extractor
importlib.reload(field_extractor)
from field_extractor import extract_cover_fields, detect_document_type

DOCS_DIR = r'c:\Users\Amit\Documents\anitgravity\rami project final'

# ── Expected outputs per spec ─────────────────────────────────────────────────

EXPECTED_A = {
    'גוש':           '6623',
    'חלקה':          '458',
    'רחוב':          'אשכנזי 80',
    'עיר':           'תל אביב',
    'מזמין השומה':   'הועדה המקומית תל אביב',
    'מספר תיק':      '2025-12005',
}

EXPECTED_B = {
    'גוש':           '6854',
    'חלקה':          '41',
    'תת חלקה':       '2',
    'סלע/כניסה':     "הסלע 1 כניסה ב'",
    'שכונה':         'ורדים',
    'עיר':           'שוהם',
    'מזמין השומה':   'הועדה המקומית שוהם',
    'המבקשים':       'יוחאי פנחס פרסר',
}


def run_test(filepath: str, expected: dict[str, str], label: str) -> bool:
    print(f'\n{"="*60}')
    print(f'TEST: {label}')
    print(f'File: {filepath}')
    print('='*60)

    with open(filepath, 'rb') as f:
        fields = extract_cover_fields(f)
        f.seek(0)
        doc_type = detect_document_type(f)

    print(f'Document type detected: {doc_type}')
    print(f'Total fields extracted: {len(fields)}')
    print('\nExtracted fields:')
    for k, v in fields.items():
        print(f'  {repr(k)}: {repr(v)}')

    print('\nVerification:')
    all_pass = True
    for key, expected_val in expected.items():
        got = fields.get(key, 'MISSING')
        ok = (got == expected_val)
        if not ok:
            all_pass = False
        status = 'PASS' if ok else f'FAIL  got={repr(got)}  expected={repr(expected_val)}'
        print(f'  [{key}]: {status}')

    # Check for unexpected extra fields (warn, not fail)
    extra = set(fields.keys()) - set(expected.keys())
    if extra:
        print(f'\n  (Extra fields not in expected spec: {extra})')

    result = 'ALL PASS' if all_pass else 'SOME FAILURES'
    print(f'\n{label}: {result}')
    return all_pass


if __name__ == '__main__':
    pass_a = run_test(
        filepath=f'{DOCS_DIR}\\2026018.docx',
        expected=EXPECTED_A,
        label='TYPE A — Standard (2026018.docx)',
    )

    pass_b = run_test(
        filepath=f'{DOCS_DIR}\\2026023T.docx',
        expected=EXPECTED_B,
        label='TYPE B/C — Correction/Betterment (2026023T.docx)',
    )

    print('\n' + '='*60)
    if pass_a and pass_b:
        print('OVERALL: ALL TESTS PASSED')
        sys.exit(0)
    else:
        print('OVERALL: SOME TESTS FAILED')
        sys.exit(1)
