"""Development-only process-local adapter for the pending-task protocol.

The memory owner should supply a shared adapter for multiple workers. This
adapter never persists dates or logs payloads and is distinct from user profiles.
"""

from datetime import datetime

from health_tools.pending_tasks import PendingCycleTask


class InMemoryPendingTaskStore:
    def __init__(self):
        self._tasks: dict[str, PendingCycleTask] = {}

    def purge_expired(self, *, now: datetime) -> None:
        for key in list(self._tasks):
            if now >= self._tasks[key].expires_at:
                self._tasks.pop(key, None)

    def get(self, session_id: str, *, now: datetime) -> PendingCycleTask | None:
        self.purge_expired(now=now)
        return self._tasks.get(session_id)

    def save(self, task: PendingCycleTask, *, now: datetime) -> None:
        if now >= task.expires_at:
            self.delete(task.session_id)
            raise ValueError("Cannot save expired pending task")
        self._tasks[task.session_id] = task

    def delete(self, session_id: str) -> None:
        self._tasks.pop(session_id, None)
