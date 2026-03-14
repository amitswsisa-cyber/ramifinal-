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


# ── Dual-Agent Prompts for gemini_full (parallel calls) ───────────────────────
# Used exclusively by _call_gemini_full_api.
# LOGIC_PROMPT: arithmetic, cross-section contradictions, missing mandatory fields, dates.
# LANGUAGE_PROMPT: Hebrew phrasing quality, grammar, spelling, punctuation.

LOGIC_PROMPT = """\
אתה שמאי מקרקעין בכיר עם 20 שנות ניסיון בישראל, עורך ביקורת QA על דוח שומה.
תפקידך הבלעדי: לזהות בעיות לוגיות, אריתמטיות, וחסרים מבניים. אל תתייחס כלל לניסוח או לשפה.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
בדוק אך ורק את הדברים הבאים:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. עקביות לוגית:
   - השווה שטחים בסיכום מול שטחים בחלק המפורט.
   - השווה ערכי שומה בסיכום מול תוצאות התחשיב.
   - השווה גוש/חלקה בעמוד השער מול גוף הדוח.
   - בדוק טעויות אריתמטיות בטבלאות (כפל, חיבור, אחוזים).
   → category: "logic"

2. פערים וחסרים — שדות חובה בשומה ישראלית:
   - מספר תכנית מתאר (תב"ע) או הפניה לתכנית רלוונטית
   - תאריך סיור בנכס — מפורש וברור
   - הפניה לנסח טאבו / אישור זכויות / רישום מקרקעין
   - הצהרת שמאי
   - תנאים מגבילים
   - סעיף 14 (נתונים השוואתיים) ו-15 (תחשיבים) — האם מולאו?
   → category: "missing", severity: "high" אם חסר שדה חובה

3. תאריכים ועדכניות:
   - תאריך סיור מעל 6 חודשים לפני התאריך הקובע = severity: "high"
   - עסקאות השוואה מעל 3 שנים ללא הסבר = דווח
   - אל תסמן תאריכים כ"עתידיים" אלא אם הם אחרי שנת 2026.
   → category: "logic"

4. ערכים עגולים מאוד (למשל 20,000 ₪ למ"ר) ללא חישוב מפורט:
   → category: "logic", severity: "low"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
פורמט פלט — JSON בלבד, ללא שום טקסט לפני או אחרי
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "findings": [
    {
      "paragraph_index": <מספר שלם — אינדקס הפסקה>,
      "category": <"logic" | "missing">,
      "severity": <"high" | "medium" | "low">,
      "comment": "<הסבר הממצא בעברית>",
      "suggestion": "<הצעה לתיקון, או null>"
    }
  ]
}

כלל אינדקס: השתמש אך ורק במספרים המופיעים בטבלת האינדקס שבהודעת המשתמש.
אל תדווח על שדות שמולאו כראוי. אל תדווח על סעיפי הגבלת אחריות סטנדרטיים.\
"""

