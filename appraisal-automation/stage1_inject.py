"""
stage1_inject.py
Stage 1: Dynamic field extraction + global find-and-replace across DOCX.

Flow:
    1. User uploads template DOCX
    2. extract_cover_fields() → dynamic label:value dict
    3. User confirms/edits in Streamlit (app.py does this)
    4. run_stage1(file_obj, confirmed_fields) → output file path + replacement summary

Does NOT chain to Stage 2. Appraiser works on the document manually between stages.
"""
import os
import io
import re
import tempfile
import shutil

from config import TEMP_DIR, STAGE1_SUFFIX
from docx_utils import docx_unpack, docx_pack, replace_throughout_document
from field_extractor import extract_cover_fields

# Minimum safe lengths for global replacement.
# Values shorter than these are replaced only in known label patterns.
MIN_NUMERIC_LENGTH = 2   # single digits like "2" are too dangerous globally
MIN_TEXT_LENGTH    = 2   # single Hebrew letters are too dangerous globally

# Labels whose values are commonly single-digit — replace ONLY in "label: value" patterns
PATTERN_ONLY_LABELS = {"תת חלקה", "תת-חלקה"}


def run_stage1(file_obj, confirmed_fields: dict[str, str]) -> tuple[str, dict[str, int]]:
    """
    Execute Stage 1 pipeline.

    Args:
        file_obj:          Streamlit UploadedFile or file-like object.
        confirmed_fields:  {label: new_value} after user confirmation in the UI.
                           This is what the appraiser typed — NOT necessarily the
                           same as what was in the original document.

    Returns:
        (output_docx_path, replacement_counts)
        replacement_counts = {old_value: total_occurrences_replaced}
    """
    # ── Save upload to temp file ───────────────────────────────────────────────
    original_name = _get_original_name(file_obj)
    with tempfile.NamedTemporaryFile(
        dir=TEMP_DIR, suffix=".docx", delete=False
    ) as tmp:
        tmp.write(_read_bytes(file_obj))
        src_path = tmp.name

    # ── Re-extract the ORIGINAL values from the uploaded document ─────────────
    # This is critical: the replace map must be {old_value → new_value}.
    # We need to know what WAS in the doc (old_value) to find it in the XML.
    with open(src_path, "rb") as f:
        extracted_fields = extract_cover_fields(f)

    # ── Unpack ────────────────────────────────────────────────────────────────
    unpack_dir = src_path.replace(".docx", "_unpacked")
    docx_unpack(src_path, unpack_dir)

    # ── Build replacement map: {old_value → new_value} ────────────────────────
    #
    # CORRECT LOGIC:
    #   extracted_fields[label] = old_value  (what was in the template)
    #   confirmed_fields[label] = new_value  (what the user typed)
    #   replacements[old_value] = new_value
    #
    # Labels (e.g. "גוש", "חלקה") are NEVER in the replacement dict.
    # Only VALUES (e.g. "6854", "הועדה המקומית שוהם") are replaced.

    replacements: dict[str, str] = {}
    pattern_replacements: dict[str, str] = {}  # full "label: old" → "label: new"

    for label in extracted_fields:
        old_value = extracted_fields[label].strip()
        new_value = confirmed_fields.get(label, "").strip()

        # Skip: nothing changed, or new value is empty/EMPTY
        if not old_value or not new_value:
            continue
        if old_value == new_value:
            continue
        if new_value in ("EMPTY", "⚠️ EMPTY"):
            continue

        # Special case: labels whose values are typically single digits
        # Replace only in "label: value" pattern, not globally
        if label in PATTERN_ONLY_LABELS:
            for sep in (": ", " "):
                pattern_old = f"{label}{sep}{old_value}"
                pattern_new = f"{label}{sep}{new_value}"
                pattern_replacements[pattern_old] = pattern_new
            continue

        # Skip values that are too short to safely replace globally
        if old_value.isdigit() and len(old_value) < MIN_NUMERIC_LENGTH:
            # Still do pattern replacement for safety
            for sep in (": ", " "):
                pattern_old = f"{label}{sep}{old_value}"
                pattern_new = f"{label}{sep}{new_value}"
                pattern_replacements[pattern_old] = pattern_new
            continue

        if len(old_value) < MIN_TEXT_LENGTH:
            # Exception: allow blank placeholder sequences like '____', '_____' etc.
            # These are template placeholders that should always be replaced.
            if not re.fullmatch(r'_+', old_value):
                continue

        replacements[old_value] = new_value

    # Merge pattern replacements in (these go LONGEST FIRST by default since
    # they're longer strings — handled inside replace_throughout_document)
    replacements.update(pattern_replacements)

    # ── Execute replacement ───────────────────────────────────────────────────
    total_counts = replace_throughout_document(unpack_dir, replacements)

    # ── Remove unfilled blank lines after replacement ────────────────────────
    # Lines that still contain only underscores are unfilled template slots — remove them.
    _remove_unfilled_blank_lines(unpack_dir)

    # ── Remap counts back to labels for the UI summary ────────────────────────
    # The UI shows "label (old_value): N locations" — so invert the mapping.
    label_counts: dict[str, int] = {}
    for label in extracted_fields:
        old_value = extracted_fields[label].strip()
        new_value = confirmed_fields.get(label, "").strip()
        count = total_counts.get(old_value, 0)
        # Also count any pattern replacements for this label
        for sep in (": ", " "):
            pat = f"{label}{sep}{old_value}"
            count += total_counts.get(pat, 0)
        if count > 0:
            label_counts[label] = count

    # ── Repack ───────────────────────────────────────────────────────────────
    base_name = _stem(original_name) + STAGE1_SUFFIX + ".docx"
    output_path = os.path.join(TEMP_DIR, base_name)
    docx_pack(unpack_dir, output_path)

    # ── Cleanup temp unpack dir ───────────────────────────────────────────────
    shutil.rmtree(unpack_dir, ignore_errors=True)
    os.unlink(src_path)

    return output_path, label_counts


