"""
docx_utils.py
Shared utilities: unpack/pack wrappers, XML string replacement helpers.

Critical constraints from spec:
 - NEVER touch bidi/rtl/cs attributes
 - Always use xml:space="preserve" on <w:t> with leading/trailing whitespace
 - Numeric partial match protection: "458" must not replace inside "4580"
 - Work at XML text level — NOT python-docx API for editing
"""
import os
import sys
import shutil
import tempfile
from typing import ByteString

# Add scripts to path
_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "scripts", "office")
sys.path.insert(0, _SCRIPTS_DIR)

from unpack import unpack
from pack import pack


def docx_unpack(src_docx: str, dst_dir: str) -> None:
    """Unpack src_docx → dst_dir (merges runs automatically)."""
    unpack(src_docx, dst_dir)


def docx_pack(src_dir: str, dst_docx: str) -> None:
    """Repack src_dir → dst_docx."""
    pack(src_dir, dst_docx)


# ── String replacement helpers ─────────────────────────────────────────────────

# Hebrew unicode block
_HE_LOW  = '\u0590'
_HE_HIGH = '\u05FF'


def _is_hebrew(c: str) -> bool:
    return _HE_LOW <= c <= _HE_HIGH


def _is_numeric_boundary_left(c: str) -> bool:
    """Chars that must NOT appear BEFORE a numeric match.
    Blocks: digit (inside larger number), dot (decimal like 41.5 → don't match '5'),
    comma (thousands separator like 6,854 → don't match '6'),
    slash (date separator like 30/12 → don't match '30').
    """
    return c.isdigit() or c in '.,' '/'


def _is_numeric_boundary_right(c: str) -> bool:
    """Chars that must NOT appear AFTER a numeric match.
    Blocks: digit (inside larger number), slash (date segment).
    Does NOT block lone '.' — a trailing period is sentence punctuation,
    not a decimal point (e.g. 'גוש: 6854.' → replace 6854 OK).
    Does NOT block ',' — '6854,' is a sentence comma, not thousands-separator
    when the comma is on the RIGHT of our match.
    """
    return c.isdigit() or c == '/'


def _safe_replace(text: str, old: str, new: str) -> tuple[str, int]:
    """
    Replace all exact occurrences of `old` with `new` in `text`,
    with boundary protection so we never clobber partial matches.

    Numeric values   — surrounding chars must NOT be digits, dots, commas, slashes.
    Hebrew text      — surrounding chars must NOT be Hebrew letters (no mid-word match).
    Mixed / other    — no boundary restriction beyond exact string match.

    Returns (modified_text, replacement_count).
    """
    if not old:
        return text, 0

    old_len = len(old)

    # Determine what kind of boundary check to apply
    stripped = old.strip()
    is_numeric = stripped.isdigit()
    # "Mostly Hebrew": majority of alpha chars are Hebrew letters
    he_count    = sum(1 for c in old if _is_hebrew(c))
    alpha_count = sum(1 for c in old if c.isalpha())
    is_hebrew_text = alpha_count > 0 and he_count / alpha_count > 0.5

    result: list[str] = []
    pos = 0
    count = 0
    text_len = len(text)

    while True:
        idx = text.find(old, pos)
        if idx == -1:
            result.append(text[pos:])
            break

        end_idx = idx + old_len
        char_before = text[idx - 1]   if idx > 0        else ' '
        char_after  = text[end_idx]   if end_idx < text_len else ' '

        safe = True
        if is_numeric:
            # Left: block digit, dot, comma, slash (decimals, thousands, dates)
            # Right: block digit, slash only (trailing '. ' = sentence punctuation, not decimal)
            if _is_numeric_boundary_left(char_before) or _is_numeric_boundary_right(char_after):
                safe = False
        elif is_hebrew_text:
            # Must not be a substring of a longer Hebrew word
            if _is_hebrew(char_before) or _is_hebrew(char_after):
                safe = False

        if safe:
            result.append(text[pos:idx])
            result.append(new)
            count += 1
            pos = end_idx
        else:
            # Skip past this match position and keep searching
            result.append(text[pos:idx + 1])
            pos = idx + 1

    return ''.join(result), count


