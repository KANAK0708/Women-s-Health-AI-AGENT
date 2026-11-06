"""Patient context extraction and clarification turn governance.

Implements Section 4 of the Implementation Plan:
- Recheck safety on every turn, including after a topic change.
- Distinguish 'not_provided' from 'no': unknown pregnancy status, unknown medication
  use, and missing age must never silently become negative findings.
- Enforce a maximum of 2 focused clarification turns.
"""

import re
from typing import Optional

from app.retrieval.exceptions import UrgentEscalationRequired
from app.retrieval.filters import check_urgent_hazards
from app.schemas.memory import MinimalPatientContext, SessionMemory, TriState

AGE_PATTERN = re.compile(
    r"\b(?:i\s+am|i'm|age\s+is|aged)\s+(\d{1,3})\s*(?:years?\s*old|yo|yrs?)?\b",
    re.IGNORECASE,
)
PREGNANT_NO_PATTERN = re.compile(
    r"\b(?:not\s+pregnant|definitely\s+not\s+pregnant|negative\s+pregnancy\s+test|no\s+chance\s+of\s+pregnancy)\b",
    re.IGNORECASE,
)
PREGNANT_YES_PATTERN = re.compile(
    r"\b(?:i\s+am\s+pregnant|i'm\s+pregnant|positive\s+pregnancy\s+test|currently\s+pregnant|might\s+be\s+pregnant|could\s+be\s+pregnant)\b",
    re.IGNORECASE,
)
MEDICATION_NO_PATTERN = re.compile(
    r"\b(?:not\s+taking\s+any\s+(?:medications?|meds|pills)|no\s+medications?)\b",
    re.IGNORECASE,
)
MEDICATION_YES_PATTERN = re.compile(
    r"\b(?:taking\s+metformin|prescribed\s+medicine|birth\s+control\s+pills?|on\s+medication)\b",
    re.IGNORECASE,
)
IRREGULAR_CYCLE_PATTERN = re.compile(
    r"\b(?:irregular\s+periods?|missed\s+periods?|late\s+periods?|absent\s+periods?|oligomenorrhea|amenorrhea)\b",
    re.IGNORECASE,
)


class ContextTracker:
    """Updates minimal session context safely without inferring negative findings from silence."""

    @staticmethod
    def update_from_user_turn(session: SessionMemory, user_input: str) -> SessionMemory:
        """Process a user turn, rechecking safety first and updating only explicitly stated context."""
        session.turn_count += 1
        ctx: MinimalPatientContext = session.context

        # 1. Always recheck urgent hazards on every turn, even after a topic change
        try:
            check_urgent_hazards(user_input)
        except UrgentEscalationRequired:
            ctx.severe_symptom_flag = TriState.YES
            session.audit_codes.append("URGENT_HAZARD_TRIGGERED")
            raise

        # 2. Age & adult eligibility extraction (only if explicitly stated)
        age_match = AGE_PATTERN.search(user_input)
        if age_match:
            parsed_age = int(age_match.group(1))
            if 1 <= parsed_age <= 120:
                ctx.age = parsed_age
                ctx.is_adult = TriState.YES if parsed_age >= 18 else TriState.NO
                session.audit_codes.append(
                    "AGE_ADULT_CONFIRMED" if parsed_age >= 18 else "AGE_MINOR_OUT_OF_SCOPE"
                )

        # 3. Pregnancy status (never assume NO if not mentioned)
        if PREGNANT_NO_PATTERN.search(user_input):
            ctx.pregnancy_status = TriState.NO
            session.audit_codes.append("PREGNANCY_STATUS_NO")
        elif PREGNANT_YES_PATTERN.search(user_input):
            ctx.pregnancy_status = TriState.YES
            session.audit_codes.append("PREGNANCY_STATUS_YES")

        # 4. Medication mentions (never assume NO if not mentioned)
        if MEDICATION_NO_PATTERN.search(user_input):
            ctx.current_medications_mentioned = TriState.NO
        elif MEDICATION_YES_PATTERN.search(user_input):
            ctx.current_medications_mentioned = TriState.YES

        # 5. Menstrual regularity mentions
        if IRREGULAR_CYCLE_PATTERN.search(user_input):
            ctx.irregular_cycles_mentioned = TriState.YES

        # 6. Topic tracking
        lowered = user_input.lower()
        if "pcos" in lowered or "pcod" in lowered or "polycystic" in lowered:
            ctx.active_topic = "PCOS (Polycystic Ovary Syndrome)"
        elif any(t in lowered for t in ("period", "menstrua", "cycle", "cramp", "dysmenorrhea")):
            ctx.active_topic = "Menstrual Health"

        if not session.allow_session_context:
            # Respect user opt-out of session context retention
            session.context = MinimalPatientContext(
                severe_symptom_flag=ctx.severe_symptom_flag,
                is_adult=ctx.is_adult,
            )

        return session

    @staticmethod
    def record_clarification_turn(
        session: SessionMemory,
        question: str,
    ) -> Optional[str]:
        """Increment clarification counter if under the 2-turn limit; return None if limit reached."""
        if not session.context.can_request_clarification():
            session.audit_codes.append("CLARIFICATION_LIMIT_REACHED_FALLBACK")
            return None

        session.context.clarification_turns_used += 1
        session.audit_codes.append(
            f"CLARIFICATION_TURN_{session.context.clarification_turns_used}"
        )
        return question
