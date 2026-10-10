"""Aggregate completed invocations without storing arguments or results."""

import time

from .storage import DesktopState


class DesktopUsageSink:
    def __init__(self, state: DesktopState) -> None:
        self.state = state

    def record_invocation_completed(self, event) -> None:
        tool = event.started.tool
        if tool.connector_id is None or tool.operation_name is None:
            return
        if getattr(event, "failure_category", None) in ("authorization", "validation"):
            return
        identity = f"{tool.connector_id}.{tool.operation_name}"
        usage = self.state.data.setdefault("tool_usage", {}).setdefault(
            identity, {"succeeded": 0, "failed": 0}
        )
        usage["succeeded" if event.outcome == "success" else "failed"] += 1
        day = str(int(time.time()) // 86400)
        daily = self.state.data.setdefault("daily_calls", {})
        daily[day] = daily.get(day, 0) + 1
        self.state.data.setdefault("daily_tracking_started", int(day))
        self.state.save()
