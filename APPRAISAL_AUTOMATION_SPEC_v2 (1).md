# Appraisal Report Automation System
## Project Specification — v2.0
### Client: Savitzky Rami Real Estate Appraisers Ltd (סויצקי רמי שמאות מקרקעין וניהול בע"מ)
### Platform: Antigravity + Claude API | Frontend: Streamlit
### Language: Python 3.11+

---

## 1. PROJECT OVERVIEW

Build a two-stage automation pipeline for Hebrew real estate appraisal reports (DOCX format).

**Stage 1 — Data Injection:**
The appraiser uploads their report template. The system dynamically reads ALL label:value pairs from the cover page, presents a confirmation form, then performs a global find-and-replace across the entire document. The appraiser downloads a filled DOCX and works on it manually.

**Stage 2 — Pre-Submission Review:**
After the appraiser finishes working on the document, they upload it for final review. The system sends the document to Claude API and injects findings as native Word comments anchored to specific paragraphs — including alternative phrasing suggestions where relevant.

**Critical constraint:** Stage 1 output and Stage 2 input are separate uploads. The appraiser works on the document between the two stages. Do NOT chain them automatically.

---

## 2. FRONTEND (Streamlit)

### Why Streamlit
Simple internal tool for 1-3 users. Streamlit provides file upload + form + file download in ~50 lines of Python. No design skills required. Can run locally (`streamlit run app.py`) or be deployed free on Streamlit Cloud for multi-user access.

### UI Layout

```
========================================
  Savitzky Appraisal Automation Tool
========================================

[TAB 1: Stage 1 — Fill Report]
  Upload your template DOCX:
  [ Choose File ]

  → After upload, extracted fields appear as editable inputs
  → User confirms/edits → clicks [Process Document]
  → [⬇ Download Filled Report]

[TAB 2: Stage 2 — Review Report]
  Upload your completed DOCX:
  [ Choose File ]

  → Click [Run Review]
  → Summary of findings shown on screen
  → [⬇ Download Reviewed Report with Comments]
========================================
```

### app.py structure

```python
import streamlit as st
from stage1_inject import run_stage1
from stage2_review import run_stage2

st.title("Savitzky Appraisal Automation")

tab1, tab2 = st.tabs(["Stage 1 — Fill Report", "Stage 2 — Review Report"])

with tab1:
    uploaded = st.file_uploader("Upload template DOCX", type="docx")
    if uploaded:
        fields = extract_cover_fields(uploaded)
        edited = {}
        for label, value in fields.items():
            edited[label] = st.text_input(label, value=value)
        if st.button("Process Document"):
            output_path = run_stage1(uploaded, edited)
            with open(output_path, "rb") as f:
                st.download_button("⬇ Download Filled Report", f,
                                   file_name="report_filled.docx")

with tab2:
    uploaded2 = st.file_uploader("Upload completed DOCX", type="docx", key="s2")
    if uploaded2:
        if st.button("Run Review"):
            output_path, summary = run_stage2(uploaded2)
            st.write(summary)
            with open(output_path, "rb") as f:
                st.download_button("⬇ Download Reviewed Report", f,
                                   file_name="report_reviewed.docx")
```

