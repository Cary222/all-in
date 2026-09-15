"""Workbench background task runner with multi-platform and worker slot scheduling."""

from __future__ import annotations

import multiprocessing as mp
from dataclasses import dataclass, field
from datetime import datetime
from threading import Event, Lock, Thread, Timer
from typing import Any, Callable
from uuid import uuid4

from allin.throttle import SendWindowChecker


MODE_LABELS = {
    "full": "运行全流程",
    "collect": "单独采集",
    "score": "单独 AI 评分",
    "rescore": "重新评分",
    "greet": "生成招呼语",
    "monitor": "单独监测",
    "deliver": "确认投递",
}

TERMINAL_STATUSES = {"completed", "failed", "stopped"}
ACTIVE_STATUSES = {"running", "stopping"}
DEADLINE_MODES = {"full", "monitor", "deliver"}
GLOBAL_EXCLUSIVE_MODES = {"full", "score", "rescore"}


class TaskAlreadyRunningError(RuntimeError):
    """Raised when a mutually exclusive workbench task is already active."""


@dataclass
class WorkerSlot:
    """Represents an allocated worker slot for a platform or global task."""
    slot_id: str
    platform: str | None = None
    task_id: str | None = None
    worker_type: str = "thread"
    is_exclusive: bool = False


@dataclass
class WorkbenchTask:
    id: str
    mode: str
    label: str
    platform: str | None = None
    slot: str | None = None
    worker_type: str = "thread"
    status: str = "running"
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    deadline_at: str | None = None
    stop_reason: str | None = None
    stop_requested: Event = field(default_factory=Event, repr=False)
    metrics: dict[str, int] = field(default_factory=dict)
    progress: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict, repr=False)

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "mode": self.mode,
            "label": self.label,
            "platform": self.platform,
            "slot": self.slot,
            "worker_type": self.worker_type,
            "status": self.status,
            "logs": list(self.logs),
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deadline_at": self.deadline_at,
            "stop_reason": self.stop_reason,
            "stop_requested": self.stop_requested.is_set(),
            "metrics": dict(self.metrics),
            "progress": dict(self.progress),
        }


Executor = Callable[[WorkbenchTask, dict], None]


def wait_for_initial_monitor_cooldown(
    task: WorkbenchTask,
    config: dict,
    log: Callable[[WorkbenchTask, str], None],
) -> bool:
    """Wait for the full-flow monitor cooldown; return true when cancellation wins."""
    raw_cooldown = config.get("monitor", {}).get("initial_cooldown_minutes", 10)
    try:
        cooldown_sec = max(float(raw_cooldown), 0) * 60
    except (TypeError, ValueError):
        cooldown_sec = 10 * 60
    if cooldown_sec <= 0:
        return False
    log(task, f"发送结束，首次监测将在 {cooldown_sec / 60:g} 分钟冷却后开始")
    if task.stop_requested.wait(cooldown_sec):
        log(task, "首次监测冷却已取消")
        return True
    return False


