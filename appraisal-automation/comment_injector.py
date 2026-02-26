"""
comment_injector.py
High-level comment injection orchestrator for Stage 2.

Collects Claude's findings, deduplicates, and injects them as Word comments
using the batch API in scripts/office/comment.py (single parse/write cycle).
"""
import os
import sys

_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "scripts", "office")
sys.path.insert(0, _SCRIPTS_DIR)

from comment import inject_comments_batch
from config import COMMENT_AUTHOR


# ── Category to emoji prefix mapping (Hebrew labels) ─────────────────────────
EMOJI_MAP: dict[str, str] = {
    "logic":       "🔍 עקביות",
    "missing":     "📋 חסר",
    "spelling":    "✍️ כתיב",
    "phrasing":    "🗣️ ניסוח",
    "punctuation": "✏️ פיסוק",
    "merged_review": "🧱 סקירה משולבת",
}


def format_comment_text(finding: dict) -> str:
    """
    Build comment text from a finding dict.
    finding keys: paragraph_index, category, severity, comment, suggestion (or None), section_label (opt)
    """
    category = finding.get("category", "logic")
    prefix   = EMOJI_MAP.get(category, "📌")
    comment_body = finding.get("comment", "")
    section = finding.get("section_label")

    text = f"{prefix}: {comment_body}"
    if section:
        text = f"📍 {section}\n" + text

    suggestion = finding.get("suggestion")
    if suggestion:
        text += f"\n\n💡 הצעה: {suggestion}"

    return text


def inject_all_comments(unpacked_dir: str, findings: list[dict]) -> int:
    """
    Inject all findings as Word comments into the unpacked DOCX.
    """
    # Sort by paragraph_index ascending so IDs are logical
    sorted_findings = sorted(findings, key=lambda f: f.get("paragraph_index", 0))

    # Build batch list
    batch: list[dict] = []
    for cid, finding in enumerate(sorted_findings):
        batch.append({
            "comment_id": cid,
            "para_index": finding.get("paragraph_index", 0),
            "text":       format_comment_text(finding),
        })

    if not batch:
        return 0

    # Single-pass injection
    inject_comments_batch(
        unpacked_dir=unpacked_dir,
        comments=batch,
        author=COMMENT_AUTHOR,
    )

    return len(batch)


def build_summary(findings: list[dict]) -> str:
    """Build the on-screen summary string for Stage 2 output."""
    from collections import Counter

    cat_counts = Counter(f.get("category", "?") for f in findings)
    sev_counts = Counter(f.get("severity", "?") for f in findings)

    total = len(findings)

    lines = [
        f"✅ הביקורת הושלמה.",
        f"",
        f"נמצאו {total} ממצאים:",
        f"🔍 עקביות לוגית: {cat_counts.get('logic', 0)}",
        f"📋 תוכן חסר: {cat_counts.get('missing', 0)}",
        f"✍️ שגיאות כתיב: {cat_counts.get('spelling', 0)}",
        f"🗣️ בעיות ניסוח: {cat_counts.get('phrasing', 0)}",
        f"✏️ פיסוק: {cat_counts.get('punctuation', 0)}",
        f"🧱 סקירה משולבת: {cat_counts.get('merged_review', 0)}",
        f"",
        f"לפי חומרה — חמור: {sev_counts.get('high', 0)} | בינוני: {sev_counts.get('medium', 0)} | נמוך: {sev_counts.get('low', 0)}",
        f"",
        f"הורד את הדוח הנסקר — ההערות כוללות הצעות לשכתוב ומיפוי סעיפים.",
    ]

    return "\n".join(lines)