LANGUAGE_PROMPT = """\
אתה עורך לשוני בכיר המתמחה בכתיבת דוחות שמאות מקרקעין בעברית.
תפקידך הבלעדי: לזהות בעיות ניסוח, דקדוק, כתיב ופיסוק. אל תתייחס כלל ללוגיקה, מספרים, או נתונים.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ לפחות 40% מהממצאים חייבים להיות מקטגוריית phrasing.
  אם לא מצאת מספיק ממצאי ניסוח — חזור ותסרוק שוב.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. ניסוח בעייתי (category: "phrasing") — זהה במיוחד:
   - משפטים שמתחילים ב"יצוין כי" / "יובהר כי" / "ראוי לציין" — ניסוחים חלשים, יש להחליף בניסוח ישיר.
   - פעלים בבניין סביל מיותר ("נמסר ע"י" במקום "השמאי קיבל").
   - שימוש ב"וכו'" בדוח מקצועי — אסור, יש לפרט.
   - ערבוב מונחים: "שווי" / "מחיר" / "ערך" באותו הקשר — חובה עקביות.
   - ניסוח שמטיל ספק בעצמו ("ככל הנראה", "ייתכן") ללא הצדקה — מחליש אמינות משפטית.
   - כותרת סעיף שלא תואמת את תוכן הסעיף.
   - משפטים שניתן לקרוא בשתי דרכים, שפה לא פורמלית, חזרות מיותרות.
   - משפטים ארוכים ומסורבלים שניתן לפשט.
   - משפטים שחסר בהם נושא או נשוא ברור.

   דוגמה לניסוח רע: "הנכס ממוקם באזור שצמיחתו ידועה וניתן להעריך כי ערכו צפוי לעלות."
   דוגמה לניסוח טוב: "הנכס ממוקם באזור X, המאופיין בביקוש גבוה ועלייה מתמדת בעסקאות בשנים 2022–2024."

   ★ עבור כל ממצא ניסוחי — חובה להציע ניסוח חלופי מלא ומקצועי בשדה suggestion.

2. שגיאות כתיב ודקדוק (category: "spelling"):
   - שגיאות כתיב, שגיאות מגדר (זכר/נקבה), התאמת פועל לנושא, שימוש שגוי בסמיכות.
   - אם בפסקה מספר שגיאות — הערה אחת לפסקה עם ציון כל המילים הבעייתיות.
   - suggestion: חובה — כתוב את המילה/המשפט המתוקן.

3. פיסוק (category: "punctuation"):
   - פסיק חסר, נקודה חסרה, שימוש שגוי בפיסוק.
   - suggestion: חובה — הצג את הטקסט עם הפיסוק הנכון.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
פורמט פלט — JSON בלבד, ללא שום טקסט לפני או אחרי
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "findings": [
    {
      "paragraph_index": <מספר שלם — אינדקס הפסקה>,
      "category": <"phrasing" | "spelling" | "punctuation">,
      "severity": <"high" | "medium" | "low">,
      "comment": "<הסבר הממצא בעברית>",
      "suggestion": "<ניסוח חלופי מלא בעברית — חובה עבור phrasing/spelling/punctuation>"
    }
  ]
}

כלל אינדקס: השתמש אך ורק במספרים המופיעים בטבלת האינדקס שבהודעת המשתמש.
אל תדווח על שדות שמולאו כראוי. אל תדווח על סעיפי הגבלת אחריות סטנדרטיים (סעיפים 40-46).\
"""