def replace_in_file(file_path: str, replacements: dict[str, str]) -> dict[str, int]:
    """
    Apply all replacements to a single XML file.

    IMPORTANT: replacements are applied LONGEST-FIRST to prevent cascade
    corruption (e.g. "הועדה המקומית שוהם" is processed before "שוהם").

    Returns {old_value: count} of replacements made.
    """
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    counts: dict[str, int] = {}

    # Bug 3 fix: sort longest-first to prevent cascade corruption
    sorted_pairs = sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True)

    for old_val, new_val in sorted_pairs:
        content, n = _safe_replace(content, old_val, new_val)
        counts[old_val] = counts.get(old_val, 0) + n

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return counts


def replace_throughout_document(unpacked_dir: str, replacements: dict[str, str]) -> dict[str, int]:
    """
    Apply replacements in ALL XML parts:
      - word/document.xml (body paragraphs + tables)
      - word/header1..3.xml
      - word/footer1..3.xml

    Returns aggregated {label: total_count} dict.
    """
    word_dir = os.path.join(unpacked_dir, "word")
    targets = ["document.xml",
               "header1.xml", "header2.xml", "header3.xml",
               "footer1.xml", "footer2.xml", "footer3.xml"]

    total_counts: dict[str, int] = {v: 0 for v in replacements}

    for fname in targets:
        fpath = os.path.join(word_dir, fname)
        if os.path.exists(fpath):
            counts = replace_in_file(fpath, replacements)
            for key, n in counts.items():
                total_counts[key] = total_counts.get(key, 0) + n

    return total_counts


def get_paragraph_texts(unpacked_dir: str) -> list[str]:
    """
    Extract ordered list of paragraph texts from document.xml.
    Returns list of plain strings (index = paragraph_index for comment injection).
    Skips empty paragraphs but KEEPS their index position.
    """
    from lxml import etree

    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    W    = f"{{{W_NS}}}"

    doc_path = os.path.join(unpacked_dir, "word", "document.xml")
    tree = etree.parse(doc_path)
    root = tree.getroot()

    texts = []
    for para in root.iter(f"{W}p"):
        parts = []
        for t_el in para.iter(f"{W}t"):
            parts.append(t_el.text or "")
        texts.append("".join(parts))

    return texts


def validate_unpacked_docx(unpacked_dir: str, files_only: list[str] = None) -> list[str]:
    """
    Validate XML files in the unpacked DOCX directory.
    Parses each .xml file with lxml to check well-formedness.

    Args:
        unpacked_dir: Path to unpacked DOCX directory.
        files_only: If provided, validate only these specific files (relative paths).
                    If None, validates ALL XML files (slower).

    Returns:
        List of error strings (empty = all valid).
    """
    from lxml import etree

    errors: list[str] = []

    if files_only:
        # Validate only specified files (faster for Stage 2)
        for rel_path in files_only:
            fpath = os.path.join(unpacked_dir, rel_path)
            if not os.path.exists(fpath):
                continue
            try:
                etree.parse(fpath)
            except etree.XMLSyntaxError as e:
                errors.append(f"{rel_path}: {e}")
    else:
        # Validate all XML files (full validation)
        for root_dir, _dirs, files in os.walk(unpacked_dir):
            for fname in files:
                if not fname.endswith(".xml"):
                    continue
                fpath = os.path.join(root_dir, fname)
                try:
                    etree.parse(fpath)
                except etree.XMLSyntaxError as e:
                    rel_path = os.path.relpath(fpath, unpacked_dir)
                    errors.append(f"{rel_path}: {e}")

    return errors


def docx_pack_safe(src_dir: str, dst_docx: str, validate_files: list[str] = None) -> None:
    """
    Validate XML, then repack.
    Raises ValueError if any XML file is malformed.
    This prevents producing a DOCX that Word cannot open.

    Args:
        src_dir: Unpacked DOCX directory.
        dst_docx: Output DOCX path.
        validate_files: If provided, validate only these files (relative paths).
                        Use for Stage 2 where only comments.xml and document.xml change.
                        If None, validates ALL XML files.
    """
    errors = validate_unpacked_docx(src_dir, files_only=validate_files)
    if errors:
        error_detail = "\n  ".join(errors)
        raise ValueError(
            f"XML validation failed — DOCX would be corrupt:\n  {error_detail}"
        )
    docx_pack(src_dir, dst_docx)
