from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager

STAGES = ("sparse", "stats", "features", "gate", "encode", "vector", "fusion")


class NullTraceSink:
    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        yield

    def increment(self, name: str, amount: int = 1) -> None:
        pass


class TraceSink:
    """One request at a time; safe to aggregate stages from parallel branch threads."""

    def __init__(self, *, detailed: bool = True):
        self.detailed = detailed
        self._lock = threading.Lock()
        self._active = False
        self._durations: Counter[str] = Counter()
        self._stage_calls: Counter[str] = Counter()
        self._counters: Counter[str] = Counter()

    def begin_request(self) -> None:
        if self._active:
            raise RuntimeError("a trace request is already active")
        self._durations.clear()
        self._stage_calls.clear()
        self._counters.clear()
        self._active = True

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        if name not in STAGES:
            raise ValueError(f"unregistered stage {name}")
        if not self._active:
            yield
            return
        start = time.perf_counter_ns() if self.detailed else 0
        try:
            yield
        finally:
            with self._lock:
                self._stage_calls[name] += 1
                if self.detailed:
                    self._durations[name] += time.perf_counter_ns() - start

    def increment(self, name: str, amount: int = 1) -> None:
        if self._active:
            with self._lock:
                self._counters[name] += amount

    def end_request(self) -> dict:
        if not self._active:
            raise RuntimeError("no active trace request")
        self._active = False
        result = {
            f"{stage}_ns": (self._durations[stage] if self.detailed else None)
            if self._stage_calls[stage]
            else 0
            for stage in STAGES
        }
        result.update(
            {
                "encoder_calls": self._counters["encoder_calls"],
                "vector_search_calls": self._counters["vector_search_calls"],
                "stage_calls": dict(self._stage_calls),
                "detailed_stages": self.detailed,
            }
        )
        return result
