"""
pattern_replacer.py
Pattern-based replacement engine for Hebrew appraisal DOCX templates.

Instead of global find-and-replace (which can corrupt free text),
this module defines the exact context patterns from the master template
and replaces values ONLY within those patterns.

Works at the lxml <w:t> element level to preserve formatting.
"""
import os
import re
import hashlib
from copy import deepcopy
from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"

# ── Underscore placeholder regex ──────────────────────────────────────────────
_UNDERSCORES = r'_{2,}'

# Value patterns: underscores OR non-whitespace (greedy)
_VAL = r'(?:' + _UNDERSCORES + r'|\S+)'
# Value patterns for longer values that may contain spaces (lazy, needs anchor after it)
_VAL_TO_END = r'(?:' + _UNDERSCORES + r'|[^\n]+?)'
# Value that runs to end of line, consuming everything except trailing period
_VAL_TO_EOL = r'(?:' + _UNDERSCORES + r'|[^\n.]+)'


# ═══════════════════════════════════════════════════════════════════════
# PATTERN DEFINITIONS
#
# Each pattern is (compiled_regex, [field_names]).
# For single-field patterns: regex groups = (prefix, VALUE, [suffix...])
# For two-field patterns: regex groups = (prefix, VALUE1, middle, VALUE2, [suffix...])
#
# IMPORTANT: patterns are applied PER FIELD per paragraph. We track which
# (paragraph, field) pairs have already been replaced to prevent double-
# replacement when multiple patterns match the same location.
# ═══════════════════════════════════════════════════════════════════════

def _build_cover_patterns():
    """
    Group A — Cover page lines (page 1 AND page 2 repeat).
    Also matches Section 6 lines that use the same "label: value" format.
    """
    return [
        # 1. שומת נכס מקרקעין מלאה - VALUE → סוג שומה
        (re.compile(
            r'(שומת\s+נכס\s+מקרקעין\s+\S+\s*-\s*)'
            r'(' + _VAL_TO_END + r')'
            r'(?=\s*$)'
        ), ["סוג שומה"]),

        # 2. גוש: VALUE — covers both cover page AND section 6 "גוש: 6636."
        (re.compile(r'(גוש\s*:\s*)(' + _VAL + r')'), ["גוש"]),

        # 3. תת חלקה: VALUE — MUST come BEFORE חלקה to prevent overlap.
        #    Also matches תת-חלקה.
        (re.compile(r'(תת[\s\-]חלקה\s*:\s*)(' + _VAL + r')'), ["תת חלקה"]),

        # 4. חלקה: VALUE — negative lookbehind prevents matching inside "תת חלקה:"
        (re.compile(r'(?<!תת )(?<!תת-)(חלקה\s*:\s*)(' + _VAL + r')'), ["חלקה"]),

        # 5. מגרש: VALUE
        (re.compile(r'(מגרש\s*:\s*)(' + _VAL + r')'), ["מגרש"]),

        # 6. רחוב VALUE (standalone or with colon)
        (re.compile(r'(רחוב\s*:?\s*)(' + _VAL_TO_END + r')(?=\s*$|,)'), ["רחוב"]),

        # 7. עיר: VALUE
        (re.compile(r'(עיר\s*:\s*)(' + _VAL_TO_END + r')(?=\s*$)'), ["עיר"]),

        # 8. מזמין השומה: VALUE
        (re.compile(r'(מזמין\s+השומה\s*:\s*)(' + _VAL_TO_END + r')(?=\s*$)'), ["מזמין השומה"]),

        # 9. מספר תיק: VALUE
        (re.compile(r'(מספר\s+תיק\s*:\s*)(' + _VAL + r')'), ["מספר תיק"]),
    ]


