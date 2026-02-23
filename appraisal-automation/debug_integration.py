"""
debug_integration.py — Check where 6854 appears in the output document
"""
import sys, os, shutil
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from stage1_inject import run_stage1
from docx_utils import get_paragraph_texts, docx_unpack
from config import TEMP_DIR

DOCS_DIR = r'c:\Users\Amit\Documents\anitgravity\rami project final'
docx_path = os.path.join(DOCS_DIR, "2026023T.docx")

confirmed_fields = {
    'גוש':          '7777',
    'חלקה':         '77',
    'תת חלקה':      '7',
    'מזמין השומה':  'הועדה המקומית שוהם',
    'המבקשים':      'יוחאי פנחס פרסר',
    'סלע/כניסה':    "הסלע 1 כניסה ב'",
    'שכונה':        'ורדים',
    'עיר':          'שוהם',
}

with open(docx_path, 'rb') as f:
    output_path, label_counts = run_stage1(f, confirmed_fields)

print("Output:", output_path)
print("Label counts:", label_counts)

unpack_dir = output_path.replace('.docx', '_debug_unpack')
try:
    docx_unpack(output_path, unpack_dir)
    paragraphs = get_paragraph_texts(unpack_dir)
    print("\n--- Lines containing 6854 ---")
    for i, p in enumerate(paragraphs):
        if '6854' in p:
            print(f"  para {i}: {repr(p[:120])}")
    print("\n--- Cover page (first 10 non-empty paragraphs) ---")
    shown = 0
    for i, p in enumerate(paragraphs):
        if p.strip():
            print(f"  para {i}: {repr(p)}")
            shown += 1
            if shown >= 10:
                break
finally:
    shutil.rmtree(unpack_dir, ignore_errors=True)
