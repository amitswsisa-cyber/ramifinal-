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
import logging
import shutil
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)

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
    get_api_key,
    REVIEW_MODEL,
    OPENAI_REVIEW_MODEL,
    OPENAI_DOCX_REVIEW_MODEL,
    GEMINI_REVIEW_MODEL,
    GEMINI_FULL_REVIEW_MODEL,
    SPELLING_ONLY_MODEL,
    REVIEW_MAX_TOKENS,
    TEMP_DIR,
    STAGE2_SUFFIX,
)
from docx_utils import docx_unpack, docx_pack_safe, get_paragraph_texts, get_rich_markdown
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

# Pre-compute the JSON schema dict for Gemini API calls.
# Passing the Pydantic class directly (ModelMetaclass) fails serialization
# on some google-genai SDK versions, so we pass the dict instead.
_REVIEW_RESPONSE_SCHEMA = ReviewResponse.model_json_schema()


# ── Dual-Agent Prompts for gemini_full (parallel calls) ───────────────────────
# Used exclusively by _call_gemini_full_api.
# LOGIC_PROMPT: arithmetic, cross-section contradictions, missing mandatory fields, dates.
# LANGUAGE_PROMPT: Hebrew phrasing quality, grammar, spelling, punctuation.

LOGIC_PROMPT = """\
אתה שמאי מקרקעין בכיר, עורך ביקורת QA על דוח שומה.
תפקידך הבלעדי: בעיות לוגיות, אריתמטיות, וחסרים מבניים. אל תתייחס לניסוח או לשפה.

בדוק אך ורק:
1. עקביות לוגית (category: "logic"):
   - השווה שטחים/ערכים/גוש-חלקה בסיכום מול החלק המפורט.
   - בדוק טעויות אריתמטיות בטבלאות.
2. חסרים — שדות חובה (category: "missing", severity: "high"):
   - תב"ע, תאריך סיור, נסח טאבו, הצהרת שמאי, תנאים מגבילים, סעיפים 14-15.
3. תאריכים (category: "logic"):
   - סיור מעל 6 חודשים לפני התאריך הקובע = "high".
   - עסקאות השוואה מעל 3 שנים ללא הסבר = דווח.
   - אל תסמן תאריכים כעתידיים אלא אם אחרי 2026.
4. ערכים עגולים ללא חישוב מפורט: category: "logic", severity: "low".

פלט — JSON בלבד:
{"findings": [{"paragraph_index": <int>, "category": "logic"|"missing", "severity": "high"|"medium"|"low", "comment": "<עברית>", "suggestion": "<תיקון או null>"}]}
כלל אינדקס: השתמש רק במספרים מטבלת האינדקס. אל תדווח על שדות תקינים או סעיפי הגבלת אחריות.\
"""

LANGUAGE_PROMPT = """\
אתה עורך לשוני בכיר לדוחות שמאות מקרקעין בעברית.
תפקידך: ניסוח, דקדוק, כתיב ופיסוק בלבד. אל תתייחס ללוגיקה, מספרים, או נתונים.
★ לפחות 40% מהממצאים חייבים להיות phrasing. אם לא מצאת מספיק — סרוק שוב.

1. ניסוח (category: "phrasing") — זהה:
   - "יצוין כי"/"יובהר כי"/"ראוי לציין" — החלף בניסוח ישיר.
   - סביל מיותר, "וכו'", ערבוב "שווי"/"מחיר"/"ערך", ניסוח מטיל ספק ("ככל הנראה").
   - כותרת שלא תואמת תוכן, משפטים דו-משמעיים, חזרות, משפטים ארוכים.
   ★ חובה suggestion עם ניסוח חלופי מלא.

2. כתיב (category: "spelling"):
   - שגיאות כתיב, מגדר, התאמת פועל, סמיכות. הערה אחת לפסקה.
   - פורמט קצר בשדה comment: "מילה שגויה ← מילה נכונה".
   - אל תדווח על בעיות רווחים (כפולים או חסרים).

3. פיסוק (category: "punctuation"):
   - פסיק/נקודה חסרים, פיסוק שגוי. suggestion חובה.

פלט — JSON בלבד:
{"findings": [{"paragraph_index": <int>, "category": "phrasing"|"spelling"|"punctuation", "severity": "high"|"medium"|"low", "comment": "<עברית>", "suggestion": "<חובה>"}]}
כלל אינדקס: השתמש רק במספרים מטבלת האינדקס. אל תדווח על סעיפים 40-46.\
"""