def _build_section6_patterns():
    """
    Group B — Section 6 paragraph-style lines that DON'T overlap with cover patterns.
    These have unique label prefixes (שטח חלקה, שטח בנוי, etc.)
    """
    return [
        # 10. שטח חלקה: VALUE. or שטח החלקה: VALUE.
        # Value = everything after colon until trailing period (greedy)
        (re.compile(r'(שטח\s+(?:ה)?חלקה\s*:?\s*)(' + _VAL_TO_EOL + r')(\s*\.?)'), ["שטח חלקה"]),

        # 11. שטח בנוי: VALUE.
        (re.compile(r'(שטח\s+בנוי\s*:?\s*)(' + _VAL_TO_EOL + r')(\s*\.?)'), ["שטח בנוי"]),

        # 12. תיאור זכויות: VALUE.
        (re.compile(r'(תיאור\s+זכויות\s*:?\s*)(' + _VAL_TO_EOL + r')(\s*\.?)'), ["תיאור זכויות"]),

        # 13. החלקה הנישום: VALUE. or החלק הנישום: VALUE.
        (re.compile(r'(החלק(?:ה)?\s+הנישום\s*:?\s*)(' + _VAL_TO_EOL + r')(\s*\.?)'), ["החלקה הנישום"]),

        # 14. מיקום: רחוב VALUE, VALUE. → רחוב + עיר
        # City value: greedy match up to trailing period
        (re.compile(
            r'(מיקום\s*:\s*רחוב\s+)'
            r'(' + _VAL_TO_END + r')'
            r'(\s*,\s*)'
            r'(' + _VAL_TO_EOL + r')'
            r'(\.?)'
        ), ["רחוב", "עיר"]),
    ]


def _build_body_patterns():
    """
    Group C — Body paragraph patterns.
    Group D — Specific body lines.
    """
    return [
        # 15. חלקה VALUE בגוש VALUE (paragraphs ~91, ~93)
        (re.compile(
            r'(חלקה\s+)(' + _VAL + r')'
            r'(\s+בגוש\s+)(' + _VAL + r')'
            r'(?=[\s,\.]|$)'
        ), ["חלקה", "גוש"]),

        # 16. עירית VALUE / עיריית VALUE (sections 10, 12)
        (re.compile(
            r'(עירי[יּ]?ת\s+)((?:' + _UNDERSCORES + r'|[^\s,.\n]+(?:\s+[^\s,.\n]+)*))'
            r'(?=[\s,.\n]|$)'
        ), ["עיר"]),

        # 17. העיר VALUE בכלל (section 12)
        (re.compile(
            r'(העיר\s+)((?:' + _UNDERSCORES + r'|[^\s,.\n]+(?:\s+[^\s,.\n]+)*))'
            r'(\s+בכלל)'
        ), ["עיר"]),

        # 18. נתבקשתי על ידי VALUE, → מזמין השומה
        (re.compile(
            r'(נתבקשתי\s+על\s+ידי\s+)(' + _VAL_TO_END + r')'
            r'(\s*,)'
        ), ["מזמין השומה"]),

        # 19. מלאה- VALUE (page 2 title repeat)
        (re.compile(
            r'(מלאה\s*-\s*)(' + _VAL_TO_END + r')'
            r'(?=\s*$)'
        ), ["סוג שומה"]),
    ]


# ═══════════════════════════════════════════════════════════════════════
# TABLE 1 (פרטי הנכס) HANDLER — for documents that use actual XML tables
# ═══════════════════════════════════════════════════════════════════════

TABLE1_LABELS = {
    "גוש": "גוש",
    "חלקה": "חלקה",
    "שטח חלקה": "שטח חלקה",
    "תת חלקה": "תת חלקה",
    "תת-חלקה": "תת חלקה",
    "שטח בנוי": "שטח בנוי",
    "תיאור זכויות": "תיאור זכויות",
    "מיקום": "מיקום",
    "החלקה הנישום": "החלקה הנישום",
    "החלק הנישום": "החלקה הנישום",
    "מגרש": "מגרש",
    "שכונה": "שכונה",
    "שכונת": "שכונה",
}


