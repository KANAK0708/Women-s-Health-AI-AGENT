"""Software-use explanations, separate from requests to execute a tool."""

import re


CYCLE_HELP = (
    "How cycle calculation works\n"
    "The calculator counts elapsed days between consecutive period start dates. "
    "For example, 2026-08-01 to 2026-09-05 is 35 days. With more dates, it also reports the average interval and the difference between the longest and shortest intervals. "
    "The reference date is used separately for time since the last recorded start.\n"
    "To run it, say 'calculate cycle intervals'. Supply starts of separate periods, oldest first, as YYYY-MM-DD, then a local reference date and confirm the proposed inputs. "
    "It calculates recorded intervals; it does not diagnose PCOS or predict ovulation."
)


def _clauses(query: str):
    return re.split(r"\s+(?:and|also)\s+(?=(?:what|how|explain|describe|tell|calculate|compute)\b)", query, flags=re.I)


def _explains_clause(query: str) -> bool:
    lowered = query.casefold()
    tool = bool(re.search(r"\b(?:cycles?|periods?)\s+calculat\w*\b|\bcalculat\w*\b.*\b(?:cycles?|periods?)\b", lowered))
    explanation = bool(re.search(r"\b(?:how|explain|describe)\b|\bwhat\b.*\b(?:calculator|calculation)\b", lowered))
    return tool and explanation


def asks_how_calculator_works(query: str) -> bool:
    return any(_explains_clause(clause) for clause in _clauses(query))


def medical_part_of_calculator_question(query: str) -> str | None:
    clauses = _clauses(query)
    remaining = [clause for clause in clauses if not asks_how_calculator_works(clause)]
    if remaining:
        return " and ".join(remaining).strip()
    # Support 'explain PCOS and cycle calculations' without inventing a topic.
    match = re.search(r"\b(?:pcos|pcod|polycystic ovary syndrome)\b", query, re.I)
    if match:
        return "What is " + match.group(0) + "?"
    return None
