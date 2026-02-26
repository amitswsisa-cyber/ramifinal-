import os
import shutil
import pytest
from section_mapper import SectionMapper

# Mock document.xml content with styles and patterns
MOCK_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
    <w:p><w:pPr><w:pStyle w:val="TOC1"/></w:pPr><w:r><w:t>1) Introduction ...... 3</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="1"/></w:pPr><w:r><w:t>1) מטרת חוות הדעת</w:t></w:r></w:p>
    <w:p><w:r><w:t>פסקה ראשונה במטרה</w:t></w:r></w:p>
    <w:p><w:r><w:t>פסקה שניה במטרה</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="1"/></w:pPr><w:r><w:t>2) ביקורים</w:t></w:r></w:p>
    <w:p><w:r><w:t>ביקרתי בנכס ביום ג'</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>סעיף 11 - תחשיבים</w:t></w:r></w:p>
    <w:p><w:r><w:t>חישוב השטח הכולל</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="a9"/></w:pPr><w:r><w:t>א) נתוני השוואה</w:t></w:r></w:p>
    <w:p><w:r><w:t>נכס א' נמכר ב-X</w:t></w:r></w:p>
</w:body>
</w:document>
"""

@pytest.fixture
def temp_unpacked_dir(tmp_path):
    d = tmp_path / "mock_unpacked"
    word_dir = d / "word"
    word_dir.mkdir(parents=True)
    xml_file = word_dir / "document.xml"
    xml_file.write_text(MOCK_XML, encoding="utf-8")
    return str(d)

def test_section_mapper_logic(temp_unpacked_dir):
    mapper = SectionMapper(temp_unpacked_dir)
    mapper.load()
    mapping = mapper.build_map()

    # Index 0: TOC
    assert "תוכן עניינים" in mapping[0]
    
    # Index 1: "1) מטרת חוות הדעת"
    assert "סעיף 1 (מטרת חוות הדעת)" in mapping[1]
    
    # Index 2: Inherited from 1
    assert mapping[2] == "סעיף 1 (מטרת חוות הדעת), פסקה 1"
    
    # Index 3: Inherited from 1
    assert mapping[3] == "סעיף 1 (מטרת חוות הדעת), פסקה 2"
    
    # Index 4: "2) ביקורים"
    assert "סעיף 2 (ביקורים)" in mapping[4]
    
    # Index 5: Inherited from 4
    assert mapping[5] == "סעיף 2 (ביקורים), פסקה 1"
    
    # Index 6: "סעיף 11 - תחשיבים" (style Heading1)
    assert "סעיף 11" in mapping[6]
    
    # Index 8: "א) נתוני השוואה" (style a9)
    assert "סעיף א" in mapping[8]
    
    # Index 9: Inherited from 8
    assert mapping[9] == "סעיף א (נתוני השוואה), פסקה 1"

if __name__ == "__main__":
    # For manual run
    import sys
    pytest.main([__file__])