def _process_table1(root, field_values, counts):
    """
    Find Table 1 (פרטי הנכס) and fill value cells.
    Only processes actual <w:tbl> XML tables.
    """
    for tbl in root.iter(f"{W}tbl"):
        rows = list(tbl.iter(f"{W}tr"))
        if not rows:
            continue

        # Check if this table contains known labels
        is_table1 = False
        for row in rows:
            cells = list(row.iter(f"{W}tc"))
            for cell in cells:
                label_text = _get_cell_text(cell).strip().rstrip(": ").strip()
                if label_text in TABLE1_LABELS:
                    is_table1 = True
                    break
            if is_table1:
                break

        if not is_table1:
            continue

        # Process each row
        for row in rows:
            cells = list(row.iter(f"{W}tc"))
            if len(cells) < 2:
                continue

            # Find the label cell (check all cells)
            label_cell_idx = -1
            field_name = None
            for i, cell in enumerate(cells):
                text = _get_cell_text(cell).strip()
                # Strip trailing colon/whitespace for matching (cells may contain "גוש:" or "גוש :")
                text_clean = text.rstrip(": ").strip()
                if text_clean in TABLE1_LABELS:
                    label_cell_idx = i
                    field_name = TABLE1_LABELS[text_clean]
                    break

            if label_cell_idx < 0 or not field_name:
                continue

            new_value = field_values.get(field_name, "")

            # Composite field: table label "מיקום" → cover fields "רחוב" + "עיר"
            if not new_value and field_name == "מיקום":
                street = field_values.get("רחוב", "")
                city = field_values.get("עיר", "")
                if street and city:
                    new_value = f"{street}, {city}"
                elif street:
                    new_value = street
                elif city:
                    new_value = city

            if not new_value:
                continue

            # Fill value cells (all non-label cells)
            for i, cell in enumerate(cells):
                if i == label_cell_idx:
                    continue
                cell_text = _get_cell_text(cell).strip()
                if cell_text == new_value:
                    continue  # already has the right value
                if not cell_text or re.fullmatch(r'_+', cell_text) or cell_text != new_value:
                    _set_cell_text(cell, new_value)
                    counts[field_name] = counts.get(field_name, 0) + 1


def _get_cell_text(tc_element):
    """Get concatenated text from a table cell."""
    parts = []
    for t_el in tc_element.iter(f"{W}t"):
        parts.append(t_el.text or "")
    return "".join(parts)


