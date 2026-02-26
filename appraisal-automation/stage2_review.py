"""
stage2_review.py
Stage 2: Send document to Claude API → receive structured JSON findings
         → inject as Word comments → return reviewed DOCX.

One API call per document. Uses Anthropic Structured Outputs (Pydantic schema).
"""
import os
import io
import sys
import json
import shutil
import tempfile
from typing import Optional

from pydantic import BaseModel
from typing import Literal

import anthropic
try:
    import openai as _openai_module
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

try:
    from google import genai as _gemini_module
    from google.genai import types as _gemini_types
    _GEMINI_AVAILABLE = True
except ImportError:
    _GEMINI_AVAILABLE = False

from config import (
    ANTHROPIC_API_KEY,
    OPENAI_API_KEY,
    GEMINI_API_KEY,
    REVIEW_MODEL,
    OPENAI_REVIEW_MODEL,
    GEMINI_REVIEW_MODEL,
    REVIEW_MAX_TOKENS,
    TEMP_DIR,
    STAGE2_SUFFIX,
)
from docx_utils import docx_unpack, docx_pack_safe, get_paragraph_texts
from comment_injector import inject_all_comments, build_summary


# ── Pydantic Schema for structured output ─────────────────────────────────────
# Field names here MUST match exactly what the system prompt instructs Claude
# to produce. Any rename here requires a matching rename in SYSTEM_PROMPT below.

class Finding(BaseModel):
    paragraph_index: int                 # index of paragraph in the document
    category: Literal[                   # class of issue
        "logic", "missing", "spelling", "phrasing", "punctuation"
    ]
    severity: Literal["high", "medium", "low"]
    comment: str                         # always required — explain the issue
    suggestion: Optional[str] = None     # required for phrasing/punctuation, null otherwise


class ReviewResponse(BaseModel):
    findings: list[Finding]


# ── System Prompt ─────────────────────────────────────────────────────────────
# CRITICAL: the JSON schema block at the bottom of this prompt MUST stay in
# sync with the Pydantic models above. Field names must be identical.

SYSTEM_PROMPT = """\
אתה שמאי מקרקעין בכיר עם 20 שנות ניסיון, עורך ביקורת עמיתים על דוח שומה לפני הגשה לבנק או לועדה המקומית.

תפקידך לזהות בעיות מהותיות שחשוב לטפל בהן לפני הגשה.

בדוק את הדברים הבאים:

1. עקביות לוגית — האם המסקנה הסופית תואמת את הנתונים המוצגים? האם יש סתירות בין חלקים שונים בדוח (שטחים, ערכים, גוש/חלקה)?

2. פערים וחסרים — האם חסרים סעיפים נדרשים? האם יש שדות שנותרו ריקים (_____)? האם סעיף 14 (נתונים השוואתיים) ריק? האם סעיף 15 (תחשיבים) מולא?

3. ריכוז שגיאות כתיב — אם בפסקה מסוימת יש מספר שגיאות כתיב — כתוב הערה אחת על הפסקה כולה, עם ציון המילים הבעייתיות.

4. ניסוח בעייתי — משפטים שניתן לקרוא בשתי דרכים, שפה לא פורמלית, ניסוח שעלול ליצור חשיפה משפטית. הצע ניסוח חלופי בשדה suggestion.

5. סימני פיסוק — זהה מקומות שבהם חסר פסיק, נקודה, או שימוש שגוי. הצע את הטקסט המתוקן בשדה suggestion.

כללים:
- אל תתייחס לסעיפי הגבלת אחריות סטנדרטיים (סעיפים 40-46)
- אל תדווח על שדות שמולאו כראוי
- אל תדווח על טענות עובדתיות שאינך יכול לאמת
- דווח רק על ממצאים ממשיים
- suggestion חובה עבור phrasing ו-punctuation, ו-null עבור שאר הסוגים

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
פורמט פלט — JSON בלבד, ללא שום טקסט לפני או אחרי
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

החזר אובייקט JSON עם מבנה זה בדיוק. שמות השדות הם אנגלית בלבד, כפי שרשום:

{
  "findings": [
    {
      "paragraph_index": <מספר שלם — אינדקס הפסקה מהקלט>,
      "category": <אחד מ: "logic", "missing", "spelling", "phrasing", "punctuation">,
      "severity": <אחד מ: "high", "medium", "low">,
      "comment": "<הסבר הממצא בעברית>",
      "suggestion": "<הצעה לתיקון בעברית, או null>"
    }
  ]
}

⚠️  שמות השדות המדויקים — אסור לשנות:
  paragraph_index  ← לא: id / index / para / paragraph_id
  category         ← לא: type / kind / issue_type / type_of_issue
  severity         ← לא: level / priority / importance / urgency
  comment          ← לא: description / text / message / finding / note / details
  suggestion       ← לא: fix / replacement / correction / proposed_text / alternative

דוגמה לפלט תקין:
{
  "findings": [
    {
      "paragraph_index": 14,
      "category": "spelling",
      "severity": "low",
      "comment": "שגיאות כתיב: 'השיבה' במקום 'השבה', 'הגבה' במקום 'הגבהה'",
      "suggestion": null
    },
    {
      "paragraph_index": 27,
      "category": "phrasing",
      "severity": "medium",
      "comment": "הניסוח עמום ועלול להתפרש בשתי דרכים שונות",
      "suggestion": "הנכס הנדון הועבר לבעלות המבקש בשנת 2021 על פי נסח הטאבו."
    }
  ]
}"""


