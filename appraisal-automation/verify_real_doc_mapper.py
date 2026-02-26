import os
import shutil
import tempfile
from docx_utils import docx_unpack
from section_mapper import SectionMapper

DOCX_PATH = r"c:\Users\Amit\Documents\anitgravity\rami project final\2026018.docx"
TEMP_DIR = os.path.join(tempfile.gettempdir(), "loki_verify_mapper")

def verify_real_doc():
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR)

    print(f"Unpacking {DOCX_PATH}...")
    docx_unpack(DOCX_PATH, TEMP_DIR)

    print("Building section map...")
    mapper = SectionMapper(TEMP_DIR)
    mapper.load()
    mapping = mapper.build_map()

    print("\nFirst 50 paragraphs and their labels:")
    print("-" * 60)
    for i in range(min(50, len(mapper.paragraphs))):
        p = mapper.paragraphs[i]
        label = mapping.get(i, "N/A")
        text_snippet = p["text"][:50].replace("\n", " ")
        print(f"[{i:03d}] {label:<40} | {text_snippet}")

if __name__ == "__main__":
    verify_real_doc()
