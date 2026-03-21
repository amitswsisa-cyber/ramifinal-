"""
inline_injector.py
Orchestrator for injecting AI review findings as inline "markered" paragraphs
directly into document.xml.

Instead of side bubbles (comments), this inserts a new paragraph immediately
under the paragraph it reviews, matching the document's font style.
"""
import os
import logging
from lxml import etree
from copy import deepcopy
from docx_utils import get_paragraph_texts

logger = logging.getLogger(__name__)

# ── Namespaces ────────────────────────────────────────────────────────────────
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"

# ── Category to Hebrew labels ───────────────────────────────────────────────
CATEGORY_LABELS: dict[str, str] = {
    "logic":       "לוגיקה",
    "missing":     "חסר",
    "spelling":    "שגיאת כתיב",
    "phrasing":    "ניסוח",
    "punctuation": "פיסוק",
    "merged_review": "ביקורת",
}

def format_inline_text(finding: dict) -> str:
    """Build the text content for the inline marker."""
    category = finding.get("category", "logic")
    label = CATEGORY_LABELS.get(category, "הערת AI")
    comment_body = finding.get("comment", "")
    
    # Make the category label the very first thing the user sees
    text = f"[{label}] {comment_body}"
    
    suggestion = finding.get("suggestion")
    if suggestion:
        text += f" | הצעה: {suggestion}"
        
    return text

def inject_inline_reviews(unpacked_dir: str, findings: list[dict]) -> int:
    """
    Inject findings as inline paragraphs in document.xml.
    Returns the number of markers injected.
    """
    if not findings:
        return 0

    word_dir = os.path.join(unpacked_dir, "word")
    doc_path = os.path.join(word_dir, "document.xml")

    if not os.path.exists(doc_path):
        logger.error(f"document.xml not found at {doc_path}")
        return 0

    # 1. Deduplicate findings (same paragraph and comment)
    seen = set()
    deduped = []
    for f in findings:
        key = (f.get("paragraph_index", 0), f.get("comment", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(f)

    # 2. Parse document.xml
    parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(doc_path, parser)
    root = tree.getroot()
    body = root.find(f"{W}body")
    
    if body is None:
        logger.error("Could not find <body> in document.xml")
        return 0

    all_paras = list(body.iter(f"{W}p"))
    total_paras = len(all_paras)

    # 3. Sort findings by paragraph index in REVERSE order
    # (So that inserting paragraphs doesn't shift the indices of paragraphs we still need to process)
    sorted_findings = sorted(deduped, key=lambda x: x.get("paragraph_index", 0), reverse=True)

    injected_count = 0
    for finding in sorted_findings:
        para_idx = finding.get("paragraph_index", 0)
        
        if para_idx < 0 or para_idx >= total_paras:
            continue
            
        target_para = all_paras[para_idx]
        
        # Create new AI Marker paragraph
        new_para = etree.Element(f"{W}p")
        
        # Copy paragraph properties (pPr) from target to match style/alignment
        target_pPr = target_para.find(f"{W}pPr")
        if target_pPr is not None:
            new_pPr = deepcopy(target_pPr)
            # Optional: Ensure it's not a heading if the original was
            new_para.append(new_pPr)

        # Create Run
        run = etree.SubElement(new_para, f"{W}r")
        
        # Create Run Properties (rPr) for formatting
        rPr = etree.SubElement(run, f"{W}rPr")
        
        # Copy size from target's first run, but skip fonts (they may not support Hebrew)
        first_r = target_para.find(f"{W}r")
        if first_r is not None:
            target_rPr = first_r.find(f"{W}rPr")
            if target_rPr is not None:
                for child in target_rPr:
                    tag = child.tag
                    # Skip fonts (may be Symbol/Math), highlight (we add our own),
                    # and cs/rtl overrides (we set our own below)
                    if tag not in (f"{W}rFonts", f"{W}highlight"):
                        rPr.append(deepcopy(child))

        # Force a Hebrew-compatible font for the marker text
        rFonts = etree.SubElement(rPr, f"{W}rFonts")
        rFonts.set(f"{W}cs", "David")
        rFonts.set(f"{W}ascii", "David")
        rFonts.set(f"{W}hAnsi", "David")

        # Add "Marker" effect (Yellow Highlight)
        highlight = etree.SubElement(rPr, f"{W}highlight")
        highlight.set(f"{W}val", "yellow")
        
        # Add Text
        t = etree.SubElement(run, f"{W}t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = format_inline_text(finding)
        
        # Insert AFTER the target paragraph
        target_para.addnext(new_para)
        injected_count += 1

    # Write back
    tree.write(doc_path, xml_declaration=True, encoding="UTF-8", standalone=True)
    
    return injected_count
