from typing import List, Dict, Any

def apply_accepted_proposals(working_prompt: str, all_accepted_proposals: List[Dict[str, Any]]) -> str:
    """
    Takes the working prompt and the list of all accepted/modified proposals,
    and returns the next working prompt.
    Appends the proposals grouped by severity under a '### Refinements' block at the end.
    
    Each item in all_accepted_proposals should have:
    - 'text': the text to append (either original proposal text or modification text)
    - 'severity': 'critical' | 'important' | 'minor'
    """
    # Strip any existing refinements section
    base_prompt = working_prompt.split("\n\n### Refinements")[0].strip()
    
    if not all_accepted_proposals:
        return base_prompt
        
    # Group by severity
    grouped = {"critical": [], "important": [], "minor": []}
    for prop in all_accepted_proposals:
        severity = (prop.get("severity") or "minor").lower()
        if severity not in grouped:
            severity = "minor"
        
        text = prop.get("text", "").strip()
        if text:
            grouped[severity].append(text)
            
    refinement_lines = ["\n\n### Refinements"]
    for sev in ["critical", "important", "minor"]:
        items = grouped[sev]
        if items:
            refinement_lines.append(f"\n#### {sev.capitalize()} Severity:")
            for item in items:
                refinement_lines.append(f"- {item}")
                
    return base_prompt + "\n".join(refinement_lines)
