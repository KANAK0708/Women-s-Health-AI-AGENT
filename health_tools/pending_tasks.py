"""Pure cycle-input conversation logic. No storage, model calls, or calculations."""

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Protocol


MAX_TASK_TURNS = 6
ISO = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
REFERENCE = re.compile(rf"\b(?:as of|reference(?: date)?|today is)\s*(?:is|to|:|=)?\s*({ISO})", re.I)
YES = {"yes", "confirm", "confirmed", "yes confirm", "yes confirmed"}
NO = {"no", "incorrect", "not correct"}
CANCEL = {"cancel", "cancel calculation", "cancel cycle calculation", "/cancel", "never mind", "nevermind", "don't calculate", "do not calculate", "stop calculation"}


@dataclass(frozen=True)
class PendingCycleTask:
    session_id: str
    expires_at: datetime
    period_start_dates: tuple[str, ...] = ()
    as_of: str | None = None
    awaiting_confirmation: bool = False
    turns_used: int = 0
    schema_version: str = "1.0"


class PendingTaskStore(Protocol):
    """Memory owner may implement this interface in Redis; keys must be isolated."""

    def get(self, session_id: str, *, now: datetime) -> PendingCycleTask | None: ...
    def save(self, task: PendingCycleTask, *, now: datetime) -> None: ...
    def delete(self, session_id: str) -> None: ...
    def purge_expired(self, *, now: datetime) -> None: ...


@dataclass(frozen=True)
class TaskTransition:
    action: str  # ask | execute | cancel | topic_change
    task: PendingCycleTask | None = None
    message: str = ""
    event: str = ""


def normalized_reply(message: str) -> str:
    return " ".join(message.strip().casefold().rstrip(".!?").split())


def is_task_reply(message: str) -> bool:
    """Recognize replies that must not execute a tool without an active task."""
    reply = normalized_reply(message)
    remainder = REFERENCE.sub(" ", message)
    remainder = re.sub(ISO, " ", remainder)
    remainder = re.sub(r"\b(?:starts?|dates?|and)\s*:?", " ", remainder, flags=re.I)
    return reply in YES | NO | CANCEL or (
        bool(re.search(ISO, message)) and not re.sub(r"[,;\s]", "", remainder)
    )


def new_cycle_task(session_id: str, session_expiry: datetime, *, now: datetime,
                   dates=(), as_of=None) -> PendingCycleTask:
    return PendingCycleTask(session_id=session_id, expires_at=min(session_expiry, now + timedelta(minutes=5)),
                            period_start_dates=tuple(dates), as_of=as_of)


def _validate(task: PendingCycleTask) -> str | None:
    if len(task.period_start_dates) > 366:
        return "Supply at most 366 dates."
    try:
        dates = []
        for value in task.period_start_dates:
            if not isinstance(value, str) or not re.fullmatch(ISO, value):
                raise ValueError
            dates.append(date.fromisoformat(value))
        if task.as_of is not None:
            if not isinstance(task.as_of, str) or not re.fullmatch(ISO, task.as_of):
                raise ValueError
            reference = date.fromisoformat(task.as_of)
            if any(value > reference for value in dates):
                return "Period starts cannot be after the reference date. Send the full corrected list or a corrected reference date."
    except (ValueError, TypeError):
        return "Use valid dates in YYYY-MM-DD format; ambiguous dates will not be guessed."
    if len(set(dates)) != len(dates):
        return "Dates must be unique. Send the full corrected list."
    if dates != sorted(dates):
        return "Send the full list from oldest to newest; I will not reorder it automatically."
    return None


def request_input(task: PendingCycleTask) -> TaskTransition:
    error = _validate(task)
    if error:
        return TaskTransition("ask", replace(task, awaiting_confirmation=False), error, "TASK_INPUT_INVALID")
    if len(task.period_start_dates) < 2:
        return TaskTransition("ask", replace(task, awaiting_confirmation=False),
                              "Send at least two period start dates, oldest first, as YYYY-MM-DD. You can include 'as of YYYY-MM-DD' for your local reference date. Type /cancel to stop.", "TASK_DATES_REQUESTED")
    if task.as_of is None:
        return TaskTransition("ask", replace(task, awaiting_confirmation=False),
                              "What local reference date should I use? Reply YYYY-MM-DD or 'as of YYYY-MM-DD'.", "TASK_REFERENCE_REQUESTED")
    message = (
        "Please confirm these starts of separate periods (not spotting): "
        + ", ".join(task.period_start_dates)
        + f". Reference date: {task.as_of}. Reply 'confirm' to calculate, send the full corrected list, or type /cancel."
    )
    return TaskTransition("ask", replace(task, awaiting_confirmation=True), message, "TASK_CONFIRMATION_REQUESTED")


