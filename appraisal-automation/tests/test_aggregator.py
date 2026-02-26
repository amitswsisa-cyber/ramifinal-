import pytest
from agents.aggregator import aggregate_findings

def test_aggregate_findings():
    phrasing = [
        {"paragraph_index": 10, "category": "phrasing", "severity": "medium", "comment": "סרבול", "suggestion": "X"}
    ]
    spelling = [
        {"paragraph_index": 10, "category": "spelling", "severity": "low", "comment": "טעות 1", "suggestion": None},
        {"paragraph_index": 12, "category": "spelling", "severity": "high", "comment": "טעות חמורה", "suggestion": None}
    ]
    consistency = [
        {"paragraph_index": 10, "category": "logic", "severity": "high", "comment": "סתירה בתאריכים", "suggestion": None}
    ]

    final = aggregate_findings(phrasing, spelling, consistency)

    # Paragraph 10 should have 2 comments: 1 Phrasing and 1 Merged (Spelling + Logic)
    p10_findings = [f for f in final if f["paragraph_index"] == 10]
    assert len(p10_findings) == 2
    
    phrasing_f = [f for f in p10_findings if f["category"] == "phrasing"][0]
    merged_f = [f for f in p10_findings if f["category"] == "merged_review"][0]
    
    assert phrasing_f["comment"] == "סרבול"
    assert "• טעות 1" in merged_f["comment"]
    assert "• סתירה בתאריכים" in merged_f["comment"]
    assert merged_f["severity"] == "high" # Logic was high

    # Paragraph 12 should have 1 comment (Spelling)
    p12_findings = [f for f in final if f["paragraph_index"] == 12]
    assert len(p12_findings) == 1
    assert p12_findings[0]["category"] == "merged_review"
    assert p12_findings[0]["severity"] == "high"

if __name__ == "__main__":
    pytest.main([__file__])