SPELLING_ONLY_PROMPT = """\
אתה עורך לשוני מומחה לעברית, בודק כתיב ודקדוק בדוחות שמאות.
תפקידך: כתיב, דקדוק ופיסוק בלבד. אל תתייחס לניסוח, סגנון, לוגיקה או תוכן.

1. כתיב ודקדוק (category: "spelling"):
   - מילים שגויות, אותיות חסרות/מיותרות, הקלדה שגויה.
   - אי-התאמה במין/מספר, סמיכות שגויה.
   - פורמט comment קצר: "מילה שגויה ← מילה נכונה". אל תסביר מדוע.
   - suggestion חובה: המילה/המשפט המתוקן.
   - הערה אחת לפסקה אם יש מספר שגיאות.
2. פיסוק (category: "punctuation"):
   - נקודה/פסיק חסרים, סוגריים פתוחים, פיסוק שגוי.
   - suggestion חובה: הטקסט עם הפיסוק הנכון.

כללים:
• אל תמציא ממצאים. טקסט תקין = findings ריקה.
• אל תתייחס לניסוח — כתיב ודקדוק בלבד.
• אל תדווח על רווחים כפולים או חסרים.
• התעלם משמות פרטיים, כתובות, מספרי גוש/חלקה/תכניות.
• severity: "low" לרוב. "medium" רק אם משנה משמעות.

פלט — JSON בלבד:
{"findings": [{"paragraph_index": <int>, "category": "spelling"|"punctuation", "severity": "high"|"medium"|"low", "comment": "<מילה שגויה ← מילה נכונה>", "suggestion": "<תיקון — חובה>"}]}
כלל אינדקס: השתמש רק במספרים מטבלת האינדקס.\
"""


# ── System Prompt ─────────────────────────────────────────────────────────────
# CRITICAL: the JSON schema block at the bottom of this prompt MUST stay in
# sync with the Pydantic models above. Field names must be identical.

SYSTEM_PROMPT = """\
אתה שמאי מקרקעין בכיר בישראל, עורך ביקורת עמיתים על דוח שומה.
תפקידך: לזהות כל בעיה — מהותית, לשונית, או מבנית — ולהציע תיקון קונקרטי.

בדוק (לפי סדר עדיפות):
1. עקביות לוגית (category: "logic"):
   - השווה שטחים/ערכים/גוש-חלקה בסיכום מול החלק המפורט.
   - בדוק חישובים בטבלאות. ערכים עגולים ללא חישוב = severity: "low".
2. חסרים (category: "missing", severity: "high"):
   - תב"ע, תאריך סיור, נסח טאבו, הצהרת שמאי, תנאים מגבילים, סעיפים 14-15, שדות ריקים.
3. תאריכים (category: "logic"):
   - סיור מעל 6 חודשים = "high". עסקאות מעל 3 שנים ללא הסבר = דווח.
4. ניסוח (category: "phrasing"):
   - דו-משמעות, שפה לא מקצועית, חזרות, משפטים ארוכים. suggestion חובה עם ניסוח חלופי.
5. כתיב (category: "spelling"):
   - הערה אחת לפסקה. פורמט קצר: "מילה שגויה ← מילה נכונה". אל תדווח על רווחים.
6. פיסוק (category: "punctuation"):
   - פסיק/נקודה חסרים. suggestion חובה.

כלל suggestion: חובה לכל ממצא. null רק אם נדרש מידע חיצוני.
כללים: אל תדווח על סעיפים 40-46, שדות תקינים, או טענות שאינך יכול לאמת.

כלל אינדקס: השתמש רק במספרים מטבלת האינדקס. "(table cell)" = תא טבלה. "(empty)" = דלג, השתמש בפסקה הלא-ריקה שלפניה.

פלט — JSON בלבד:
{"findings": [{"paragraph_index": <int>, "category": "logic"|"missing"|"spelling"|"phrasing"|"punctuation", "severity": "high"|"medium"|"low", "comment": "<עברית>", "suggestion": "<תיקון או null>"}]}"""


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


