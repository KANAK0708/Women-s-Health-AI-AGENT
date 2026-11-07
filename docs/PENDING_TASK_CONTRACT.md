# Pending cycle task contract v1

Ownership: tools/orchestration owns transitions, confirmation, corrections, and
execution. The memory owner may implement storage through `PendingTaskStore` in
`health_tools/pending_tasks.py`. Existing `SessionMemory` and patient-profile
schemas have not changed. No database implementation is added here.

## Current CLI behavior

```bash
python3 main.py --remember
```

Example conversation using synthetic dates:

```text
You: Calculate cycle intervals
Assistant: Send at least two period start dates ...
You: 2026-08-01, 2026-09-05
Assistant: What local reference date should I use? ...
You: 2026-11-07
Assistant: Please confirm these starts ...
You: confirm
Assistant: Recorded intervals: 35 days. ...
```

Dates and a reference date can also be supplied together:
`2026-08-01, 2026-09-05; as of 2026-11-07`.
Only explicit ISO dates and simple date lists/labels are recognized. Slash dates,
missing years, relative dates, and mixed narratives are not guessed. The display
asks users to confirm starts of separate periods rather than spotting.

Before confirmation, a date list replaces the entire proposed start list; it is
never implicitly appended. `as of YYYY-MM-DD` changes just the reference date.
Every correction requires a new confirmation. A premature yes cannot substitute
for missing inputs. A no requires another review before a later yes can execute.

`/cancel` clears the task. A new question clears the task and is routed normally.
Urgent/scope stops, minor-user routing, retention withdrawal, `/forget`, task
expiry, session expiry, and normal CLI exit clear pending state. After execution,
the task is consumed before running the calculator; replaying `confirm` does not
calculate again. Direct complete CLI/API inputs remain caller-confirmed inputs
and do not add a redundant confirmation step.

Without session-context consent, the service creates no pending task. It explains
that multi-turn collection needs consent; complete explicit inputs still work.
Task input prompts have their own six-reply limit and do not consume the existing
two-turn medical-context clarification budget.

## Payload and storage interface

`PendingCycleTask` fields:

| Field | Meaning |
| --- | --- |
| `session_id` | Owning active session key |
| `expires_at` | Timezone-aware absolute deadline |
| `period_start_dates` | Proposed ISO date strings, oldest first |
| `as_of` | Proposed local reference date or null |
| `awaiting_confirmation` | True only after valid, complete inputs were shown |
| `turns_used` | Consumed task-input replies |
| `schema_version` | `1.0` |

Implement `get(session_id, now=...)`, `save(task, now=...)`, `delete(session_id)`,
and `purge_expired(now=...)`. Expiry is the earlier of five minutes from task
creation or the session's expiry. Updates must not extend it. Missing/expired
tasks return null; saves of expired tasks fail. Return isolated immutable values.
Serialized timestamps must retain their timezone, and input schema validation is
the adapter's responsibility. Never log the payload or put it in the evidence DB.

`app/workflow/task_store.py` is a development-only process-local adapter. It does
not support multiple workers, durable restart recovery, or distributed locking.
For a Redis implementation, coordinate atomic consume/delete behavior before
deployment; two concurrent confirmations must not both execute. The application
must also enforce session ownership at its eventual authenticated API boundary.

The service owns consent/lifecycle calls. A task-store exception stops pending
flows for that application instance so a later confirmation cannot reuse stale
inputs. Urgent/scope routing still runs. Deletion failures are not reported as
successful deletion. A production shared adapter needs tested recovery/revocation
semantics; no compliance or clinical-readiness claim is made by this interface.

## Acceptance checks for a future shared adapter

- Same conversation transitions with no raw date logging.
- Consent off means no task writes; revocation and deletion remove task keys.
- Expiry is enforced on read/write and never refreshed by corrections.
- Keys are isolated; a different session cannot confirm another task.
- Atomic consumption rejects duplicate/concurrent confirmations.
- Task-store failures do not block urgent messages or permit stale execution.

The app currently passes the protocol through `HealthApplication(pending_task_store=...)`.
Please coordinate interface changes rather than adding pending dates to
`MinimalPatientContext` independently.
