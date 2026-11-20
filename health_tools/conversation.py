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


ABOUT_ME = (
    "I'm a women's health education assistant. I can explain conditions like PCOS, endometriosis, "
    "period problems, PMS and menopause using reviewed sources, and help you make sense of symptoms by asking "
    "a few questions. I'm not a doctor and can't diagnose you or prescribe anything, but I can help you "
    "understand what might be going on and when to get care."
)
CAPABILITIES = (
    "Here's what I can help with:\n\n"
    "- Talk through what you're feeling: tell me your symptoms and I'll ask a few questions, then explain "
    "what a doctor may consider and when to get help\n"
    "- Explain conditions: PCOS, endometriosis, period pain, heavy bleeding, PMS/PMDD, fibroids, menopause\n"
    "- Cycle calculations: work out your cycle lengths from your period start dates\n"
    "- Deep research: search medical literature and guidelines for a cited answer\n\n"
    "What would you like to start with?"
)
_IDENTITY = re.compile(r"^\s*(?:hi|hello|hey)?[\s,!]*(?:who|what) (?:are|r) (?:you|u)\b|^\s*are you (?:a |an )?(?:doctor|human|real|bot|robot|ai|person|nurse)\b|"
                       r"^\s*(?:what'?s|what is) your name\b|^\s*introduce yourself\b", re.I)
_ABILITIES = re.compile(r"^\s*(?:hi|hello|hey)?[\s,!]*(?:what (?:can|do) (?:you|u) do|how (?:can|do) (?:you|u) help|what (?:can|could) (?:you|u) help (?:me )?with|"
                        r"what are you (?:for|able to do)|what do you (?:know|cover)|help|menu|options)\b[\s?!.]*$", re.I)
_FEELINGS = re.compile(r"^\s*(?:i'?m|i am|feeling) (?:worried|scared|anxious|confused|stressed|nervous)\b[\s.!]*$", re.I)


def conversational_reply(query: str) -> str | None:
    """Return an acknowledgement only when every clause is social/context-only."""
    if not isinstance(query, str):
        return None
    text = " ".join(query.strip().split())
    if _IDENTITY.search(text):
        return ABOUT_ME + " What would you like help with?"
    if _ABILITIES.search(text):
        return CAPABILITIES
    if _FEELINGS.search(text):
        return ("That's completely understandable — health worries can be stressful. I'm here to help. "
                "Can you tell me what's going on, or what you're feeling in your body?")
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
        return ("Thanks for introducing yourself. How can I help today? You can tell me what you're feeling, "
                "or ask about PCOS, periods, or a cycle calculation.")
    if greeted:
        return ("Hello. I'm here to help with women's health questions. You can tell me what you're feeling, "
                "or ask about PCOS, periods, or a cycle calculation. What's on your mind?")
    return None
