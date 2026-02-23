# Savitzky Appraisal Automation

> **סויצקי רמי שמאות מקרקעין וניהול בע"מ** | Two-stage DOCX automation for Hebrew real estate appraisal reports.

---

## Overview

This tool automates two distinct workflows for Israeli real estate appraisal reports:

| Stage | What it does |
|-------|-------------|
| **Stage 1 — Fill Report** | Dynamically extracts all label:value pairs from the cover page, presents an editable confirmation form, and performs a global find-and-replace throughout the entire document (body, tables, headers, footers). |
| **Stage 2 — Review Report** | Sends the completed document to Claude AI for peer review. Findings are injected as native Word comments anchored to specific paragraphs, with suggested rewrites where applicable. |

**Critical:** Stage 1 output and Stage 2 input are **separate uploads**. The appraiser works on the document manually between stages.

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set your Anthropic API key

```bash
# Windows (PowerShell)
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# Or create a .env file (never commit this)
```

### 3. Run the app

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`

---

## File Structure

```
appraisal-automation/
├── app.py                  # Streamlit frontend (RTL Hebrew UI)
├── stage1_inject.py        # Stage 1: cover extraction + global replace
├── stage2_review.py        # Stage 2: Claude API call + comment injection
├── field_extractor.py      # Dynamic cover page field extraction
├── comment_injector.py     # Comment batching + formatting
├── docx_utils.py           # Shared: unpack/pack wrappers, XML helpers
├── config.py               # Model, author name, API keys
├── scripts/
│   └── office/
│       ├── unpack.py       # DOCX → XML directory (merges Hebrew runs)
│       ├── pack.py         # XML directory → DOCX
│       └── comment.py      # OOXML comment injection (manages 4 XML files)
├── requirements.txt
└── README.md
```

---

## Configuration

Edit `config.py` to change:

| Setting | Default | Notes |
|---------|---------|-------|
| `REVIEW_MODEL` | `claude-3-5-sonnet-20241022` | Switch to `claude-opus-4-6` for deeper analysis |
| `REVIEW_MAX_TOKENS` | `10000` | Increase for very long documents |
| `COMMENT_AUTHOR` | `רמי סויצקי` | Appears in Word comment bubble |
| `STAGE1_SUFFIX` | `_filled` | Output filename suffix |
| `STAGE2_SUFFIX` | `_reviewed` | Output filename suffix |

---

## Key Technical Notes

1. **Hebrew RTL preservation** — All XML editing preserves `bidi`, `rtl`, `cs` attributes and uses `xml:space="preserve"`. Never uses python-docx for editing (destroys RTL on save).

2. **Run merging** — Hebrew DOCX text is often split across multiple `<w:r>` runs. `unpack.py` merges adjacent identical-format runs before any string search.

3. **Numeric partial match protection** — `458` will not replace inside `4580` or `14580`. Checked by examining surrounding characters.

4. **Comments use 4 XML files** — `comment.py` manages `comments.xml`, `document.xml`, `[Content_Types].xml`, and `_rels/document.xml.rels` as required by the OOXML spec.

5. **One spelling comment per paragraph** — Multiple spelling errors in the same paragraph are reported in a single comment listing all problem words.

---

## Document Types Supported

| Type | Detection | Extra Fields |
|------|-----------|-------------|
| **Type A** — Standard (שומת נכס מקרקעין) | Title contains שומה | — |
| **Type B** — Betterment (היטל השבחה) | Title contains היטל השבחה | המבקשים, שכונה, סלע/כניסה |
| **Type C** — Correction (תיקון שומה) | Title contains תיקון שומה | Original file number reference |

---

## Deployment

### Local (default)
```bash
streamlit run app.py
```

### Streamlit Cloud (free, 2-3 users)
1. Push to GitHub
2. Connect at [streamlit.io/cloud](https://streamlit.io/cloud)
3. Add `ANTHROPIC_API_KEY` in **App Settings → Secrets**

### DigitalOcean / Railway ($5/mo)
```bash
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

---

## Testing Checklist

### Stage 1
- [ ] Upload Type A → correct fields extracted dynamically
- [ ] Upload Type B (היטל השבחה) → extra fields appear
- [ ] Unexpected new field → it appears in the form
- [ ] All values replaced in body, tables, headers, footers
- [ ] Numeric partial match: `458` does NOT replace inside `14580`
- [ ] Missing field shows ⚠️ EMPTY
- [ ] Replacement count per field shown after processing
- [ ] Download: opens in Word, RTL preserved

### Stage 2
- [ ] Claude API called exactly once per document
- [ ] All 5 categories working: logic, missing, spelling, phrasing, punctuation
- [ ] `suggestion` populated for phrasing + punctuation
- [ ] `suggestion` is null for logic + missing + spelling
- [ ] Comments appear at correct paragraphs in Word
- [ ] Comment author shows "רמי סויצקי"
- [ ] Emoji prefix on each comment
- [ ] Document opens without error in Word
- [ ] RTL preserved throughout
