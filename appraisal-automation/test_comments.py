"""
test_comments.py — Full test of comment injection + XML validation.
Injects 3 test comments into a real document and verifies:
  1. XML is well-formed after injection
  2. comments.xml has correct structure
  3. document.xml has markers INSIDE <w:p>, not at body level
  4. [Content_Types].xml has comments override
  5. document.xml.rels has comments relationship
  6. Repacked DOCX is valid
"""
import sys, os, shutil
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from lxml import etree
from docx_utils import docx_unpack, docx_pack_safe, validate_unpacked_docx
from comment_injector import inject_all_comments

DOCS_DIR = r'c:\Users\Amit\Documents\anitgravity\rami project final'
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W    = f"{{{W_NS}}}"


def test_comment_injection():
    docx_path = os.path.join(DOCS_DIR, "2026023T.docx")
    if not os.path.exists(docx_path):
        print("SKIP: Test document not found")
        return

    # Unpack into a test directory
    test_dir = os.path.join(DOCS_DIR, "appraisal-automation", "_temp", "_comment_test")
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
    docx_unpack(docx_path, test_dir)

    # Inject 3 test comments
    test_findings = [
        {
            "paragraph_index": 2,
            "category": "logic",
            "severity": "high",
            "comment": "סתירה בנתוני שטח — 77.43 בטבלה לעומת 69.53 בסעיף 5",
            "suggestion": None,
        },
        {
            "paragraph_index": 5,
            "category": "spelling",
            "severity": "low",
            "comment": "שגיאות כתיב: 'השיבה' → 'השבה', 'הגבה' → 'הגבהה'",
            "suggestion": None,
        },
        {
            "paragraph_index": 10,
            "category": "phrasing",
            "severity": "medium",
            "comment": "ניסוח עמום שעלול ליצור חשיפה משפטית",
            "suggestion": "הנכס הנדון הועבר לבעלות המבקש בשנת 2021 על פי נסח הטאבו.",
        },
    ]

    injected = inject_all_comments(test_dir, test_findings)
    print(f"Injected {injected} comments")

    # ── Check 1: XML well-formedness ──────────────────────────────────────
    errors = validate_unpacked_docx(test_dir)
    if errors:
        for e in errors:
            print(f"  XML ERROR: {e}")
        print("[FAIL] XML validation failed")
        return
    print("[PASS] All XML files are well-formed")

    # ── Check 2: comments.xml has 3 <w:comment> elements ─────────────────
    comments_path = os.path.join(test_dir, "word", "comments.xml")
    assert os.path.exists(comments_path), "comments.xml missing!"
    tree = etree.parse(comments_path)
    root = tree.getroot()
    comment_els = root.findall(f"{W}comment")
    assert len(comment_els) == 3, f"Expected 3 comments, got {len(comment_els)}"
    print(f"[PASS] comments.xml has {len(comment_els)} <w:comment> elements")

    # Verify IDs are 0, 1, 2
    ids = sorted(int(c.get(f"{W}id", -1)) for c in comment_els)
    assert ids == [0, 1, 2], f"Comment IDs wrong: {ids}"
    print(f"[PASS] Comment IDs are correct: {ids}")

    # ── Check 3: document.xml markers are INSIDE <w:p> ────────────────────
    doc_path = os.path.join(test_dir, "word", "document.xml")
    doc_tree = etree.parse(doc_path)
    doc_root = doc_tree.getroot()

    # commentRangeStart must have <w:p> as parent, not <w:body>
    for rs in doc_root.iter(f"{W}commentRangeStart"):
        parent_tag = rs.getparent().tag
        assert parent_tag == f"{W}p", \
            f"commentRangeStart parent is {parent_tag}, expected w:p!"
    print("[PASS] All commentRangeStart are INSIDE <w:p>")

    for re_el in doc_root.iter(f"{W}commentRangeEnd"):
        parent_tag = re_el.getparent().tag
        assert parent_tag == f"{W}p", \
            f"commentRangeEnd parent is {parent_tag}, expected w:p!"
    print("[PASS] All commentRangeEnd are INSIDE <w:p>")

    for cr in doc_root.iter(f"{W}commentReference"):
        # commentReference should be inside <w:r> which is inside <w:p>
        run_parent = cr.getparent()
        assert run_parent.tag == f"{W}r", \
            f"commentReference parent is {run_parent.tag}, expected w:r!"
        para_parent = run_parent.getparent()
        assert para_parent.tag == f"{W}p", \
            f"commentReference grandparent is {para_parent.tag}, expected w:p!"
    print("[PASS] All commentReference are inside <w:r> inside <w:p>")

    # ── Check 4: [Content_Types].xml has override ─────────────────────────
    ct_path = os.path.join(test_dir, "[Content_Types].xml")
    ct_tree = etree.parse(ct_path)
    ct_root = ct_tree.getroot()
    has_override = any(
        el.get("PartName") == "/word/comments.xml" for el in ct_root
    )
    assert has_override, "[Content_Types].xml missing comments.xml override!"
    print("[PASS] [Content_Types].xml has comments.xml override")

    # ── Check 5: document.xml.rels has relationship ───────────────────────
    rels_path = os.path.join(test_dir, "word", "_rels", "document.xml.rels")
    rels_tree = etree.parse(rels_path)
    rels_root = rels_tree.getroot()
    has_rel = any(
        rel.get("Target") == "comments.xml" for rel in rels_root
    )
    assert has_rel, "document.xml.rels missing comments relationship!"
    print("[PASS] document.xml.rels has comments relationship")

    # ── Check 6: Repack with validation ───────────────────────────────────
    output_path = os.path.join(
        DOCS_DIR, "appraisal-automation", "_temp", "comment_test_output.docx"
    )
    try:
        docx_pack_safe(test_dir, output_path)
        print(f"[PASS] Repacked successfully: {output_path}")
        print(f"       Size: {os.path.getsize(output_path):,} bytes")
    except ValueError as e:
        print(f"[FAIL] Repack failed: {e}")

    # Cleanup
    shutil.rmtree(test_dir, ignore_errors=True)

    print("\n" + "=" * 50)
    print("ALL CHECKS PASSED — DOCX should open in Word")
    print("=" * 50)


if __name__ == "__main__":
    test_comment_injection()