def _set_cell_text(tc_element, new_text):
    """Set text in a table cell, preserving formatting of the first run."""
    t_elements = list(tc_element.iter(f"{W}t"))
    if not t_elements:
        paras = list(tc_element.iter(f"{W}p"))
        if not paras:
            return
        para = paras[0]
        # Find reference rPr from any run in the same table row
        ref_rpr = None
        parent = tc_element.getparent()  # <w:tr>
        if parent is not None:
            for r in parent.iter(f"{W}r"):
                rpr = r.find(f"{W}rPr")
                if rpr is not None:
                    ref_rpr = rpr
                    break
        run = etree.SubElement(para, f"{W}r")
        if ref_rpr is not None:
            run.insert(0, deepcopy(ref_rpr))
        t_el = etree.SubElement(run, f"{W}t")
        t_el.text = new_text
        t_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        return

    # Existing text — find reference font from runs in the cell
    ref_rfonts = None
    for r_el in tc_element.iter(f"{W}r"):
        rpr = r_el.find(f"{W}rPr")
        if rpr is not None:
            rf = rpr.find(f"{W}rFonts")
            if rf is not None:
                ref_rfonts = rf
                break

    t_elements[0].text = new_text
    t_elements[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    # Ensure the modified run has proper font info
    if ref_rfonts is not None:
        first_run = t_elements[0].getparent()
        if first_run is not None and first_run.tag == f"{W}r":
            rpr = first_run.find(f"{W}rPr")
            if rpr is None:
                rpr = etree.Element(f"{W}rPr")
                first_run.insert(0, rpr)
            if rpr.find(f"{W}rFonts") is None:
                rpr.insert(0, deepcopy(ref_rfonts))

    for t_el in t_elements[1:]:
        t_el.text = ""


# ═══════════════════════════════════════════════════════════════════════
# PARAGRAPH-LEVEL PATTERN MATCHING
# ═══════════════════════════════════════════════════════════════════════

def _get_para_text(para_element):
    """Get full text of a paragraph by concatenating all <w:t> elements."""
    parts = []
    for t_el in para_element.iter(f"{W}t"):
        parts.append(t_el.text or "")
    return "".join(parts)


def _replace_value_in_runs(para_element, old_text, new_text, match_start=None):
    """
    Replace old_text with new_text within the <w:t> elements of a paragraph.
    Preserves formatting by mapping back to individual <w:t> elements.
    After replacement, copies rFonts from the paragraph's reference run
    to ensure replaced text uses the same font as the labels.

    Args:
        para_element: lxml paragraph element
        old_text: text to replace
        new_text: replacement text
        match_start: if provided, the exact character position in the
                     concatenated paragraph text where old_text starts.
                     This prevents replacing at wrong positions when the
                     same substring appears multiple times.
    """
    t_elements = list(para_element.iter(f"{W}t"))
    if not t_elements:
        return False

    full_text = ""
    t_map = []
    for t_el in t_elements:
        t_text = t_el.text or ""
        start = len(full_text)
        full_text += t_text
        t_map.append((start, start + len(t_text), t_el))

    if match_start is not None:
        # Use the exact position from the regex match
        idx = match_start
        # Verify the text actually exists at this position
        if full_text[idx:idx + len(old_text)] != old_text:
            # Fallback to find if positions shifted from earlier edits
            idx = full_text.find(old_text)
    else:
        idx = full_text.find(old_text)

    if idx == -1:
        return False

    old_end = idx + len(old_text)

    # Find reference rFonts from the first run that has font properties
    ref_rfonts = None
    for r in para_element.iter(f"{W}r"):
        rpr = r.find(f"{W}rPr")
        if rpr is not None:
            rf = rpr.find(f"{W}rFonts")
            if rf is not None:
                ref_rfonts = rf
                break

    first_overlap = True
    modified_t_elements = []
    for t_start, t_end, t_el in t_map:
        t_text = t_el.text or ""

        if t_end <= idx or t_start >= old_end:
            continue

        local_start = max(0, idx - t_start)
        local_end = min(len(t_text), old_end - t_start)

        if first_overlap:
            t_el.text = t_text[:local_start] + new_text + t_text[local_end:]
            t_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            first_overlap = False
            modified_t_elements.append(t_el)
        else:
            t_el.text = t_text[:local_start] + t_text[local_end:]

    # Ensure modified runs inherit font from the paragraph's reference run
    if ref_rfonts is not None:
        for t_el in modified_t_elements:
            run = t_el.getparent()
            if run is None or run.tag != f"{W}r":
                continue
            rpr = run.find(f"{W}rPr")
            if rpr is None:
                rpr = etree.Element(f"{W}rPr")
                run.insert(0, rpr)
            if rpr.find(f"{W}rFonts") is None:
                rpr.insert(0, deepcopy(ref_rfonts))

    return True


def _apply_pattern_to_paragraph(para_element, pattern, field_names, field_values,
                                extracted_fields, counts, replaced_fields):
    """
    Check if a paragraph's text matches a pattern.
    If it does, replace the VALUE portions with new values.

    Args:
        para_element: lxml paragraph element
        pattern: compiled regex
        field_names: list of field names captured by this pattern's groups
        field_values: {field_name: new_value} — what to replace WITH
        extracted_fields: {field_name: old_value} — original extracted values
        counts: mutable dict to track replacement counts
        replaced_fields: set of field names already replaced in THIS paragraph
                        (prevents double-replacement from overlapping patterns)
    """
    # Skip fields that were already replaced in this paragraph
    remaining_fields = [f for f in field_names if f not in replaced_fields]
    if not remaining_fields:
        return

    full_text = _get_para_text(para_element)
    if not full_text.strip():
        return

    # 🛑 NUCLEAR SAFEGUARD FOR LETTERHEAD 🛑
    # If the paragraph contains ANY of the letterhead keywords (English or Hebrew),
    # immediately abort processing this entire paragraph.
    upper_text = full_text.upper()
    if "אמירים" in full_text or "AMIRIM" in upper_text or "TEL-AVIV ISRAEL" in upper_text or "03-644" in full_text:
        return

    match = pattern.search(full_text)
    if not match:
        return

    groups = match.groups()

    if len(field_names) == 1:
        field_name = field_names[0]
        if field_name in replaced_fields:
            return
        new_value = field_values.get(field_name, "")
        if not new_value:
            return

        old_value = groups[1]

        # Hardcode protection for the base template (letterhead address)
        if "אמירים" in old_value and field_name in ["רחוב", "מיקום", "עיר"]:
            return

        # Calculate exact position of the value in the full paragraph text
        value_start = match.start(2)  # group 2 = the value capture group
        # Normalize: strip trailing period from new_value since pattern
        # captures value without the period (period is in a separate group)
        new_value_clean = new_value.rstrip(".")
        if old_value == new_value or old_value == new_value_clean:
            return

        if _replace_value_in_runs(para_element, old_value, new_value_clean, match_start=value_start):
            counts[field_name] = counts.get(field_name, 0) + 1
            replaced_fields.add(field_name)

    elif len(field_names) == 2:
        # Replace second field first (right-to-left) to avoid offset issues
        for field_idx in reversed(range(2)):
            field_name = field_names[field_idx]
            if field_name in replaced_fields:
                continue
            new_value = field_values.get(field_name, "")
            if not new_value:
                continue

            value_group_idx = 1 + field_idx * 2
            if value_group_idx >= len(groups):
                continue

            old_value = groups[value_group_idx]
            
            # Hardcode protection for the base template (letterhead address)
            if "אמירים" in old_value and field_name in ["רחוב", "מיקום", "עיר"]:
                continue

            # Calculate exact position from the regex match group
            value_start = match.start(value_group_idx + 1)  # +1 because groups are 1-indexed in match.start()
            new_value_clean = new_value.rstrip(".")
            if old_value == new_value or old_value == new_value_clean:
                continue

            if _replace_value_in_runs(para_element, old_value, new_value_clean, match_start=value_start):
                counts[field_name] = counts.get(field_name, 0) + 1
                replaced_fields.add(field_name)


# ═══════════════════════════════════════════════════════════════════════
# MAIN API
# ═══════════════════════════════════════════════════════════════════════

def pattern_replace(unpacked_dir, confirmed_fields, extracted_fields=None):
    """
    Replace field values in the DOCX using context-aware patterns.

    Args:
        unpacked_dir: Path to unpacked DOCX directory
        confirmed_fields: {field_name: new_value} — user-confirmed values
        extracted_fields: {field_name: old_value} — original extracted values

    Returns:
        counts: {field_name: replacement_count}
    """
    counts = {}

    # ── 🛑 HEADER INTEGRITY: snapshot header hashes BEFORE any work ─────
    word_dir = os.path.join(unpacked_dir, "word")
    header_hashes = _snapshot_header_hashes(word_dir)

    # Build all pattern groups
    cover_patterns = _build_cover_patterns()
    section6_patterns = _build_section6_patterns()
    body_patterns = _build_body_patterns()

    all_patterns = cover_patterns + section6_patterns + body_patterns

    # ── Process document.xml ──────────────────────────────────────────────
    doc_path = os.path.join(unpacked_dir, "word", "document.xml")
    if os.path.exists(doc_path):
        tree = etree.parse(doc_path)
        root = tree.getroot()

        # Pattern-based paragraph replacement
        for para in root.iter(f"{W}p"):
            # Track which fields have been replaced in THIS paragraph
            # to prevent double-replacement from overlapping patterns
            replaced_fields = set()
            for pattern, field_names in all_patterns:
                _apply_pattern_to_paragraph(
                    para, pattern, field_names,
                    confirmed_fields, extracted_fields or {},
                    counts, replaced_fields
                )

        # Table 1 replacement (for docs that use actual XML tables)
        _process_table1(root, confirmed_fields, counts)

        # Save
        with open(doc_path, "wb") as f:
            tree.write(f, xml_declaration=True, encoding="UTF-8", standalone=True)

    # ── Process headers/footers ───────────────────────────────────────────
    # Per user request, we DO NOT process headers and footers to protect
    # the basic template (like the company letterhead "רחוב אמירים 14").
    # The replacement should only happen in the main document body.

    # ── 🛑 HEADER INTEGRITY: verify headers were NOT modified ─────────
    _verify_header_integrity(word_dir, header_hashes)

    return counts


# ═══════════════════════════════════════════════════════════════════════
# HEADER INTEGRITY HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _snapshot_header_hashes(word_dir: str) -> dict[str, str]:
    """
    Compute MD5 hashes of all header/footer XML files.
    Used as a before/after check to ensure they are never modified.
    """
    hashes = {}
    for pattern in ("header", "footer"):
        for i in range(1, 4):
            fpath = os.path.join(word_dir, f"{pattern}{i}.xml")
            if os.path.exists(fpath):
                hashes[fpath] = hashlib.md5(open(fpath, "rb").read()).hexdigest()
    return hashes


def _verify_header_integrity(word_dir: str, original_hashes: dict[str, str]) -> None:
    """
    Verify that header/footer XML files were NOT modified during processing.
    Raises RuntimeError if any header was changed — this is always a bug.
    """
    for fpath, original_hash in original_hashes.items():
        if not os.path.exists(fpath):
            continue
        current_hash = hashlib.md5(open(fpath, "rb").read()).hexdigest()
        if current_hash != original_hash:
            fname = os.path.basename(fpath)
            raise RuntimeError(
                f"HEADER INTEGRITY VIOLATION: {fname} was modified during "
                f"pattern_replace(). This is a bug — headers must never be touched."
            )