# ── Hand-written strict-mode schema for OpenAI Responses API ─────────────────
# OpenAI strict=True requires ALL properties to appear in "required" — even
# optional ones.  The field's *value* can still be null (via anyOf).
# Do NOT use ReviewResponse.model_json_schema(): Pydantic omits Optional fields
# from "required", which OpenAI strict mode rejects.
_OPENAI_STRICT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "paragraph_index",
                    "category",
                    "severity",
                    "comment",
                    "suggestion",    # must be present; value may be null
                ],
                "properties": {
                    "paragraph_index": {"type": "integer"},
                    "category": {
                        "type": "string",
                        "enum": ["logic", "missing", "spelling", "phrasing", "punctuation"],
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                    "comment": {"type": "string"},
                    "suggestion": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "null"},
                        ]
                    },
                },
            }
        }
    },
}


def _build_index_map(unpacked_dir: str) -> tuple[list[str], str]:
    """
    Parse document.xml and return (paragraphs_list, index_map_string).

    Labels every paragraph with its exact XML index — the same index used by
    inject_comments_batch — so the AI can return paragraph_index values that
    map 1:1 to the XML without any drift.  Table-cell paragraphs are flagged
    explicitly so the AI understands the document structure.
    """
    from lxml import etree

    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    W    = f"{{{W_NS}}}"

    doc_path = os.path.join(unpacked_dir, "word", "document.xml")
    tree = etree.parse(doc_path)
    root = tree.getroot()

    all_paras = list(root.iter(f"{W}p"))

    # Build set of table-cell paragraph element ids
    table_para_ids: set[int] = set()
    for tc in root.iter(f"{W}tc"):
        for p in tc.iter(f"{W}p"):
            table_para_ids.add(id(p))

    texts: list[str] = []
    rows:  list[str] = []

    for idx, para in enumerate(all_paras):
        parts = [t.text or "" for t in para.iter(f"{W}t")]
        text = "".join(parts)
        texts.append(text)

        is_table = id(para) in table_para_ids
        prefix   = "(table cell) " if is_table else ""

        if text.strip():
            display = text[:120] + ("..." if len(text) > 120 else "")
            rows.append(f"[{idx}] {prefix}{display}")
        else:
            rows.append(f"[{idx}] (empty)")

    return texts, "\n".join(rows)


def _call_openai_docx_api(file_bytes: bytes, unpacked_dir: str) -> list[dict]:
    """
    Upload the .docx to the OpenAI Files API and run a single Responses API
    call with Structured Outputs (strict=True).  Builds the paragraph index map
    in parallel with the upload so neither blocks the other.

    Uses client.responses.create (Responses API), NOT chat.completions —
    only the Responses API supports file inputs.

    Returns a validated list of finding dicts.
    """
    import concurrent.futures

    if not _OPENAI_AVAILABLE:
        raise ImportError("openai package is not installed. Run: pip install openai>=1.68.0")
    api_key = get_api_key("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set.")

    client = _openai_module.OpenAI(api_key=api_key)

    # Upload and index-map building run in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        upload_future = executor.submit(
            client.files.create,
            file=("document.docx", io.BytesIO(file_bytes),
                  "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            purpose="user_data",  # "user_data" for Responses API, not "assistants"
        )
        index_future = executor.submit(_build_index_map, unpacked_dir)

        uploaded_file = upload_future.result()
        paragraphs, index_map = index_future.result()

    file_id = uploaded_file.id

    try:
        user_message = (
            "להלן טבלת אינדקס הפסקאות של המסמך — השתמש במספרים אלו בדיוק עבור paragraph_index:\n\n"
            f"{index_map}\n\n"
            "בדוק את המסמך המצורף ודווח על ממצאים."
        )

        response = client.responses.create(
            model=OPENAI_DOCX_REVIEW_MODEL,
            input=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_message},
                        {"type": "input_file", "file_id": file_id},
                    ],
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "review_findings",
                    "strict": True,
                    "schema": _OPENAI_STRICT_SCHEMA,
                }
            },
        )

        raw = response.output_text

        try:
            validated = ReviewResponse.model_validate_json(raw)
        except Exception as e:
            raise ValueError(
                f"OpenAI docx JSON schema mismatch.\nPydantic error: {e}\nRaw: {raw[:500]}"
            )

        return [f.model_dump() for f in validated.findings]

    finally:
        try:
            client.files.delete(file_id)
        except Exception:
            pass