def advance_cycle_task(task: PendingCycleTask, message: str, *, now: datetime) -> TaskTransition:
    if now >= task.expires_at:
        return TaskTransition("cancel", message="The pending calculation expired. Start a new cycle calculation.", event="TASK_EXPIRED")
    reply = normalized_reply(message)
    if reply in CANCEL:
        return TaskTransition("cancel", message="Cycle calculation cancelled; pending dates cleared.", event="TASK_CANCELLED")
    if reply in YES:
        if not task.awaiting_confirmation:
            # A premature yes cannot stand in for dates or a reference date.
            return request_input(replace(task, turns_used=task.turns_used + 1)) if task.turns_used < MAX_TASK_TURNS else TaskTransition("cancel", message="The input limit was reached. Start a new calculation.", event="TASK_TURN_LIMIT")
        if _validate(task) is not None or len(task.period_start_dates) < 2 or task.as_of is None:
            return TaskTransition("cancel", message="Pending inputs could not be validated. Start a new calculation.", event="TASK_STATE_INVALID")
        return TaskTransition("execute", task=task, event="TASK_CONFIRMED")
    if task.turns_used >= MAX_TASK_TURNS:
        return TaskTransition("cancel", message="The input limit was reached. Start a new calculation.", event="TASK_TURN_LIMIT")
    task = replace(task, turns_used=task.turns_used + 1)
    if reply in NO:
        return TaskTransition("ask", replace(task, awaiting_confirmation=False),
                              "Send the full corrected period-start list and 'as of YYYY-MM-DD'. Nothing has been calculated.", "TASK_CORRECTION_REQUESTED")

    if re.search(r"\?|\b(?:what|why|how|explain|research|pubmed)\b", message, re.I):
        return TaskTransition("topic_change", event="TASK_TOPIC_CHANGED")

    # Parse only date lists with optional explicit role labels. Other narratives
    # are not mined for dates (birth dates, appointment dates, etc.).
    reference_matches = list(REFERENCE.finditer(message))
    remainder = REFERENCE.sub(" ", message)
    date_matches = re.findall(ISO, remainder)
    residual = re.sub(ISO, " ", remainder)
    residual = re.sub(r"\b(?:starts?|dates?|period starts?|my period started on|and)\s*:?", " ", residual, flags=re.I)
    residual = re.sub(r"[,;\s]", "", residual)
    if len(reference_matches) > 1 or (residual and (date_matches or re.search(r"\d", message))):
        return TaskTransition("ask", replace(task, awaiting_confirmation=False),
                              "Send only the full period-start list in YYYY-MM-DD format, optionally followed by 'as of YYYY-MM-DD'. I will not guess which dates you mean.", "TASK_INPUT_AMBIGUOUS")
    if not date_matches and not reference_matches:
        if re.search(r"\d", message):
            return TaskTransition("ask", replace(task, awaiting_confirmation=False),
                                  "Use full YYYY-MM-DD dates; month/day order and missing years will not be guessed.", "TASK_INPUT_AMBIGUOUS")
        return TaskTransition("topic_change", event="TASK_TOPIC_CHANGED")

    reference = reference_matches[0].group(1) if reference_matches else task.as_of
    dates = task.period_start_dates
    if date_matches:
        if len(dates) >= 2 and task.as_of is None and not task.awaiting_confirmation and len(date_matches) == 1:
            reference = date_matches[0]
        else:
            # Replacement, never an implicit append or a silent date correction.
            dates = tuple(date_matches)
    updated = replace(task, period_start_dates=dates, as_of=reference, awaiting_confirmation=False)
    error = _validate(updated)
    if error:
        return TaskTransition("ask", replace(task, awaiting_confirmation=False), error, "TASK_INPUT_INVALID")
    return request_input(updated)