### Deployment options
- **Local only:** `streamlit run app.py` — runs on `localhost:8501`
- **Team access (2-3 people):** Deploy to [Streamlit Cloud](https://streamlit.io/cloud) (free tier) — share a URL, password-protect with `st.secrets`
- **More control:** Deploy on a $5/month DigitalOcean or Railway server

---

## 3. DOCUMENT TYPES

The system handles two primary report formats from the same appraisal firm:

### Type A: Standard Appraisal (שומת נכס מקרקעין)
Cover contains `שומת נכס מקרקעין` or `שומה` in title.

### Type B: Betterment Levy (היטל השבחה)
Cover contains `היטל השבחה` in title.
Has additional fields: המבקשים, שכונה, סלע/כניסה.

### Type C: Correction (תיקון שומה)
Cover contains `תיקון שומה` — treat as Type A, also extract original file number reference.

**Detection:** Read title text inside bordered box on page 1.

---

## 4. STAGE 1 — DATA INJECTION

### 4.1 Flow
```
User uploads DOCX
      ↓
system reads cover page (page 1–2 only)
      ↓
DYNAMIC extraction: scan ALL label:value pairs found
      ↓
present editable confirmation form (all fields, including unexpected ones)
      ↓
user confirms / corrects / adds values
      ↓
global find-and-replace throughout entire document
      ↓
user downloads filled DOCX
```

### 4.2 Dynamic Field Extraction

**Do NOT use a hardcoded field list.** Instead, scan all label:value pairs dynamically from the cover box. This handles new field types without code changes.

```python
def extract_all_label_value_pairs(docx_path: str) -> dict[str, str]:
    """
    Scan the bordered table/box on page 1.
    For each cell that contains a colon-separated label:value or
    adjacent label/value cells, extract the pair.
    Return ALL pairs found — not just known fields.
    """
    from docx import Document
    doc = Document(docx_path)
    
    fields = {}
    # Check tables on first 2 pages
    for table in doc.tables[:5]:
        for row in table.rows:
            for i, cell in enumerate(row.cells):
                text = cell.text.strip()
                if ':' in text:
                    parts = text.split(':', 1)
                    label = parts[0].strip()
                    value = parts[1].strip()
                    if label and value:
                        fields[label] = value
                elif text.endswith(':') and i + 1 < len(row.cells):
                    label = text.rstrip(':').strip()
                    value = row.cells[i + 1].text.strip()
                    if label and value:
                        fields[label] = value
    return fields
```

**Known field labels (Hebrew) for reference — but accept ANY label found:**

| Document Label | Example Value |
|---|---|
| גוש | 6623 |
| חלקה | 458 |
| תת חלקה / מגרש | 41, ב', 2 |
| רחוב | אשכנזי 80 |
| עיר / ישוב | תל אביב |
| מזמין השומה | הועדה המקומית תל אביב |
| מספר תיק | 12005-2025 |
| המבקשים | יוחאי פנחס פרסר |
| שכונה | ורדים |
| סלע / כניסה | סלע 1 כניסה ב' |

If a field is not found, mark as `EMPTY` — never guess.

### 4.3 Confirmation Form

Present all extracted fields as editable text inputs (see Streamlit UI above). User can:
- Correct any value
- Leave a value unchanged
- See `⚠️ EMPTY` for missing fields (shown in red)

Only proceed after user clicks "Process Document".

### 4.4 Global Find-and-Replace

After confirmation, replace every occurrence of each value throughout the entire document.

**Scope — search and replace in ALL of:**
- Body paragraphs (`w:body > w:p`)
- Table cells (`w:tbl > w:tr > w:tc > w:p`)
- Headers (`word/header1.xml`, `word/header2.xml`, `word/header3.xml`)
- Footers (`word/footer1.xml`, `word/footer2.xml`, `word/footer3.xml`)

**Technical implementation:**
```bash
# Step 1: Unpack DOCX to XML (merges split runs automatically)
python scripts/office/unpack.py input.docx unpacked/

# Step 2: String replace in each XML file
# Step 3: Repack
python scripts/office/pack.py unpacked/ output_filled.docx --original input.docx
```

**Replacement rules:**
- Exact string match — do NOT use regex
- Replace ALL occurrences, not just first
- Partial match protection for numbers: check `char[index-1]` and `char[index+len(value)]` are not digits
- Preserve surrounding `<w:rPr>` formatting — only change `<w:t>` content
- Skip field labels themselves (only replace values, not "גוש:" label)

**Do NOT change:**
- Page layout, margins, fonts, colors
- Section headings and titles  
- Boilerplate legal clauses
- The "הגבלת שימוש" yellow warning box

### 4.5 Output

File: `[original_filename]_filled.docx`

Show replacement count per field so the appraiser can verify:
```
✅ Done. Replaced values across the document:
גוש (6623): 8 locations
חלקה (458): 6 locations
רחוב (אשכנזי 80): 3 locations
...
Total: 22 replacements.
```

---

## 5. STAGE 2 — PRE-SUBMISSION REVIEW

### 5.1 Flow
```
User uploads completed DOCX (after manual editing)
      ↓
extract full text with paragraph index mapping
      ↓
single Claude API call with reviewer persona
      ↓
receive structured JSON findings
      ↓
inject each finding as a Word Comment (with suggestion where applicable)
      ↓
user downloads reviewed DOCX
```

### 5.2 Text Extraction

```bash
pandoc --track-changes=all input.docx -o extracted.md
```

Build paragraph map: `{paragraph_index: xml_paragraph_element}` by parsing `document.xml` directly.

### 5.3 Claude API Call

**Model:** `claude-sonnet-4-6` (configurable — see config.py)
**Max tokens:** 10000
**Format:** Anthropic Structured Outputs API with Pydantic schema

**System prompt (Hebrew — do not translate):**
```
אתה שמאי מקרקעין בכיר עם 20 שנות ניסיון, עורך ביקורת עמיתים על דוח שומה לפני הגשה לבנק או לועדה המקומית.

תפקידך לזהות בעיות מהותיות שחשוב לטפל בהן לפני הגשה.

בדוק את הדברים הבאים:

1. עקביות לוגית — האם המסקנה הסופית תואמת את הנתונים המוצגים? האם יש סתירות בין חלקים שונים בדוח (שטחים, ערכים, גוש/חלקה)?

2. פערים וחסרים — האם חסרים סעיפים נדרשים? האם יש שדות שנותרו ריקים (_____)?  האם סעיף 14 (נתונים השוואתיים) ריק? האם סעיף 15 (תחשיבים) מולא?

3. ריכוז שגיאות כתיב — אל תדגיש כל שגיאה בנפרד. אם בפסקה מסוימת יש מספר שגיאות כתיב — כתוב הערה אחת על הפסקה כולה, עם ציון המילים הבעייתיות.

4. ניסוח בעייתי — משפטים שניתן לקרוא בשתי דרכים, שפה לא פורמלית, משפטים שאורכם גורם לאי-בהירות, ניסוח שעלול ליצור חשיפה משפטית. עבור כל ממצא כזה — הצע ניסוח חלופי מוכן לשימוש בשדה suggestion.

5. סימני פיסוק — זהה מקומות שבהם חסר פסיק, נקודה, או שנעשה שימוש שגוי בסימני פיסוק שמשנה את משמעות המשפט. עבור כל ממצא — הצע את הטקסט המתוקן בשדה suggestion.

כללים:
- אל תתייחס לסעיפי הגבלת אחריות סטנדרטיים (סעיפים 40-46 ב"גורמים ושיקולים")
- אל תדווח על שדות שמולאו כראוי
- אל תדווח על טענות עובדתיות שאינך יכול לאמת (נתוני תב"ע, מספרי היתרים, בעלויות)
- דווח רק על ממצאים ממשיים — אל תמלא ממצאים לשם מראית עין
- suggestion הוא חובה עבור phrasing ו-punctuation, ו-null עבור שאר הסוגים

החזר JSON בלבד — ללא טקסט נוסף לפני או אחרי:
{
  "findings": [
    {
      "paragraph_index": <integer>,
      "category": "logic" | "missing" | "spelling" | "phrasing" | "punctuation",
      "severity": "high" | "medium" | "low",
      "comment": "<תיאור הבעיה בעברית, קצר ומקצועי>",
      "suggestion": "<ניסוח חלופי מוכן לשימוש, או null>"
    }
  ]
}
```

**User message format:**
```
[0] תוכן ענינים...
[1] מטרת חוות הדעת...
[2] נתבקשתי על ידי...
...
```

### 5.4 Pydantic Schema

```python
from pydantic import BaseModel
from typing import Literal, Optional

class Finding(BaseModel):
    paragraph_index: int
    category: Literal["logic", "missing", "spelling", "phrasing", "punctuation"]
    severity: Literal["high", "medium", "low"]
    comment: str           # What's wrong — always required
    suggestion: Optional[str] = None  # Alternative wording — required for phrasing + punctuation
```

### 5.5 Comment Injection

For each finding:

**Step 1 — Create comment:**
```bash
python scripts/comment.py unpacked/ <id> "<formatted_comment>" --author "רמי סויצקי"
```

**Step 2 — Add markers to document.xml:**
```xml
<!-- CORRECT: markers are SIBLINGS of <w:r> -->
<w:commentRangeStart w:id="N"/>
<w:r><w:t>paragraph text</w:t></w:r>
<w:commentRangeEnd w:id="N"/>
<w:r>
  <w:rPr><w:rStyle w:val="CommentReference"/></w:rPr>
  <w:commentReference w:id="N"/>
</w:r>

<!-- WRONG — breaks Word silently: -->
<w:r><w:commentRangeStart w:id="N"/>...</w:r>
```

**Comment text format (with suggestion):**

```python
def format_comment(finding: Finding) -> str:
    emoji_map = {
        "logic":       "🔍 עקביות",
        "missing":     "📋 חסר",
        "spelling":    "✍️ כתיב",
        "phrasing":    "🗣️ ניסוח",
        "punctuation": "✏️ פיסוק",
    }
    prefix = emoji_map[finding.category]
    text = f"{prefix}: {finding.comment}"
    if finding.suggestion:
        text += f"\n\n💡 הצעה: {finding.suggestion}"
    return text
```

**Example comment output in Word:**
```
🗣️ ניסוח: המשפט אינו חד-משמעי לגבי היקף הזכויות הנישומות

💡 הצעה: "הזכויות הנישומות כוללות את מלוא זכויות הבעלות בחלקה, לרבות יתרת זכויות הבניה הלא ממומשות."
```

```
✏️ פיסוק: חסר פסיק לאחר "לתאריך הקובע" — המשפט עלול להתפרש שלא כנדרש

💡 הצעה: "השומה נכונה לתאריך הקובע, ולא לכל מועד אחר."
```

### 5.6 Output

File: `[original_filename]_reviewed.docx`

Screen summary:
```
✅ Review complete.

Found N issues:
🔍 Logic/Consistency: N
📋 Missing content: N
✍️ Spelling clusters: N
🗣️ Phrasing issues: N  (N with suggested rewrites)
✏️ Punctuation: N  (N with suggested fixes)

By severity — High: N | Medium: N | Low: N

Download your reviewed report — comments include suggested rewrites 
where applicable. Click any comment in Word to see the suggestion.
```

---

## 6. FILE STRUCTURE

```
appraisal-automation/
├── app.py                  # Streamlit frontend
├── stage1_inject.py        # Stage 1: cover extraction + global replace
├── stage2_review.py        # Stage 2: Claude API call + comment injection
├── field_extractor.py      # Dynamic cover page field extraction
├── comment_injector.py     # OOXML comment injection + formatting
├── docx_utils.py           # Shared: unpack/pack wrappers, XML helpers
├── config.py               # Model, author name, API keys
├── scripts/
│   └── office/
│       ├── unpack.py       # DOCX skill library
│       ├── pack.py         # DOCX skill library
│       └── comment.py      # DOCX skill library
├── requirements.txt
└── README.md
```

---

## 7. CONFIGURATION (config.py)

```python
# Model — switch here to A/B test
REVIEW_MODEL = "claude-sonnet-4-6"
# Options: "claude-opus-4-6", "claude-sonnet-4-6"

# Comment author
COMMENT_AUTHOR = "רמי סויצקי"

# Max tokens for review
REVIEW_MAX_TOKENS = 10000

# API key — load from environment
import os
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Output naming
STAGE1_SUFFIX = "_filled"
STAGE2_SUFFIX = "_reviewed"
```

---

## 8. REQUIREMENTS (requirements.txt)

```
anthropic>=0.40.0
python-docx>=1.1.0
pydantic>=2.0.0
lxml>=5.0.0
streamlit>=1.35.0
```

---

## 9. KEY TECHNICAL CONSTRAINTS

1. **Hebrew RTL preservation** — never strip or modify `bidi`, `rtl`, or `cs` XML attributes. Always use `xml:space="preserve"` on `<w:t>` with leading/trailing whitespace.

2. **Run merging** — Hebrew DOCX text is often split across multiple `<w:r>` runs. `unpack.py` merges adjacent runs automatically. Always unpack before searching.

3. **Partial match protection** — numeric values like `458` must not replace `4580` or `1458`. Check surrounding characters before replacing.

4. **Dynamic field detection** — do NOT hardcode the field list. Scan all label:value pairs from the cover. This handles new field types without code changes.

5. **Never edit comment XML manually** — always use `comment.py`. It manages IDs and relationships across all 4 required XML files.

6. **No invented data** — if a field is not found on the cover, show `⚠️ EMPTY`. Never guess.

7. **One comment per paragraph max for spelling** — do not create multiple spelling comments on the same paragraph.

8. **Structured output only** — Stage 2 must use Anthropic Structured Outputs API (JSON schema validation), not free-text parsing.

9. **Do NOT use python-docx for XML editing** — it destroys RTL formatting on save. Use unpack/edit XML/repack exclusively.

10. **Do NOT add colored highlighting** (red/yellow/green) to document text in Stage 2 — Word Comments only.

11. **suggestion field** — required for `phrasing` and `punctuation` findings. Must be a complete, ready-to-use Hebrew sentence, not a description of what to write.

---

## 10. TESTING CHECKLIST

**Stage 1:**
- [ ] Upload Type A → correct fields extracted dynamically
- [ ] Upload Type B (היטל השבחה) → extra fields appear (המבקשים, שכונה)
- [ ] Upload report with unexpected new field → it appears in the form
- [ ] All values replaced in body, tables, headers, footers
- [ ] Numeric partial match: `458` does NOT replace inside `14580`
- [ ] Missing field shows ⚠️ EMPTY, not blank or error
- [ ] Replacement count per field shown after processing
- [ ] Download: opens in Word with no corruption, RTL preserved

**Stage 2:**
- [ ] Upload filled document → Claude API called exactly once
- [ ] All 5 categories working: logic, missing, spelling, phrasing, punctuation
- [ ] `suggestion` field populated for phrasing + punctuation findings
- [ ] `suggestion` is null for logic + missing + spelling findings
- [ ] Comments appear in Word at correct paragraphs
- [ ] Comment author shows "רמי סויצקי"
- [ ] Emoji prefix on each comment
- [ ] Suggestion appears after blank line with 💡 prefix
- [ ] Document opens without error in Word
- [ ] RTL direction preserved throughout

---

## 11. SAMPLE DATA FOR TESTING

**Type A cover:**
```
שומת נכס מקרקעין מלאה
גוש: 6623   חלקה: 458
רחוב אשכנזי 80
תל אביב
מזמין השומה: הועדה המקומית תל אביב
מספר תיק: 12005-2025
```

**Type B cover:**
```
היטל השבחה
גוש: 6854   חלקה: 41   תת חלקה: 2
הסלע 1 כניסה ב'
שכונת המגורים "ורדים"
שוהם
מזמין השומה: הועדה המקומית שוהם
המבקשים: יוחאי פנחס פרסר
מספר תיק: 2026-00330
```

---

## 12. DEVELOPER NOTES

- **Do NOT chain Stage 1 → Stage 2 automatically.** Appraiser works manually between stages.
- **Stage 1 is pure string replacement** — no AI call needed, no API cost.
- **Stage 2 is one API call** — the entire document goes in, structured JSON comes out.
- The `suggestion` field is what makes Stage 2 genuinely useful vs. just flagging problems. Prioritize getting this right.
- Run the Streamlit app locally first, deploy to Streamlit Cloud only when both stages are verified working.