class WorkbenchTaskRunner:
    def __init__(
        self,
        executors: dict[str, Executor] | None = None,
        *,
        max_slots: int = 4,
        default_worker_type: str = "thread",
    ):
        self._executors = executors or {}
        self.max_slots = max_slots
        self.default_worker_type = default_worker_type
        self._tasks: dict[str, WorkbenchTask] = {}
        self._threads: dict[str, Thread] = {}
        self._processes: dict[str, Any] = {}
        self._slots: dict[str, WorkerSlot] = {}
        self._deadline_timers: dict[str, Timer] = {}
        self._lock = Lock()

    def _resolve_slot(
        self,
        mode: str,
        config: dict,
        platform: str | None = None,
    ) -> tuple[str, str | None, bool]:
        """Resolve slot_id, platform, and is_exclusive."""
        plat = platform or config.get("_platform") or config.get("platform")
        if not plat and isinstance(config.get("_collection_options"), dict):
            plat_order = config["_collection_options"].get("platform_order", [])
            if len(plat_order) == 1:
                plat = plat_order[0]

        if mode in GLOBAL_EXCLUSIVE_MODES or plat is None:
            return "global", plat, True

        return f"platform:{plat}", plat, False

    def _check_conflict_locked(self, slot_id: str, is_exclusive: bool) -> WorkbenchTask | None:
        active_tasks = [t for t in self._tasks.values() if t.status in ACTIVE_STATUSES]
        if not active_tasks:
            return None

        # A globally exclusive task conflicts with any active task
        if is_exclusive:
            return active_tasks[0]

        # An already running globally exclusive task conflicts with incoming platform task
        for task in active_tasks:
            if task.slot == "global" or task.mode in GLOBAL_EXCLUSIVE_MODES:
                return task

        # A task on the exact same platform slot conflicts
        for task in active_tasks:
            if task.slot == slot_id:
                return task

        if len(active_tasks) >= self.max_slots:
            return active_tasks[0]

        return None

    def start(
        self,
        mode: str,
        config: dict,
        *,
        platform: str | None = None,
        worker_type: str | None = None,
        before_start: Callable[[], None] | None = None,
    ) -> dict:
        if mode not in MODE_LABELS:
            raise ValueError(f"Unsupported workbench mode: {mode}")

        slot_id, resolved_plat, is_exclusive = self._resolve_slot(mode, config, platform)
        resolved_worker_type = worker_type or self.default_worker_type

        with self._lock:
            conflict = self._check_conflict_locked(slot_id, is_exclusive)
            if conflict:
                target_desc = f"平台「{resolved_plat}」" if resolved_plat else "全局"
                raise TaskAlreadyRunningError(
                    f"当前已有后台任务「{conflict.label}」正在运行或停止中，请等待其完全结束"
                )

            task = WorkbenchTask(
                id=str(uuid4()),
                mode=mode,
                label=MODE_LABELS[mode],
                platform=resolved_plat,
                slot=slot_id,
                worker_type=resolved_worker_type,
            )
            deadline = _deadline_from_config(mode, config)
            if deadline:
                task.deadline_at = deadline.isoformat(timespec="seconds")
            if deadline and deadline <= datetime.now():
                task.stop_requested.set()
                task.status = "stopped"
                task.stop_reason = "今日发送时间窗口已截止，后台未启动"
                task.logs.append(task.stop_reason)
                task.updated_at = datetime.now().isoformat(timespec="seconds")
                self._tasks[task.id] = task
                return task.snapshot()

            # Persist start settings under the same lock as admission
            if before_start is not None:
                before_start()

            self._tasks[task.id] = task
            self._slots[slot_id] = WorkerSlot(
                slot_id=slot_id,
                platform=resolved_plat,
                task_id=task.id,
                worker_type=resolved_worker_type,
                is_exclusive=is_exclusive,
            )

            if resolved_worker_type == "process":
                try:
                    proc = mp.Process(target=self._run, args=(task, config), daemon=True)
                    self._processes[task.id] = proc
                    proc.start()
                except Exception:
                    # Fallback to Thread if process spawn fails
                    thread = Thread(target=self._run, args=(task, config), daemon=True)
                    self._threads[task.id] = thread
                    thread.start()
            else:
                thread = Thread(target=self._run, args=(task, config), daemon=True)
                self._threads[task.id] = thread
                thread.start()

            if deadline:
                delay_seconds = max((deadline - datetime.now()).total_seconds(), 0)
                timer = Timer(delay_seconds, self._stop_at_deadline, args=(task.id,))
                timer.daemon = True
                self._deadline_timers[task.id] = timer
                timer.start()

            return task.snapshot()

    def status(self, platform: str | None = None) -> dict:
        with self._lock:
            active_tasks = [t for t in self._tasks.values() if t.status in ACTIVE_STATUSES]
            tasks = [task.snapshot() for task in self._tasks.values()]

            active = None
            if platform:
                for t in reversed(active_tasks):
                    if t.platform == platform or t.slot == f"platform:{platform}":
                        active = t
                        break
            if not active and active_tasks:
                active = active_tasks[-1]

            active_by_platform: dict[str, dict] = {}
            for t in active_tasks:
                plat_key = t.platform or t.slot or "global"
                active_by_platform[plat_key] = t.snapshot()

            slots_status = {
                s_id: {
                    "platform": slot.platform,
                    "task_id": slot.task_id,
                    "worker_type": slot.worker_type,
                    "is_exclusive": slot.is_exclusive,
                }
                for s_id, slot in self._slots.items()
            }

            return {
                "active": active.snapshot() if active else None,
                "active_tasks": [t.snapshot() for t in active_tasks],
                "active_by_platform": active_by_platform,
                "slots": slots_status,
                "last_task": tasks[-1] if tasks else None,
                "tasks": tasks,
            }

    def stop(self, task_id: str, reason: str = "用户已请求停止") -> dict:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(task_id)
            if task.status in TERMINAL_STATUSES:
                return task.snapshot()
            task.stop_requested.set()
            task.status = "stopping"
            task.stop_reason = reason
            if reason and (not task.logs or task.logs[-1] != reason):
                task.logs.append(reason)
            task.updated_at = datetime.now().isoformat(timespec="seconds")
            confirmation_event = task.context.get("confirmation_event")
            if isinstance(confirmation_event, Event):
                confirmation_event.set()
            monitor_wakeup_event = task.context.get("monitor_wakeup_event")
            if isinstance(monitor_wakeup_event, Event):
                monitor_wakeup_event.set()

            proc = self._processes.get(task_id)
            if proc and hasattr(proc, "is_alive") and proc.is_alive():
                try:
                    proc.terminate()
                except Exception:
                    pass

            return task.snapshot()

    def stop_platform(self, platform: str, reason: str = "用户已请求停止") -> list[dict]:
        with self._lock:
            target_ids = [
                t.id for t in self._tasks.values()
                if (t.platform == platform or t.slot == f"platform:{platform}") and t.status in ACTIVE_STATUSES
            ]
        results = []
        for tid in target_ids:
            results.append(self.stop(tid, reason))
        return results

    def stop_all(self, reason: str = "用户已请求停止") -> list[dict]:
        with self._lock:
            target_ids = [t.id for t in self._tasks.values() if t.status in ACTIVE_STATUSES]
        results = []
        for tid in target_ids:
            results.append(self.stop(tid, reason))
        return results

    def wait(self, timeout: float | None = None) -> None:
        threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout=timeout)
        procs = list(self._processes.values())
        for proc in procs:
            if hasattr(proc, "join"):
                proc.join(timeout=timeout)

    def _run(self, task: WorkbenchTask, config: dict) -> None:
        try:
            executor = self._executors.get(task.mode)
            if executor:
                executor(task, config)
            with self._lock:
                if task.stop_requested.is_set():
                    task.status = "stopped"
                else:
                    task.status = "completed"
                task.updated_at = datetime.now().isoformat(timespec="seconds")
                self._slots.pop(task.slot or "", None)
        except Exception as exc:
            with self._lock:
                if task.stop_requested.is_set():
                    task.status = "stopped"
                    task.error = None
                else:
                    task.status = "failed"
                    task.error = str(exc)
                task.updated_at = datetime.now().isoformat(timespec="seconds")
                self._slots.pop(task.slot or "", None)
        finally:
            with self._lock:
                timer = self._deadline_timers.pop(task.id, None)
                self._slots.pop(task.slot or "", None)
            if timer:
                timer.cancel()

    def _stop_at_deadline(self, task_id: str) -> None:
        try:
            self.stop(task_id, "已到发送时间窗口截止时间，后台自动停止")
        except KeyError:
            return

    def _active_task_locked(self) -> WorkbenchTask | None:
        for task in self._tasks.values():
            if task.status in ACTIVE_STATUSES:
                return task
        return None


def _deadline_from_config(mode: str, config: dict) -> datetime | None:
    """Resolve the automatic stop deadline for long-running/send tasks."""
    if mode not in DEADLINE_MODES:
        return None
    throttle = config.get("throttle", {}) if isinstance(config, dict) else {}
    windows = throttle.get("send_windows", [])
    if not isinstance(windows, list):
        return None
    return SendWindowChecker(windows).latest_end_datetime()
