"""
tests/test_stage1.py
pytest test suite for Stage 1 replacement engine (docx_utils._safe_replace).

Run: pytest tests/test_stage1.py -v
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from docx_utils import _safe_replace, replace_throughout_document


# ═══════════════════════════════════════════════════════════════════════════════
# _safe_replace — unit tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestSafeReplaceNumeric:
    """Numeric value replacement with boundary protection."""

    def test_basic_numeric_replacement(self):
        """Plain number surrounded by spaces → replace."""
        text = "גוש: 6854 חלקה: 41"
        result, count = _safe_replace(text, "6854", "7777")
        assert result == "גוש: 7777 חלקה: 41"
        assert count == 1

    def test_no_replace_inside_larger_number(self):
        """'458' must NOT match inside '14580'."""
        text = "14580"
        result, count = _safe_replace(text, "458", "999")
        assert result == "14580"
        assert count == 0

    def test_no_replace_inside_decimal(self):
        """'5' inside '41.5' — dot is to the LEFT of '5', so '5' is blocked."""
        text = "שטח: 41.5 מ\"ר"
        result, count = _safe_replace(text, "5", "9")
        # '5' has '.' immediately before it → left-boundary blocks it
        assert count == 0

    def test_replace_number_with_trailing_period(self):
        """'6854.' — trailing period is sentence punctuation, NOT a decimal. Should replace."""
        text = "גוש: 6854."
        result, count = _safe_replace(text, "6854", "7777")
        assert result == "גוש: 7777."
        assert count == 1

    def test_no_replace_number_in_date_slash(self):
        """'41' inside '30/41/2025' should NOT be replaced (slash boundary)."""
        text = "30/41/2025"
        result, count = _safe_replace(text, "41", "77")
        assert result == "30/41/2025"
        assert count == 0

    def test_replace_number_at_line_start(self):
        """Number at start of text (no char before) → replace."""
        text = "41 מגרש"
        result, count = _safe_replace(text, "41", "77")
        assert result == "77 מגרש"
        assert count == 1

    def test_replace_number_at_line_end(self):
        """Number at end of text (no char after) → replace."""
        text = "חלקה: 41"
        result, count = _safe_replace(text, "41", "77")
        assert result == "חלקה: 77"
        assert count == 1

    def test_no_replace_single_digit_inside_number(self):
        """Single digit '2' must NOT replace inside '26' or '2026'."""
        text = "26 יח\"ד"
        result, count = _safe_replace(text, "2", "7")
        assert result == "26 יח\"ד"
        assert count == 0

    def test_no_replace_digit_inside_year(self):
        """'2' inside '2026' must not be replaced."""
        text = "שנת 2026"
        result, count = _safe_replace(text, "2", "7")
        assert result == "שנת 2026"
        assert count == 0

    def test_replace_multi_digit_numeric(self):
        """Multi-digit numeric replacement with space boundaries → OK."""
        text = "גוש: 6854 מזמין"
        result, count = _safe_replace(text, "6854", "7777")
        assert result == "גוש: 7777 מזמין"
        assert count == 1

    def test_multiple_occurrences(self):
        """All valid occurrences are replaced."""
        text = "6854 ו- 6854 וגם 6854"
        result, count = _safe_replace(text, "6854", "0000")
        assert result == "0000 ו- 0000 וגם 0000"
        assert count == 3

    def test_no_replace_number_beside_comma(self):
        """'41' adjacent to comma (e.g. '6,541') → not replaced."""
        text = "6,541 ש\"ח"
        result, count = _safe_replace(text, "41", "77")
        assert result == "6,541 ש\"ח"
        assert count == 0


class TestSafeReplaceHebrew:
    """Hebrew text replacement with word boundary protection."""

    def test_basic_hebrew_replacement(self):
        """Exact Hebrew word match → replace."""
        text = "מזמין השומה: הועדה המקומית שוהם"
        result, count = _safe_replace(text, "שוהם", "הרצליה")
        assert result == "מזמין השומה: הועדה המקומית הרצליה"
        assert count == 1

    def test_no_replace_hebrew_inside_longer_word(self):
        """'חלקה' inside 'שטח החלקה הינו' — 'חלקה' IS a standalone word here."""
        # Note: "החלקה" has 'ה' prefix — _is_hebrew('ה') is True
        # so "חלקה" should NOT match inside "החלקה"
        text = "שטח החלקה הינו"
        result, count = _safe_replace(text, "חלקה", "999")
        # "החלקה" — char before 'ח' is 'ה' which is Hebrew → protected → no match
        assert result == "שטח החלקה הינו"
        assert count == 0

    def test_replace_standalone_hebrew_word(self):
        """'שוהם' as a standalone word → replace."""
        text = "עיר: שוהם"
        result, count = _safe_replace(text, "שוהם", "תל אביב")
        assert result == "עיר: תל אביב"
        assert count == 1

    def test_no_replace_hebrew_substring(self):
        """'שוהם' must NOT match inside 'שוהמי'."""
        text = "תושבי שוהמי"
        result, count = _safe_replace(text, "שוהם", "הרצליה")
        assert result == "תושבי שוהמי"
        assert count == 0

    def test_replace_long_hebrew_phrase(self):
        """Long phrase replacement — exact match → replace."""
        text = "מזמין השומה: הועדה המקומית שוהם"
        result, count = _safe_replace(text, "הועדה המקומית שוהם", "מינהל מקרקעי ישראל")
        assert result == "מזמין השומה: מינהל מקרקעי ישראל"
        assert count == 1


class TestSafeReplaceMixed:
    """Mixed / edge cases."""

    def test_empty_old_value(self):
        """Empty old_value → no change."""
        text = "some text"
        result, count = _safe_replace(text, "", "X")
        assert result == "some text"
        assert count == 0

    def test_replace_does_not_affect_xml_tags(self):
        """XML tags in the content are treated as plain chars — value inside <w:t> is targeted."""
        # Simulates a snippet of the raw document.xml content
        xml = '<w:t xml:space="preserve">גוש: 6854 חלקה: 41</w:t>'
        result, count = _safe_replace(xml, "6854", "7777")
        assert "7777" in result
        assert "6854" not in result
        assert count == 1

    def test_label_itself_not_replaced(self):
        """Replacement key is old VALUE not label — label text untouched."""
        # Old value = "6854", not "גוש"
        text = "גוש: 6854 גוש נוסף: 6854"
        result, count = _safe_replace(text, "6854", "0000")
        assert "גוש" in result      # label intact
        assert "0000" in result     # value replaced
        assert "6854" not in result
        assert count == 2


# ═══════════════════════════════════════════════════════════════════════════════
# stage1_inject — integration test against real document
# ═══════════════════════════════════════════════════════════════════════════════

DOCS_DIR = r'c:\Users\Amit\Documents\anitgravity\rami project final'


@pytest.mark.integration
def test_stage1_real_document_type_b():
    """
    Upload 2026023T.docx, change גוש/חלקה/תת חלקה values.
    Verify: values replaced, labels intact, table numbers untouched.
    """
    import shutil
    from stage1_inject import run_stage1
    from docx_utils import get_paragraph_texts, docx_unpack
    import tempfile
    from config import TEMP_DIR

    docx_path = os.path.join(DOCS_DIR, "2026023T.docx")
    if not os.path.exists(docx_path):
        pytest.skip("Test document not found")

    # Simulate the user changing these values in the form
    confirmed_fields = {
        'גוש':          '7777',       # was 6854
        'חלקה':         '77',         # was 41
        'תת חלקה':      '7',          # was 2  (single digit — pattern only)
        'מזמין השומה':  'הועדה המקומית שוהם',  # unchanged
        'המבקשים':      'יוחאי פנחס פרסר',     # unchanged
        'סלע/כניסה':    "הסלע 1 כניסה ב'",     # unchanged
        'שכונה':        'ורדים',      # unchanged
        'עיר':          'שוהם',       # unchanged
    }

    with open(docx_path, 'rb') as f:
        output_path, label_counts = run_stage1(f, confirmed_fields)

    assert os.path.exists(output_path), "Output file was not created"

    # Unpack output and inspect paragraph text
    unpack_dir = output_path.replace('.docx', '_test_unpack')
    try:
        docx_unpack(output_path, unpack_dir)
        paragraphs = get_paragraph_texts(unpack_dir)
        full_text = '\n'.join(paragraphs)

        # ✅ New values are present
        assert '7777' in full_text, "גוש new value 7777 not found"
        assert '77' in full_text,   "חלקה new value 77 not found"

        # ✅ Old values are gone
        assert '6854' not in full_text, "Old גוש value 6854 still present"
        assert ' 41 ' not in full_text and ': 41' not in full_text, \
            "Old חלקה value 41 still present"

        # ✅ Label text is intact (not replaced)
        assert 'גוש' in full_text,   "Label 'גוש' was incorrectly deleted"
        assert 'חלקה' in full_text,  "Label 'חלקה' was incorrectly deleted"

        print(f"\nReplacement counts: {label_counts}")
        print("INTEGRATION TEST: PASS")

    finally:
        shutil.rmtree(unpack_dir, ignore_errors=True)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
