import re
import os
import logging
from lxml import etree

class SectionMapper:
    """
    Analyzes DOCX paragraphs to build a map of {index: label}.
    Labels identify which section/sub-section a paragraph belongs to.
    """

    # Namespaces
    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    W = f"{{{W_NS}}}"

    # Regex patterns for Hebrew sectioning
    # 1) Title starting with number: "1) מטרת חוות הדעת" or "1. מטרת..."
    RE_NUM_TITLE = re.compile(r"^(\d+)[\)\.]\s*(.*)$")
    # 2) Section keyword: "סעיף 11", "פרק ב'"
    RE_SECTION = re.compile(r"^(סעיף|פרק)\s+([א-ת\d]+)(.*)$", re.IGNORECASE)
    # 3) Hebrew letter: "א) תיאור"
    RE_HEB_LETTER = re.compile(r"^([א-ת])[\)\.]\s*(.*)$")
    # 4) TOC detection: dots followed by digits
    RE_TOC = re.compile(r"[\.]{3,}\s*\d+\s*$", re.IGNORECASE)

    def __init__(self, unpacked_dir: str):
        self.unpacked_dir = unpacked_dir
        self.paragraphs = []
        self.mapping = {}

    def _get_text_from_p(self, p_el) -> str:
        parts = []
        for t_el in p_el.iter(self.W + "t"):
            parts.append(t_el.text or "")
        return "".join(parts).strip()

    def _get_style_from_p(self, p_el) -> str:
        pPr = p_el.find(self.W + "pPr")
        if pPr is not None:
            pStyle = pPr.find(self.W + "pStyle")
            if pStyle is not None:
                return pStyle.get(self.W + "val")
        return None

    def load(self):
        """Parse document.xml and load paragraphs with their styles."""
        xml_path = os.path.join(self.unpacked_dir, "word", "document.xml")
        if not os.path.exists(xml_path):
            logging.error(f"document.xml not found at {xml_path}")
            return

        tree = etree.parse(xml_path)
        root = tree.getroot()

        for i, p_el in enumerate(root.iter(self.W + "p")):
            text = self._get_text_from_p(p_el)
            style = self._get_style_from_p(p_el)
            self.paragraphs.append({"index": i, "text": text, "style": style})

    def build_map(self) -> dict[int, str]:
        """
        Builds the map of {paragraph_index: label}.
        A label is like 'סעיף 1' or 'סעיף 7 (מצב תכנוני)'.
        """
        current_section = None
        section_para_count = 0
        
        # Style-based headers (usually integers like '1', '2' in these docs, or 'Heading1')
        HEADER_STYLES = {"1", "2", "3", "Heading1", "Heading2", "Heading3", "a9"}

        for p in self.paragraphs:
            idx = p["index"]
            text = p["text"]
            style = p["style"]

            # 1. Skip TOC
            if style == "TOC1" or self.RE_TOC.search(text):
                self.mapping[idx] = "תוכן עניינים"
                continue

            # 2. Detect if this paragraph IS a header
            is_header = False
            label = None

            # Style check
            if style in HEADER_STYLES and text:
                is_header = True
            
            # Regex check
            m_num = self.RE_NUM_TITLE.match(text)
            m_sec = self.RE_SECTION.match(text)
            m_heb = self.RE_HEB_LETTER.match(text)

            if m_num:
                num, title = m_num.groups()
                label = f"סעיף {num}"
                if title.strip():
                    clean_title = title.strip().lstrip(" -–")
                    if clean_title:
                        label += f" ({clean_title})"
                is_header = True
            elif m_sec:
                type_name, val, rest = m_sec.groups()
                label = f"{type_name} {val}"
                if rest.strip():
                    clean_title = rest.strip().lstrip(" -–")
                    if clean_title:
                        label += f" ({clean_title})"
                is_header = True
            elif m_heb and is_header: # Hebrew letter only if style also says header
                letter, title = m_heb.groups()
                label = f"סעיף {letter}"
                if title.strip():
                    clean_title = title.strip().lstrip(" -–")
                    if clean_title:
                        label += f" ({clean_title})"
                is_header = True

            # Special case for known non-numbered but important headers
            if text in ["פרטי הנכס", "תיאור הנכס והסביבה", "מצב תכנוני", "גורמים ושיקולים", "חשיפה וסיכונים"]:
                label = text
                is_header = True

            if is_header and label:
                current_section = label
                section_para_count = 0
                self.mapping[idx] = label
            elif current_section:
                # Inherit section, add sub-paragraph counter
                section_para_count += 1
                self.mapping[idx] = f"{current_section}, פסקה {section_para_count}"
            else:
                # No section context yet
                self.mapping[idx] = f"תחילת מסמך, פסקה {idx + 1}"

        return self.mapping

def get_section_label(unpacked_dir: str, paragraph_index: int) -> str:
    """Helper to get label for a single index without rebuilding map repeatedly."""
    mapper = SectionMapper(unpacked_dir)
    mapper.load()
    mapping = mapper.build_map()
    return mapping.get(paragraph_index, f"פסקה {paragraph_index}")
