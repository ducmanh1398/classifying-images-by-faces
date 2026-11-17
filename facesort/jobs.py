"""JobRunner: một tác vụ nặng chạy nền tại một thời điểm (UI_PLAN mục 2)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from .errors import FacesortError

log = logging.getLogger("facesort.jobs")

JobFn = Callable[[Callable[[str, int, int], None], Callable[[], bool]], dict[str, Any]]


class JobBusy(FacesortError):
    pass


class JobRunner:
    def __init__(self) -> None:
        self._mutex = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._state: dict[str, Any] = {"state": "idle"}
        self._step_started = 0.0

    # ------------------------------------------------------------ truy vấn
    def snapshot(self) -> dict[str, Any]:
        with self._mutex:
            return dict(self._state)

    def is_running(self) -> bool:
        with self._mutex:
            return self._state.get("state") == "running"

    def wait(self, timeout: float | None = None) -> None:
        t = self._thread
        if t is not None:
            t.join(timeout)

    # ------------------------------------------------------------ điều khiển
    def start(
        self,
        kind: str,
        fn: JobFn,
        lock: AbstractContextManager | None = None,
    ) -> None:
        with self._mutex:
            if self._state.get("state") == "running":
                raise JobBusy("Đang có một tác vụ chạy. Hãy chờ xong hoặc bấm Dừng.")
            self._cancel.clear()
            self._state = {
                "state": "running",
                "kind": kind,
                "step": "start",
                "i": 0,
                "total": 0,
                "eta_seconds": None,
                "error": None,
                "result": None,
                "cancel_requested": False,
            }
            self._step_started = time.monotonic()
            self._thread = threading.Thread(
                target=self._run, args=(fn, lock), daemon=True, name=f"job-{kind}"
            )
            self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()
        with self._mutex:
            if self._state.get("state") == "running":
                self._state["cancel_requested"] = True

    # ------------------------------------------------------------ nội bộ
    def _progress(self, step: str, i: int, total: int) -> None:
        with self._mutex:
            if self._state.get("state") != "running":
                return
            if step != self._state["step"]:
                self._step_started = time.monotonic()
            eta = None
            if total > 0 and i > 0:
                elapsed = time.monotonic() - self._step_started
                eta = int(elapsed / i * (total - i))
            self._state.update(step=step, i=i, total=total, eta_seconds=eta)

    def _finish(self, **fields: Any) -> None:
        with self._mutex:
            self._state.update(fields)
            self._state["eta_seconds"] = None

    def _run(self, fn: JobFn, lock: AbstractContextManager | None) -> None:
        try:
            if lock is not None:
                with lock:
                    result = fn(self._progress, self._cancel.is_set)
            else:
                result = fn(self._progress, self._cancel.is_set)
            cancelled = bool(result.get("cancelled")) or self._cancel.is_set()
            self._finish(state="cancelled" if cancelled else "done", result=result)
        except FacesortError as e:
            self._finish(state="error", error=str(e))
        except Exception as e:  # noqa: BLE001 - mọi lỗi phải hiện ra cho người dùng
            log.exception("Tác vụ lỗi")
            self._finish(state="error", error=f"Lỗi không mong muốn: {e}")
