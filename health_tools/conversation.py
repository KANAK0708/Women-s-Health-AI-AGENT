"""Recognize complete social/context-only turns before evidence retrieval.

Only whole clauses are accepted. A greeting or name prefix never hides a health
question or symptoms that follow it. Names are not extracted into stored memory.
"""

import re


GREETING = re.compile(r"(?:hi|hello|hey|good morning|good afternoon|good evening)\b[\s,!]*", re.I)
NAME = re.compile(r"(?:my name is|call me)\s+[a-z][a-z'’-]*(?:\s+[a-z][a-z'’-]*){0,2}", re.I)
AGE = re.compile(r"(?:i am|i'm|age is|aged)\s+[0-9]{1,3}\s*(?:years? old|years?|yrs?|yo)?", re.I)
HEALTH_OR_REQUEST = re.compile(
    r"\b(?:pcos|pcod|periods?|menstr\w*|pregnan\w*|symptoms?|pain|bleeding|faint\w*|"
    r"medicat\w*|doctor|help|what|how|why|when|calculate|research|diagnos\w*)\b", re.I)


def conversational_reply(query: str) -> str | None:
    """Return an acknowledgement only when every clause is social/context-only."""
    if not isinstance(query, str):
        return None
    text = " ".join(query.strip().split())
    if HEALTH_OR_REQUEST.search(text):
        return None
    if text.casefold().rstrip(".! ") in {"thanks", "thank you", "thank you very much"}:
        return "You're welcome. What would you like help with next?"
    intro = False
    greeted = False
    clauses = re.split(r"\s+and\s+|[,;.!?]+", text, flags=re.I)
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        greeting = GREETING.match(clause)
        if greeting:
            greeted = True
            clause = clause[greeting.end():].strip()
        if not clause:
            continue
        if NAME.fullmatch(clause) or AGE.fullmatch(clause):
            intro = True
            continue
        return None
    if intro:
        return "Thanks for introducing yourself. What would you like help with—PCOS, periods, or a cycle calculation?"
    if greeted:
        return "Hello. What would you like help with—PCOS, periods, or a cycle calculation?"
    return None
