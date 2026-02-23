"""
scripts/office/comment.py
Inject Word comments into an unpacked DOCX directory.

OOXML spec for comments requires 4 coordinated XML files:
  1. word/comments.xml          — <w:comment> body elements
  2. word/document.xml          — per-paragraph markers (inside <w:p>)
  3. [Content_Types].xml        — Override for comments.xml content type
  4. word/_rels/document.xml.rels — Relationship entry

CRITICAL STRUCTURE (inside <w:p>):
    <w:commentRangeStart w:id="N"/>     ← SIBLING of <w:r>, CHILD of <w:p>
    <w:r>...original runs...</w:r>
    <w:commentRangeEnd w:id="N"/>       ← SIBLING of <w:r>, CHILD of <w:p>
    <w:r>                               ← reference run, CHILD of <w:p>
      <w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>
      <w:commentReference w:id="N"/>
    </w:r>

These MUST be children of <w:p>, NEVER siblings of <w:p> at body level.
"""
import sys
import os
import argparse
from lxml import etree

# ── Namespaces ────────────────────────────────────────────────────────────────
W_NS   = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
R_NS   = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT_NS  = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

W   = f"{{{W_NS}}}"
W14 = f"{{{W14_NS}}}"

COMMENT_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
)
COMMENT_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
)


# ── Batch injection API ──────────────────────────────────────────────────────

def inject_comments_batch(
    unpacked_dir: str,
    comments: list[dict],
    author: str = "רמי סויצקי",
) -> int:
    """
    Inject multiple comments in a SINGLE pass.

    Args:
        unpacked_dir: Path to unpacked DOCX directory.
        comments:     List of dicts, each with:
                        - comment_id: int
                        - para_index: int
                        - text: str
        author:       Comment author name.

    Returns:
        Number of comments injected.
    """
    word_dir = os.path.join(unpacked_dir, "word")
    doc_path = os.path.join(word_dir, "document.xml")

    if not os.path.exists(doc_path):
        raise FileNotFoundError(f"document.xml not found at {doc_path}")

    # ── Step 1: Create/update comments.xml ────────────────────────────────
    comments_path = _ensure_comments_xml(word_dir)
    _add_all_comments_to_xml(comments_path, comments, author)

    # ── Step 2: Ensure relationship + content type ────────────────────────
    _ensure_comments_relationship(word_dir)
    _ensure_content_type(unpacked_dir)

    # ── Step 3: Inject markers into document.xml — single parse/write ─────
    _inject_all_markers(doc_path, comments)

    return len(comments)


