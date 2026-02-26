"""
agents/aggregator.py
Merges findings from multiple agents into a final set of Word comments.
"""
from typing import TypedDict, Optional, Literal

class Finding(TypedDict):
    paragraph_index: int
    category: str
    severity: str
    comment: str
    suggestion: Optional[str]

def aggregate_findings(
    phrasing_findings: list[Finding],
    spelling_findings: list[Finding],
    consistency_findings: list[Finding]
) -> list[Finding]:
    """
    Merges findings from the 3 agents into a final list.
    Rules:
    1. Phrasing findings get their own comment (max 1 per paragraph).
    2. Spelling, Punctuation, and Consistency findings are merged into a single bulleted comment.
    3. Final result: Max 2 comments per paragraph.
    """
    by_paragraph = {} # {idx: {"phrasing": [], "others": []}}

    # Sort all findings into buckets
    def add_to_bucket(findings, bucket_key):
        for f in findings:
            idx = f["paragraph_index"]
            if idx not in by_paragraph:
                by_paragraph[idx] = {"phrasing": [], "others": []}
            by_paragraph[idx][bucket_key].append(f)

    add_to_bucket(phrasing_findings, "phrasing")
    add_to_bucket(spelling_findings, "others")
    add_to_bucket(consistency_findings, "others")

    final_findings = []

    for idx in sorted(by_paragraph.keys()):
        buckets = by_paragraph[idx]
        
        # 1. Handle Phrasing (take highest severity if multiple, though prompt says 1)
        if buckets["phrasing"]:
            # Sort by severity high > medium > low
            severity_map = {"high": 3, "medium": 2, "low": 1}
            sorted_phrasing = sorted(buckets["phrasing"], key=lambda x: severity_map.get(x["severity"], 0), reverse=True)
            # Take only the first one as per Amit's 2-comment rule
            final_findings.append(sorted_phrasing[0])

        # 2. Merge Others
        if buckets["others"]:
            # Combine all comments into a bulleted list
            merged_comments = []
            highest_severity = "low"
            severity_map = {"high": 3, "medium": 2, "low": 1}
            
            for f in buckets["others"]:
                # Upgrade severity if needed
                if severity_map.get(f["severity"], 0) > severity_map.get(highest_severity, 0):
                    highest_severity = f["severity"]
                
                # Add bullet point
                merged_comments.append(f"• {f['comment']}")
            
            # Create a single merged finding
            final_findings.append({
                "paragraph_index": idx,
                "category": "merged_review",
                "severity": highest_severity,
                "comment": "\n".join(merged_comments),
                "suggestion": None # Suggestions are usually phrasing-specific
            })

    return final_findings