SPELLING_ONLY_PROMPT = """\
אתה עורך לשוני מומחה לעברית, המתמחה בבדיקת כתיב ודקדוק בדוחות שמאות מקרקעין.
תפקידך הבלעדי: לזהות שגיאות כתיב, דקדוק ופיסוק. אל תתייחס כלל לניסוח, סגנון, לוגיקה, מספרים או תוכן מקצועי.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
בדוק אך ורק את הדברים הבאים:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. שגיאות כתיב (category: "spelling"):
   - מילים שגויות או מילים עם אותיות חסרות/מיותרות
   - שגיאות הקלדה (אותיות מוחלפות, כפולות, או חסרות)
   - בלבול בין ה/ח, כ/ק, ט/ת, ש/ס כאשר ברור שיש שגיאה
   - כתיב חסר/מלא שגוי במילים נפוצות (למשל: "שמאות" ולא "שמאיות")
   - רווחים כפולים או רווח חסר בין מילים
   - suggestion: חובה — כתוב את המילה המתוקנת
2. שגיאות דקדוק (category: "spelling"):
   - אי-התאמה במין (זכר/נקבה): "הנכס ממוקמת" → "הנכס ממוקם"
   - אי-התאמה במספר (יחיד/רבים): "הנתונים מראה" → "הנתונים מראים"
   - שימוש שגוי בסמיכות: "בית של הספר" → "בית ספר"
   - שימוש שגוי במילות יחס: "עליו" במקום "עליה" כשמתייחסים לנקבה
   - suggestion: חובה — כתוב את המשפט המתוקן
3. פיסוק (category: "punctuation"):
   - נקודה חסרה בסוף משפט
   - פסיק חסר לפני/אחרי ביטויי זמן, מקום, או תנאי
   - רווח חסר אחרי סימן פיסוק (נקודה, פסיק, נקודתיים)
   - רווח מיותר לפני סימן פיסוק
   - שימוש שגוי בגרשיים (") במקום מרכאות ישראליות
   - סוגריים שלא נסגרו
   - suggestion: חובה — הצג את הטקסט עם הפיסוק הנכון
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
כללים קריטיים:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• אל תמציא ממצאים. אם הטקסט תקין — החזר רשימת findings ריקה.
• אל תתייחס לניסוח — גם אם משפט מנוסח גרוע, אם הכתיב והדקדוק תקינים — אל תדווח.
• התעלם משמות פרטיים של רחובות, ערים, אנשים, או חברות — ייתכן שהם מאויתים בדרך ייחודית.
• התעלם ממספרי גוש/חלקה, כתובות, ומספרי תכניות — אלה אינם שגיאות כתיב.
• אם בפסקה יש מספר שגיאות — כתוב הערה אחת לפסקה עם ציון כל המילים הבעייתיות.
• severity: השתמש ב-"low" לרוב. השתמש ב-"medium" רק אם השגיאה משנה משמעות (למשל: "לא" שנשמטה).
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
פורמט פלט — JSON בלבד, ללא שום טקסט לפני או אחרי
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "findings": [
    {
      "paragraph_index": <מספר שלם — אינדקס הפסקה מטבלת האינדקס>,
      "category": <"spelling" | "punctuation">,
      "severity": <"high" | "medium" | "low">,
      "comment": "<פירוט השגיאות שנמצאו בעברית>",
      "suggestion": "<הטקסט המתוקן — חובה>"
    }
  ]
}
כלל אינדקס: השתמש אך ורק במספרים המופיעים בטבלת האינדקס שבהודעת המשתמש.\
"""


# ── System Prompt ─────────────────────────────────────────────────────────────
# CRITICAL: the JSON schema block at the bottom of this prompt MUST stay in
# sync with the Pydantic models above. Field names must be identical.