def _call_claude_api(paragraph_text: str) -> list[dict]:
    """
    Make a single Claude API call and return list of finding dicts.
    Validates response against the Pydantic schema.
    Uses streaming to reduce perceived wait time.
    """
    api_key = get_api_key("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set.")
    client = anthropic.Anthropic(api_key=api_key)

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
    api_key = get_api_key("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set.")

    client = _openai_module.OpenAI(api_key=api_key)

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
    api_key = get_api_key("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")

    client = _gemini_module.Client(api_key=api_key)

    response_stream = client.models.generate_content_stream(
        model=GEMINI_REVIEW_MODEL,
        contents=paragraph_text,
        config=_gemini_types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=_REVIEW_RESPONSE_SCHEMA,
            temperature=0.2,
        ),
    )

    raw_text = ""
    for chunk in response_stream:
        if chunk.text:
            raw_text += chunk.text

    raw_text = raw_text.strip()

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


def _strip_markdown_wrappers(text: str) -> str:
    """Strip ```json ... ``` wrappers that Gemini sometimes adds around JSON."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _salvage_gemini_json_list(raw_text: str) -> list[dict]:
    """Attempts to salvage findings from a truncated Gemini JSON response.
    
    Handles the common case where Gemini cuts off mid-string, producing
    invalid JSON like: {"comment": "some text that keeps go...
    Strategy: find every COMPLETE finding object via regex, ignore the rest.
    """
    import json
    import re

    raw_text = raw_text.strip()
    if not raw_text:
        return []

    # ── Strategy 1: Extract all complete finding objects via regex ─────────
    # Each finding is a JSON object containing "paragraph_index".
    # We find them by matching balanced braces around that key.
    findings = []
    # This pattern matches a { ... } block that contains "paragraph_index"
    # It handles nested quotes and escaped characters.
    brace_depth = 0
    obj_start = -1
    i = 0
    while i < len(raw_text):
        ch = raw_text[i]
        if ch == '"':  # skip over string contents
            i += 1
            while i < len(raw_text):
                if raw_text[i] == '\\':
                    i += 2  # skip escaped char
                    continue
                if raw_text[i] == '"':
                    break
                i += 1
        elif ch == '{':
            if brace_depth == 0:
                obj_start = i
            brace_depth += 1
        elif ch == '}':
            brace_depth -= 1
            if brace_depth == 0 and obj_start >= 0:
                candidate = raw_text[obj_start:i+1]
                if '"paragraph_index"' in candidate:
                    try:
                        obj = json.loads(candidate)
                        if isinstance(obj, dict) and "paragraph_index" in obj:
                            findings.append(obj)
                    except Exception:
                        pass
                obj_start = -1
        i += 1

    if findings:
        return findings

    # ── Strategy 2: Cut at last complete `}`, close brackets ──────────────
    last_brace = raw_text.rfind('}')
    if last_brace != -1:
        truncated = raw_text[:last_brace+1]
        open_brackets = truncated.count('[')
        close_brackets = truncated.count(']')
        if open_brackets > close_brackets:
            truncated += ']' * (open_brackets - close_brackets)
        open_braces = truncated.count('{')
        close_braces = truncated.count('}')
        if open_braces > close_braces:
            truncated += '}' * (open_braces - close_braces)
        try:
            data = json.loads(truncated)
            if isinstance(data, dict) and "findings" in data:
                return data["findings"]
            elif isinstance(data, list):
                return data
        except Exception:
            pass

    return findings


def _filter_empty_paragraphs(rich_markdown: str) -> str:
    """Remove [N] (ריק) lines from rich markdown to save input tokens."""
    return "\n".join(
        line for line in rich_markdown.split("\n")
        if not line.strip().endswith("(ריק)")
    )


def _call_gemini_full_api(rich_markdown: str) -> list[dict]:
    """
    Dual-agent Gemini call: runs LOGIC_PROMPT and LANGUAGE_PROMPT in parallel,
    then merges and deduplicates findings.
    """
    import concurrent.futures

    rich_markdown = _filter_empty_paragraphs(rich_markdown)

    if not _GEMINI_AVAILABLE:
        raise ImportError(
            "google-genai package is not installed. Run: pip install -U google-genai"
        )
    api_key = get_api_key("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")

    def _gemini_call(system_prompt: str, agent_label: str, content: str, max_tokens: int = 16384) -> list[dict]:
        """Single Gemini API call with retries. Raises on total failure."""
        import time
        client = _gemini_module.Client(api_key=api_key)

        last_exception = None
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=GEMINI_FULL_REVIEW_MODEL,
                    contents=content,
                    config=_gemini_types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json",
                        response_schema=_REVIEW_RESPONSE_SCHEMA,
                        temperature=0.2,
                        max_output_tokens=max_tokens,
                    ),
                )

                raw = _strip_markdown_wrappers(response.text or "")
                data = json.loads(raw)
                validated = ReviewResponse(**data)
                logger.info(f"[{agent_label}] returned {len(validated.findings)} findings")
                return [f.model_dump() for f in validated.findings]

            except Exception as e:
                last_exception = e
                logger.warning(f"[{agent_label}] attempt {attempt+1}/3 failed: {e}")
                if attempt < 2:
                    time.sleep(1)
                    continue

        raise RuntimeError(
            f"Gemini {agent_label} failed after 3 attempts: {last_exception}"
        )

    # ── LOGIC: send full document (needs global context) ──────────────────
    def _logic_call() -> list[dict]:
        return _gemini_call(LOGIC_PROMPT, "LOGIC", rich_markdown, max_tokens=16384)

    # ── LANGUAGE: chunk and process in parallel (local errors) ─────────────
    def _language_call() -> list[dict]:
        lines = rich_markdown.split('\n')
        chunks = []
        current_chunk = []
        current_len = 0

        for line in lines:
            current_chunk.append(line)
            current_len += len(line) + 1
            if current_len > 8000:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_len = 0

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        logger.info(f"Language pipeline: {len(chunks)} chunks")
        all_findings = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(_gemini_call, LANGUAGE_PROMPT, f"LANGUAGE_CHUNK_{i}", c) for i, c in enumerate(chunks)]
            for future in concurrent.futures.as_completed(futures):
                all_findings.extend(future.result())

        return all_findings

    # ── Run both agents in parallel ────────────────────────────────────────────
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        logic_future    = executor.submit(_logic_call)
        language_future = executor.submit(_language_call)
        logic_findings    = logic_future.result()
        language_findings = language_future.result()

    # ── Merge + deduplicate ────────────────────────────────────────────────────
    # Keep all findings; if same (paragraph_index, category) appears in both,
    # prefer the one with higher severity.
    _sev_rank = {"high": 3, "medium": 2, "low": 1}
    merged: dict[tuple, dict] = {}
    for finding in logic_findings + language_findings:
        key = (finding.get("paragraph_index"), finding.get("category"))
        existing = merged.get(key)
        if existing is None:
            merged[key] = finding
        else:
            # Keep higher-severity entry
            if _sev_rank.get(finding.get("severity", "low"), 0) > _sev_rank.get(existing.get("severity", "low"), 0):
                merged[key] = finding

    return list(merged.values())


def _call_spelling_only_single_chunk(chunk_markdown: str) -> list[dict]:
    """
    Single Gemini call focused exclusively on spelling, grammar, and punctuation for a chunk.
    Uses SPELLING_ONLY_PROMPT — no logic, phrasing, or structural checks.
    Returns a validated list of finding dicts (categories: spelling, punctuation only).
    Raises on failure so errors are visible to the user.
    """
    import time
    if not _GEMINI_AVAILABLE:
        raise ImportError("google-genai package is not installed. Run: pip install -U google-genai")
    api_key = get_api_key("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")

    client = _gemini_module.Client(api_key=api_key)

    last_exception = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=SPELLING_ONLY_MODEL,
                contents=chunk_markdown,
                config=_gemini_types.GenerateContentConfig(
                    system_instruction=SPELLING_ONLY_PROMPT,
                    response_mime_type="application/json",
                    response_schema=_REVIEW_RESPONSE_SCHEMA,
                    temperature=0.1,
                    max_output_tokens=16384,
                ),
            )

            raw = _strip_markdown_wrappers(response.text or "")
            data = json.loads(raw)
            validated = ReviewResponse(**data)
            logger.info(f"[SPELLING_ONLY] chunk returned {len(validated.findings)} findings")
            return [f.model_dump() for f in validated.findings]

        except Exception as e:
            last_exception = e
            logger.warning(f"[SPELLING_ONLY] attempt {attempt+1}/3 failed: {e}")
            if attempt < 2:
                time.sleep(1)
                continue

    raise RuntimeError(f"Gemini spelling-only failed after 3 attempts: {last_exception}")


def _call_spelling_only_api(rich_markdown: str) -> list[dict]:
    import concurrent.futures

    rich_markdown = _filter_empty_paragraphs(rich_markdown)
    lines = rich_markdown.split('\n')
    chunks = []
    current_chunk = []
    current_len = 0
    
    for line in lines:
        current_chunk.append(line)
        current_len += len(line) + 1
        if current_len > 8000:
            chunks.append("\n".join(current_chunk))
            current_chunk = []
            current_len = 0

    if current_chunk:
        chunks.append("\n".join(current_chunk))
        
    all_findings = []
    # Use max_workers=4 to process the chunks in parallel and keep it very fast
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(_call_spelling_only_single_chunk, chunks))
        for r in results:
            all_findings.extend(r)
            
    return all_findings


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
    if api_provider in ("openai", "openai_docx"):
        if not get_api_key("OPENAI_API_KEY"): raise ValueError("OPENAI_API_KEY is not set.")
    elif api_provider in ("gemini", "gemini_full", "spelling_only"):
        if not get_api_key("GEMINI_API_KEY"): raise ValueError("GEMINI_API_KEY is not set.")
    elif api_provider == "multi":
        if not get_api_key("OPENAI_API_KEY") or not get_api_key("GEMINI_API_KEY"):
            raise ValueError("Multi-agent review requires both OPENAI_API_KEY and GEMINI_API_KEY.")
    else:
        if not get_api_key("ANTHROPIC_API_KEY"): raise ValueError("ANTHROPIC_API_KEY is not set.")

    # ── Step 1: Extract text & Map Sections ──────────────────────────────────
    yield "📄 מנתח מבנה מסמך וממפה סעיפים..."

    original_name = _get_original_name(file_obj)
    file_bytes = _read_bytes(file_obj)
    with tempfile.NamedTemporaryFile(dir=TEMP_DIR, suffix=".docx", delete=False) as tmp:
        tmp.write(file_bytes)
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
    if api_provider == "openai_docx":
        yield "🤖 מעלה מסמך ל-GPT-4o ומריץ ביקורת מלאה..."
        try:
            findings = _call_openai_docx_api(file_bytes, unpack_dir)
        except Exception as e:
            yield f"❌ שגיאה בהעלאת המסמך ל-OpenAI: {e}"
            raise
    elif api_provider == "multi":
        yield "🤖 מריץ ביקורת רב-סוכנית (ניסוח, כתיב ועקביות)..."
        reviewer = MultiAgentReviewer()
        findings = reviewer.run_review(prompt_text)
        debug_info = reviewer.get_debug_summary()
    elif api_provider == "openai":
        yield "🤖 שולח לביקורת GPT-4o..."
        findings = _call_openai_api(prompt_text)
    elif api_provider == "gemini_full":
        yield "🤖 סורק מסמך מלא עם Gemini 3 Flash (טקסט עשיר)..."
        rich_md = get_rich_markdown(unpack_dir)
        findings = _call_gemini_full_api(rich_md)
    elif api_provider == "spelling_only":
        yield "🔤 בודק כתיב ודקדוק עם Gemini 3 Flash..."
        rich_md = get_rich_markdown(unpack_dir)
        findings = _call_spelling_only_api(rich_md)
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