def _remove_unfilled_blank_lines(unpacked_dir: str) -> None:
    """
    Delete paragraphs from document.xml whose entire text content consists
    only of underscores (_____) — these are unfilled template placeholders.

    Uses lxml for safe XML editing. Only modifies word/document.xml.
    """
    from lxml import etree

    doc_path = os.path.join(unpacked_dir, "word", "document.xml")
    if not os.path.exists(doc_path):
        return

    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    W    = f"{{{W_NS}}}"

    tree = etree.parse(doc_path)
    root = tree.getroot()

    # Regex: line whose stripped text is ONLY underscores (1 or more)
    _BLANK_ONLY = re.compile(r'^_+$')

    paragraphs_to_remove = []
    for para in root.iter(f"{W}p"):
        # Collect all text in this paragraph
        parts = [t_el.text or "" for t_el in para.iter(f"{W}t")]
        full_text = "".join(parts).strip()
        if full_text and _BLANK_ONLY.fullmatch(full_text):
            paragraphs_to_remove.append(para)

    for para in paragraphs_to_remove:
        parent = para.getparent()
        if parent is not None:
            parent.remove(para)

    with open(doc_path, "wb") as f:
        tree.write(f, xml_declaration=True, encoding="UTF-8", standalone=True)


def _get_original_name(file_obj) -> str:
    """Extract original filename from file object."""
    if hasattr(file_obj, "name"):
        return os.path.basename(file_obj.name)
    return "report.docx"


def _stem(filename: str) -> str:
    """Return filename without extension."""
    base = os.path.basename(filename)
    return os.path.splitext(base)[0]


def _read_bytes(file_obj) -> bytes:
    """Read bytes from file-like object, resetting position if possible."""
    if hasattr(file_obj, "read"):
        data = file_obj.read()
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        return data
    with open(file_obj, "rb") as f:
        return f.read()