def _format_paragraphs_for_prompt(paragraphs: list[str]) -> str:
    """Format paragraph list as indexed text for the API user message."""
    lines = []
    for idx, text in enumerate(paragraphs):
        if text.strip():
            lines.append(f"[{idx}] {text}")

    # Add paragraph count header to help Claude estimate scope
    non_empty_count = len(lines)
    header = f"להלן {non_empty_count} פסקאות לבדיקה:\n\n"
    return header + "\n".join(lines)


def _call_claude_api(paragraph_text: str) -> list[dict]:
    """
    Make a single Claude API call and return list of finding dicts.
    Validates response against the Pydantic schema.
    Uses streaming to reduce perceived wait time.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Use streaming for faster perceived response
    raw_text = ""
    with client.messages.stream(
        model=REVIEW_MODEL,
        max_tokens=REVIEW_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": paragraph_text,
            }
        ],
    ) as stream:
        for text in stream.text_stream:
            raw_text += text

    # Strip any preamble/postamble Claude might add despite instructions
    raw_text = raw_text.strip()
    start = raw_text.find("{")
    end   = raw_text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found in Claude response:\n{raw_text[:500]}")

    json_str = raw_text[start:end]

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Claude returned invalid JSON: {e}\n\nRaw output:\n{json_str[:500]}"
        )

    # Validate with Pydantic — raises a descriptive error if field names mismatch
    try:
        response = ReviewResponse(**data)
    except Exception as e:
        # Show exactly which keys Claude sent so the error is actionable
        first_finding = data.get("findings", [{}])[0] if data.get("findings") else {}
        received_keys = list(first_finding.keys())
        expected_keys = ["paragraph_index", "category", "severity", "comment", "suggestion"]
        raise ValueError(
            f"Claude JSON schema mismatch.\n"
            f"Expected fields : {expected_keys}\n"
            f"Received fields : {received_keys}\n"
            f"Pydantic error  : {e}"
        )

    return [f.model_dump() for f in response.findings]


def _call_openai_api(paragraph_text: str) -> list[dict]:
    """
    Make a single OpenAI API call and return list of finding dicts.
    Uses the same SYSTEM_PROMPT and JSON format as the Claude version.
    Validates response against the same Pydantic schema.
    """
    if not _OPENAI_AVAILABLE:
        raise ImportError(
            "openai package is not installed. Run: pip install openai>=1.0.0"
        )
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set.")

    client = _openai_module.OpenAI(api_key=OPENAI_API_KEY)

    completion = client.chat.completions.create(
        model=OPENAI_REVIEW_MODEL,
        response_format={"type": "json_object"},
        max_completion_tokens=REVIEW_MAX_TOKENS,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": paragraph_text},
        ],
    )

    raw_text = (completion.choices[0].message.content or "").strip()
    start = raw_text.find("{")
    end   = raw_text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found in OpenAI response:\n{raw_text[:500]}")

    json_str = raw_text[start:end]

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"OpenAI returned invalid JSON: {e}\n\nRaw output:\n{json_str[:500]}"
        )

    try:
        validated = ReviewResponse(**data)
    except Exception as e:
        first_finding = data.get("findings", [{}])[0] if data.get("findings") else {}
        received_keys = list(first_finding.keys())
        expected_keys = ["paragraph_index", "category", "severity", "comment", "suggestion"]
        raise ValueError(
            f"OpenAI JSON schema mismatch.\n"
            f"Expected fields : {expected_keys}\n"
            f"Received fields : {received_keys}\n"
            f"Pydantic error  : {e}"
        )

    return [f.model_dump() for f in validated.findings]


def _call_gemini_api(paragraph_text: str) -> list[dict]:
    """
    Make a single Gemini API call and return list of finding dicts.
    Uses the same SYSTEM_PROMPT.
    Validates response against the same Pydantic schema.
    """
    if not _GEMINI_AVAILABLE:
        raise ImportError(
            "google-genai package is not installed. Run: pip install -U google-genai"
        )
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set.")

    client = _gemini_module.Client(api_key=GEMINI_API_KEY)

    response = client.models.generate_content(
        model=GEMINI_REVIEW_MODEL,
        contents=paragraph_text,
        config=_gemini_types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )

    raw_text = response.text.strip()

    # Strip any potential markdown wrappers (Gemini sometimes adds them)
    if raw_text.startswith("```json"):
        raw_text = raw_text[7:]
    if raw_text.startswith("```"):
        raw_text = raw_text[3:]
    if raw_text.endswith("```"):
        raw_text = raw_text[:-3]
    raw_text = raw_text.strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Gemini returned invalid JSON: {e}\n\nRaw output:\n{raw_text[:500]}"
        )

    try:
        validated = ReviewResponse(**data)
    except Exception as e:
        first_finding = data.get("findings", [{}])[0] if data.get("findings") else {}
        received_keys = list(first_finding.keys())
        expected_keys = ["paragraph_index", "category", "severity", "comment", "suggestion"]
        raise ValueError(
            f"Gemini JSON schema mismatch.\n"
            f"Expected fields : {expected_keys}\n"
            f"Received fields : {received_keys}\n"
            f"Pydantic error  : {e}"
        )

    return [f.model_dump() for f in validated.findings]


def run_stage2(file_obj, api_provider: str = "anthropic") -> tuple[str, str]:
    """
    Execute Stage 2 pipeline (non-generator version for backward compatibility).

    Args:
        file_obj:     Streamlit UploadedFile or file-like object with completed DOCX.
        api_provider: "anthropic" (default) or "openai"

    Returns:
        (output_docx_path, summary_text)
    """
    result = None
    for item in run_stage2_with_progress(file_obj, api_provider=api_provider):
        if isinstance(item, tuple):
            result = item
    return result


from section_mapper import SectionMapper
from agents.reviewer import MultiAgentReviewer

def run_stage2_with_progress(file_obj, api_provider: str = "anthropic"):
    """
    Execute Stage 2 pipeline with progress updates.
    Supports both legacy single-agent and new multi-agent review.
    """
    # ... (API key validation logic preserved) ...
    if api_provider == "openai":
        if not OPENAI_API_KEY: raise ValueError("OPENAI_API_KEY is not set.")
    elif api_provider == "gemini":
        if not GEMINI_API_KEY: raise ValueError("GEMINI_API_KEY is not set.")
    elif api_provider == "multi":
        if not OPENAI_API_KEY or not GEMINI_API_KEY:
            raise ValueError("Multi-agent review requires both OPENAI_API_KEY and GEMINI_API_KEY.")
    else:
        if not ANTHROPIC_API_KEY: raise ValueError("ANTHROPIC_API_KEY is not set.")

    # ── Step 1: Extract text & Map Sections ──────────────────────────────────
    yield "📄 מנתח מבנה מסמך וממפה סעיפים..."

    original_name = _get_original_name(file_obj)
    with tempfile.NamedTemporaryFile(dir=TEMP_DIR, suffix=".docx", delete=False) as tmp:
        tmp.write(_read_bytes(file_obj))
        src_path = tmp.name

    unpack_dir = src_path.replace(".docx", "_s2_unpacked")
    docx_unpack(src_path, unpack_dir)

    # Build section map
    mapper = SectionMapper(unpack_dir)
    mapper.load()
    section_map = mapper.build_map()

    paragraphs = get_paragraph_texts(unpack_dir)
    prompt_text = _format_paragraphs_for_prompt(paragraphs)

    # -- Step 2: Call AI API (Single or Multi) --------------------------------
    debug_info = ""
    if api_provider == "multi":
        yield "🤖 מריץ ביקורת רב-סוכנית (ניסוח, כתיב ועקביות)..."
        reviewer = MultiAgentReviewer()
        findings = reviewer.run_review(prompt_text)
        debug_info = reviewer.get_debug_summary()
    elif api_provider == "openai":
        yield "🤖 שולח לביקורת GPT-4o..."
        findings = _call_openai_api(prompt_text)
    elif api_provider == "gemini":
        yield "🤖 שולח לביקורת Gemini 2.0 Flash..."
        findings = _call_gemini_api(prompt_text)
    else:
        yield "🤖 שולח לביקורת Claude..."
        findings = _call_claude_api(prompt_text)

    # Attach section labels to findings for better reporting
    for f in findings:
        idx = f.get("paragraph_index")
        if idx is not None and idx in section_map:
            f["section_label"] = section_map[idx]

    # ── Step 3: Inject comments ───────────────────────────────────────────────
    yield "💬 מזריק הערות למסמך..."

    inject_all_comments(unpack_dir, findings)

    # ── Build output summary ──────────────────────────────────────────────────
    summary = build_summary(findings)
    if debug_info:
        summary += "\n\n" + debug_info

    # ── Repack ────────────────────────────────────────────────────────────────
    stem        = _stem(original_name)
    output_name = stem + STAGE2_SUFFIX + ".docx"
    output_path = os.path.join(TEMP_DIR, output_name)
    _STAGE2_MODIFIED_FILES = ["word/document.xml", "word/comments.xml"]
    docx_pack_safe(unpack_dir, output_path, validate_files=_STAGE2_MODIFIED_FILES)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    shutil.rmtree(unpack_dir, ignore_errors=True)
    os.unlink(src_path)

    yield "✅ הביקורת הושלמה!"
    yield (output_path, summary)


def _get_original_name(file_obj) -> str:
    if hasattr(file_obj, "name"):
        return os.path.basename(file_obj.name)
    return "report.docx"


def _stem(filename: str) -> str:
    base = os.path.basename(filename)
    return os.path.splitext(base)[0]


def _read_bytes(file_obj) -> bytes:
    if hasattr(file_obj, "read"):
        data = file_obj.read()
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        return data
    with open(file_obj, "rb") as f:
        return f.read()
