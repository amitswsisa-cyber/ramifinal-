"""
scripts/office/unpack.py
Unpack a DOCX file into a directory of XML files.
Merges adjacent <w:r> runs with identical formatting to fix Hebrew split-run issue.

Usage:
    python unpack.py input.docx output_dir/
    # or import and call unpack(src, dst)
"""
import sys
import zipfile
import shutil
import os
from lxml import etree

# Word XML namespaces
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"

WORD_NS = {
    "w": W_NS,
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def _runs_have_same_rpr(run_a: etree._Element, run_b: etree._Element) -> bool:
    """Return True if both runs have identical rPr (or both have none)."""
    rpr_a = run_a.find(f"{W}rPr")
    rpr_b = run_b.find(f"{W}rPr")
    if rpr_a is None and rpr_b is None:
        return True
    if rpr_a is None or rpr_b is None:
        return False
    # Compare serialised XML strings — good-enough for our purposes
    return etree.tostring(rpr_a) == etree.tostring(rpr_b)


def merge_runs_in_paragraph(para: etree._Element) -> None:
    """
    Merge consecutive <w:r> elements that share the same <w:rPr>.
    This repairs the fragmentation that happens when Word tracks revisions
    or the RTL bidi engine inserts mid-word run boundaries.
    """
    runs = para.findall(f"{W}r")
    if len(runs) < 2:
        return

    i = 0
    while i < len(para) - 1:
        child = para[i]
        if child.tag != f"{W}r":
            i += 1
            continue

        next_child = para[i + 1]
        if next_child.tag != f"{W}r":
            i += 1
            continue

        if not _runs_have_same_rpr(child, next_child):
            i += 1
            continue

        # Merge next_child's <w:t> text into child's <w:t>
        t_mine = child.find(f"{W}t")
        t_next = next_child.find(f"{W}t")
        if t_mine is None or t_next is None:
            i += 1
            continue

        # Preserve leading/trailing spaces
        combined = (t_mine.text or "") + (t_next.text or "")
        t_mine.text = combined
        if combined != combined.strip():
            t_mine.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

        # Remove the merged run
        para.remove(next_child)
        # Don't increment i — re-check new next child against same child

    # Recurse into table cells etc.
    for child in para:
        merge_runs_in_paragraph(child)


def merge_runs_in_xml(xml_path: str) -> None:
    """Parse an XML file, merge runs, write back."""
    tree = etree.parse(xml_path)
    root = tree.getroot()
    # Find all paragraphs anywhere in the document
    for para in root.iter(f"{W}p"):
        merge_runs_in_paragraph(para)
    tree.write(xml_path, xml_declaration=True, encoding="UTF-8", standalone=True)


def unpack(src_docx: str, dst_dir: str) -> None:
    """
    Unpack src_docx into dst_dir (created/cleared automatically).
    After extraction, merge runs in all word/*.xml files.
    """
    if os.path.exists(dst_dir):
        shutil.rmtree(dst_dir)
    os.makedirs(dst_dir)

    with zipfile.ZipFile(src_docx, "r") as zf:
        zf.extractall(dst_dir)

    # Merge runs in all Word XML parts
    word_dir = os.path.join(dst_dir, "word")
    if os.path.isdir(word_dir):
        for fname in os.listdir(word_dir):
            if fname.endswith(".xml"):
                merge_runs_in_xml(os.path.join(word_dir, fname))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: unpack.py <input.docx> <output_dir>")
        sys.exit(1)
    unpack(sys.argv[1], sys.argv[2])
    print(f"Unpacked to {sys.argv[2]}")
