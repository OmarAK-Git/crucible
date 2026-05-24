from backend.merge import apply_accepted_proposals

def test_apply_accepted_proposals():
    base_prompt = "Perform code optimization."
    
    # 1. Empty accepted proposals
    assert apply_accepted_proposals(base_prompt, []) == base_prompt
    
    # 2. Grouped proposals by severity
    proposals = [
        {"text": "Ensure rates are limited", "severity": "critical"},
        {"text": "Add logs", "severity": "minor"},
        {"text": "Validate paths", "severity": "critical"},
        {"text": "Use token auth", "severity": "important"}
    ]
    
    merged = apply_accepted_proposals(base_prompt, proposals)
    assert "### Refinements" in merged
    assert "#### Critical Severity:" in merged
    assert "- Ensure rates are limited" in merged
    assert "- Validate paths" in merged
    assert "#### Important Severity:" in merged
    assert "- Use token auth" in merged
    assert "#### Minor Severity:" in merged
    assert "- Add logs" in merged
    
    # 3. Strip existing refinements and merge updated list
    new_proposals = [
        {"text": "Ensure rates are limited", "severity": "critical"},
        {"text": "Validate paths", "severity": "critical"},
        {"text": "Use token auth (modified)", "severity": "important"}
    ]
    remerged = apply_accepted_proposals(merged, new_proposals)
    
    assert "- Add logs" not in remerged
    assert "Use token auth (modified)" in remerged
    assert remerged.count("### Refinements") == 1