def inject_comment(
    unpacked_dir: str,
    comment_id: int,
    text: str,
    author: str = "רמי סויצקי",
    para_index: int = 0,
) -> None:
    """
    Legacy single-comment API.
    Delegates to inject_comments_batch for a single item.
    """
    inject_comments_batch(
        unpacked_dir,
        [{"comment_id": comment_id, "para_index": para_index, "text": text}],
        author=author,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ensure_comments_xml(word_dir: str) -> str:
    """Create word/comments.xml if it does not exist. Return its path."""
    path = os.path.join(word_dir, "comments.xml")
    if not os.path.exists(path):
        root = etree.Element(
            f"{W}comments",
            nsmap={"w": W_NS, "w14": W14_NS},
        )
        tree = etree.ElementTree(root)
        tree.write(path, xml_declaration=True, encoding="UTF-8", standalone=True)
    return path


def _add_all_comments_to_xml(
    comments_path: str, comments: list[dict], author: str
) -> None:
    """Append all <w:comment> elements to comments.xml in one pass."""
    tree = etree.parse(comments_path)
    root = tree.getroot()

    for c in comments:
        cid  = c["comment_id"]
        text = c["text"]

        comment_el = etree.SubElement(root, f"{W}comment")
        comment_el.set(f"{W}id", str(cid))
        comment_el.set(f"{W}author", author)
        comment_el.set(f"{W}date", "2026-02-19T00:00:00Z")
        comment_el.set(f"{W}initials", author[0] if author else "A")

        # Comment body paragraph
        para = etree.SubElement(comment_el, f"{W}p")
        run  = etree.SubElement(para, f"{W}r")

        rpr    = etree.SubElement(run, f"{W}rPr")
        rStyle = etree.SubElement(rpr, f"{W}rStyle")
        rStyle.set(f"{W}val", "CommentText")

        t = etree.SubElement(run, f"{W}t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = text

    tree.write(comments_path, xml_declaration=True, encoding="UTF-8", standalone=True)


def _ensure_comments_relationship(word_dir: str) -> None:
    """Add comments relationship to word/_rels/document.xml.rels if missing."""
    rels_dir  = os.path.join(word_dir, "_rels")
    rels_path = os.path.join(rels_dir, "document.xml.rels")
    os.makedirs(rels_dir, exist_ok=True)

    if not os.path.exists(rels_path):
        root = etree.Element("Relationships", xmlns=REL_NS)
        tree = etree.ElementTree(root)
        tree.write(rels_path, xml_declaration=True, encoding="UTF-8", standalone=True)

    tree = etree.parse(rels_path)
    root = tree.getroot()

    # Check if comments relationship already exists
    for rel in root:
        if rel.get("Type") == COMMENT_REL_TYPE:
            return  # Already present

    # Add it — use a unique rId that won't clash
    existing_ids = {rel.get("Id", "") for rel in root}
    rid = "rIdComments"
    counter = 1
    while rid in existing_ids:
        rid = f"rIdComments{counter}"
        counter += 1

    rel_el = etree.SubElement(root, "Relationship")
    rel_el.set("Id", rid)
    rel_el.set("Type", COMMENT_REL_TYPE)
    rel_el.set("Target", "comments.xml")

    tree.write(rels_path, xml_declaration=True, encoding="UTF-8", standalone=True)


def _ensure_content_type(unpacked_dir: str) -> None:
    """Add comments.xml Override to [Content_Types].xml if missing."""
    ct_path = os.path.join(unpacked_dir, "[Content_Types].xml")
    if not os.path.exists(ct_path):
        return

    tree = etree.parse(ct_path)
    root = tree.getroot()

    # Check existing overrides
    for el in root:
        if el.get("PartName") == "/word/comments.xml":
            return  # Already present

    override = etree.SubElement(root, "Override")
    override.set("PartName", "/word/comments.xml")
    override.set("ContentType", COMMENT_CONTENT_TYPE)

    tree.write(ct_path, xml_declaration=True, encoding="UTF-8", standalone=True)


def _inject_all_markers(doc_path: str, comments: list[dict]) -> None:
    """
    Insert commentRangeStart/End + commentReference markers
    INSIDE the target <w:p> elements — single parse/write cycle.

    CRITICAL: All three elements are children of <w:p>, not siblings of it.

    Structure after injection:
        <w:p>
          <w:pPr>...</w:pPr>                ← untouched
          <w:commentRangeStart w:id="N"/>   ← inserted first child after pPr
          <w:r>...original runs...</w:r>     ← untouched
          <w:commentRangeEnd w:id="N"/>     ← appended
          <w:r>                             ← reference run, appended
            <w:rPr>
              <w:rStyle w:val="CommentReference"/>
            </w:rPr>
            <w:commentReference w:id="N"/>
          </w:r>
        </w:p>
    """
    tree = etree.parse(doc_path)
    root = tree.getroot()

    # Collect all <w:p> elements in document order
    all_paras = list(root.iter(f"{W}p"))
    total_paras = len(all_paras)

    # Group comments by paragraph index
    for c in comments:
        cid       = c["comment_id"]
        para_idx  = c["para_index"]

        # Clamp to valid range
        if para_idx < 0:
            para_idx = 0
        if para_idx >= total_paras:
            para_idx = total_paras - 1

        para = all_paras[para_idx]

        # Find insertion point: after <w:pPr> if present, otherwise at position 0
        insert_pos = 0
        for i, child in enumerate(para):
            if child.tag == f"{W}pPr":
                insert_pos = i + 1
                break

        # 1. <w:commentRangeStart> — insert right after pPr (or at start)
        range_start = etree.Element(f"{W}commentRangeStart")
        range_start.set(f"{W}id", str(cid))
        para.insert(insert_pos, range_start)

        # 2. <w:commentRangeEnd> — append at end of paragraph
        range_end = etree.Element(f"{W}commentRangeEnd")
        range_end.set(f"{W}id", str(cid))
        para.append(range_end)

        # 3. <w:r> with commentReference — append after range end
        ref_run = etree.SubElement(para, f"{W}r")
        rpr     = etree.SubElement(ref_run, f"{W}rPr")
        rStyle  = etree.SubElement(rpr, f"{W}rStyle")
        rStyle.set(f"{W}val", "CommentReference")
        comment_ref = etree.SubElement(ref_run, f"{W}commentReference")
        comment_ref.set(f"{W}id", str(cid))

    tree.write(doc_path, xml_declaration=True, encoding="UTF-8", standalone=True)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Inject a Word comment into an unpacked DOCX"
    )
    parser.add_argument("unpacked_dir", help="Path to unpacked DOCX directory")
    parser.add_argument("comment_id",  type=int, help="Unique comment ID (integer)")
    parser.add_argument("text",        help="Comment text")
    parser.add_argument("--author",    default="רמי סויצקי", help="Comment author name")
    parser.add_argument(
        "--para-index", type=int, default=0, dest="para_index",
        help="0-based paragraph index to attach comment to",
    )
    args = parser.parse_args()

    inject_comment(
        args.unpacked_dir,
        args.comment_id,
        args.text,
        args.author,
        args.para_index,
    )
    print(f"✅ Comment {args.comment_id} injected at paragraph {args.para_index}")