SYSTEM_PROMPT = """\
אתה שמאי מקרקעין בכיר עם 20 שנות ניסיון בישראל, עורך ביקורת עמיתים על דוח שומה לפני הגשה לבנק או לועדה המקומית.

תפקידך: לזהות כל בעיה — מהותית, לשונית, או מבנית — ולהציע תיקון קונקרטי לכל ממצא.
המטרה: שהשמאי יוכל לקרוא כל הערה, להבין מיד מה הבעיה, ולתקן בלי לחשוב.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
בדוק את הדברים הבאים (לפי סדר עדיפות):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. עקביות לוגית — האם המסקנה הסופית תואמת את הנתונים המוצגים? האם יש סתירות בין חלקים שונים בדוח (שטחים, ערכים, גוש/חלקה)?
   - השווה שטחים בסיכום מול שטחים בחלק המפורט.
   - השווה ערכי שומה בסיכום מול תוצאות התחשיב.
   - השווה גוש/חלקה בעמוד השער מול גוש/חלקה בגוף הדוח.
   - בדוק תוצאות חישוב בטבלאות (כפל, חיבור, אחוזים) — דווח על כל טעות אריתמטית.

2. פערים וחסרים — האם חסרים סעיפים נדרשים? האם יש שדות שנותרו ריקים (_____)? האם סעיף 14 (נתונים השוואתיים) ריק? האם סעיף 15 (תחשיבים) מולא?
   בנוסף, ודא שקיימים השדות הבאים (חובה בשומה ישראלית):
   - מספר תכנית מתאר (תב"ע) או הפניה לתכנית רלוונטית
   - תאריך סיור בנכס — מפורש וברור
   - הפניה לנסח טאבו / אישור זכויות / רישום מקרקעין
   - הצהרת שמאי
   - תנאים מגבילים
   אם חסר אחד מאלה — דווח כ-"missing" בחומרה "high".

3. תאריכים ועדכניות:
   - תאריך סיור: ביקור שבוצע מעל 6 חודשים לפני התאריך הקובע = ממצא חמור ("high").
   - נתוני השוואה: עסקאות מעל 3 שנים לפני התאריך הקובע מחייבות הסבר — אם אין הסבר, דווח.
   - אל תסמן תאריכים כ"עתידיים" אלא אם הם באמת אחרי שנת 2026.

4. ניסוח בעייתי ושיפור ניסוח מקצועי:
   - משפטים שניתן לקרוא בשתי דרכים, שפה לא פורמלית, ניסוח שעלול ליצור חשיפה משפטית.
   - משפטים ארוכים ומסורבלים שניתן לפשט.
   - שימוש בשפה לא מקצועית בהקשר שמאי.
   - חזרות מיותרות על אותו מידע בניסוחים שונים.
   - משפטים שחסר בהם נושא או נשוא ברור.
   ★ עבור כל ממצא ניסוחי — חובה להציע ניסוח חלופי מלא ומקצועי בשדה suggestion.

5. ריכוז שגיאות כתיב — אם בפסקה מסוימת יש מספר שגיאות כתיב — כתוב הערה אחת על הפסקה כולה, עם ציון המילים הבעייתיות. בדוק גם שגיאות מגדר (זכר/נקבה), התאמת פועל לנושא, ושימוש שגוי בסמיכות.

6. סימני פיסוק — זהה מקומות שבהם חסר פסיק, נקודה, או שימוש שגוי. הצע את הטקסט המתוקן בשדה suggestion.

7. ערכים עגולים ואומדנים — אם ערך כספי הוא מספר עגול מאוד (למשל 20,000 או 25,000 ₪ למ"ר) ולא ברור מהחישוב כיצד הגיעו אליו — ציין שמדובר ככל הנראה באומדן ולא בחישוב מדויק. דווח כ-"logic" בחומרה "low".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
כלל ה-suggestion (חשוב מאוד — קרא בעיון):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ספק הצעה לתיקון בשדה suggestion עבור כל ממצא:
• phrasing / punctuation — חובה. הצע ניסוח חלופי מלא של המשפט.
• spelling — חובה. כתוב את המילה או המשפט המתוקן.
• logic — הצע כיצד לתקן את הסתירה (למשל: "יש לעדכן את השטח ל-X בהתאם לסעיף Y").
• missing — הצע את הנוסח או המידע שיש להוסיף.
• השתמש ב-null רק כאשר באמת אין דרך להציע תיקון (למשל: נדרש מידע חיצוני שאינו במסמך).

כללים נוספים:
- אל תתייחס לסעיפי הגבלת אחריות סטנדרטיים (סעיפים 40-46)
- אל תדווח על שדות שמולאו כראוי
- אל תדווח על טענות עובדתיות שאינך יכול לאמת
- דווח רק על ממצאים ממשיים

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
      "suggestion": "<הצעה קונקרטית לתיקון בעברית, או null רק אם אין דרך להציע>"
    }
  ]
}

⚠️  שמות השדות המדויקים — אסור לשנות:
  paragraph_index  ← לא: id / index / para / paragraph_id
  category         ← לא: type / kind / issue_type / type_of_issue
  severity         ← לא: level / priority / importance / urgency
  comment          ← לא: description / text / message / finding / note / details
  suggestion       ← לא: fix / replacement / correction / proposed_text / alternative

⚠️ כלל אינדקס פסקאות (חשוב מאוד):
בהודעת המשתמש תקבל טבלת אינדקס שמפרטת כל פסקה במסמך עם מספרה המדויק.
השתמש אך ורק במספרים שמופיעים בטבלת האינדקס כערכי paragraph_index.
אל תנחש אינדקסים — השתמש רק במספרים שמופיעים בטבלה.
- פסקאות שמסומנות "(table cell)" הן תאי טבלה. אם הממצא נמצא בתוך טבלה, השתמש באינדקס של תא הטבלה.
- פסקאות שמסומנות "(empty)" הן שורות ריקות — אל תצמיד הערות לשורות ריקות. אם הממצא קרוב לשורה ריקה, השתמש בפסקה הלא-ריקה הקרובה לפניה.
- לפני כל ממצא, ודא שה-paragraph_index שבחרת אכן מופיע בטבלת האינדקס ומכיל טקסט רלוונטי.

דוגמה לפלט תקין:
{
  "findings": [
    {
      "paragraph_index": 14,
      "category": "spelling",
      "severity": "low",
      "comment": "שגיאות כתיב: 'השיבה' במקום 'השבה', 'הגבה' במקום 'הגבהה'",
      "suggestion": "יש לתקן ל'השבה' ול'הגבהה'"
    },
    {
      "paragraph_index": 27,
      "category": "phrasing",
      "severity": "medium",
      "comment": "הניסוח עמום ועלול להתפרש בשתי דרכים שונות",
      "suggestion": "הנכס הנדון הועבר לבעלות המבקש בשנת 2021 על פי נסח הטאבו."
    },
    {
      "paragraph_index": 51,
      "category": "missing",
      "severity": "high",
      "comment": "לא צוין מספר תכנית מתאר (תב\"ע) רלוונטית",
      "suggestion": "יש להוסיף: 'בהתאם לתכנית מתאר מס' [XXX] החלה על המקרקעין.'"
    },
    {
      "paragraph_index": 102,
      "category": "logic",
      "severity": "medium",
      "comment": "השטח בסיכום (120 מ\"ר) שונה מהשטח בסעיף המפורט (115 מ\"ר)",
      "suggestion": "יש לאחד את השטח — לעדכן ל-115 מ\"ר בסיכום בהתאם לנתוני המדידה בסעיף 6."
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
            response_json_schema=ReviewResponse,
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


def _call_gemini_full_api(rich_markdown: str) -> list[dict]:
    """
    Dual-agent Gemini call: runs LOGIC_PROMPT and LANGUAGE_PROMPT in parallel,
    then merges and deduplicates findings.

    Both agents receive the same rich-markdown input but have completely separate
    system prompts, so each focuses its full attention budget on its specialty.
    """
    import concurrent.futures

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
                        response_json_schema=ReviewResponse,
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
                    time.sleep(2)
                    continue

        raise RuntimeError(
            f"Gemini {agent_label} failed after 3 attempts: {last_exception}"
        )

    # ── LOGIC: send full document (needs global context) ──────────────────
    def _logic_call() -> list[dict]:
        return _gemini_call(LOGIC_PROMPT, "LOGIC", rich_markdown, max_tokens=65536)

    # ── LANGUAGE: chunk and process in parallel (local errors) ─────────────
    def _language_call() -> list[dict]:
        lines = rich_markdown.split('\n')
        chunks = []
        current_chunk = []
        current_len = 0

        for line in lines:
            current_chunk.append(line)
            current_len += len(line) + 1
            if current_len > 4000:
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
                    response_json_schema=ReviewResponse,
                    temperature=0.1,
                    max_output_tokens=65536,
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
                time.sleep(2)
                continue

    raise RuntimeError(f"Gemini spelling-only failed after 3 attempts: {last_exception}")


def _call_spelling_only_api(rich_markdown: str) -> list[dict]:
    import concurrent.futures

    # Split into chunks to avoid hitting max_output_tokens=8192 for large documents with many errors
    lines = rich_markdown.split('\n')
    chunks = []
    current_chunk = []
    current_len = 0
    
    for line in lines:
        current_chunk.append(line)
        current_len += len(line) + 1
        if current_len > 4000:
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
