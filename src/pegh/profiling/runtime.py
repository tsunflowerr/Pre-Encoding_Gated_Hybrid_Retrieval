from __future__ import annotations

import ctypes
import os
import platform
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import psutil
import yaml

from pegh.dense.index import package_versions

_WINDOWS_JOB_HANDLES: list[int] = []


@dataclass(frozen=True)
class RuntimeSettings:
    logical_cpus: int = 4
    memory_limit_bytes: int = 8_000_000_000
    enforce_memory_limit: bool = True
    online_batch_size: int = 1
    concurrency: int = 1
    warmup_queries: int = 50
    repetitions: int = 5
    seed: int = 42
    detailed_stages: bool = False
    memory_sample_seconds: float = 0.02
    worker_timeout_seconds: float = 3600.0

    def __post_init__(self) -> None:
        if self.online_batch_size != 1 or self.concurrency != 1:
            raise ValueError("online protocol requires batch_size=concurrency=1")
        if min(self.logical_cpus, self.memory_limit_bytes, self.repetitions) < 1:
            raise ValueError("invalid resource limit/repetitions")
        if self.warmup_queries < 0 or self.memory_sample_seconds <= 0:
            raise ValueError("invalid warmup/sampling interval")

    @classmethod
    def from_yaml(cls, path: str | Path) -> RuntimeSettings:
        with Path(path).open(encoding="utf-8") as stream:
            return cls(**yaml.safe_load(stream)["runtime"])


def _windows_memory_limit(limit: int) -> str:
    from ctypes import wintypes

    class BasicLimit(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IOCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_ulonglong)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class ExtendedLimit(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimit),
            ("IoInfo", IOCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedLimit()
    limits.BasicLimitInformation.LimitFlags = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    limits.ProcessMemoryLimit = limit
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        error = ctypes.get_last_error()
        kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    _WINDOWS_JOB_HANDLES.append(handle)
    return "windows_job_process_commit_limit"


def configure_resources(settings: RuntimeSettings) -> dict:
    process = psutil.Process()
    original = process.cpu_affinity()
    selected = sorted(original)[: settings.logical_cpus]
    process.cpu_affinity(selected)
    memory_kind = "observed_only"
    if settings.enforce_memory_limit:
        if sys.platform == "win32":
            memory_kind = _windows_memory_limit(settings.memory_limit_bytes)
        elif sys.platform.startswith("linux"):
            import resource

            current_soft, current_hard = resource.getrlimit(resource.RLIMIT_AS)
            maximum = settings.memory_limit_bytes
            if current_hard != resource.RLIM_INFINITY:
                maximum = min(maximum, current_hard)
            if current_soft != resource.RLIM_INFINITY:
                maximum = min(maximum, current_soft)
            resource.setrlimit(resource.RLIMIT_AS, (maximum, current_hard))
            memory_kind = "linux_address_space_limit_not_cgroup"
        else:
            raise RuntimeError("strict memory enforcement is unsupported on this platform")
    return {
        "requested_logical_cpus": settings.logical_cpus,
        "effective_affinity": process.cpu_affinity(),
        "memory_limit_bytes": settings.memory_limit_bytes,
        "memory_limit_kind": memory_kind,
        "memory_semantics_note": (
            "Windows cap applies to process committed memory; Linux fallback caps address space. "
            "RSS is measured separately; neither is described as an external container/cgroup cap."
        ),
    }


def runtime_manifest(settings: RuntimeSettings, resources: dict) -> dict:
    def git(*arguments: str) -> str | None:
        result = subprocess.run(["git", *arguments], capture_output=True, text=True, check=False)
        return result.stdout.strip() if result.returncode == 0 else None

    return {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cpus_host": psutil.cpu_count(),
        "physical_cores_host": psutil.cpu_count(False),
        "host_ram_bytes": psutil.virtual_memory().total,
        "available_ram_before_load_bytes": psutil.virtual_memory().available,
        "system_cpu_percent_before_load": psutil.cpu_percent(interval=0.2),
        "settings": asdict(settings),
        "resources": resources,
        "package_versions": package_versions(),
        "git_commit": git("rev-parse", "HEAD"),
        "git_branch": git("branch", "--show-current"),
        "git_status": git("status", "--porcelain"),
        "pid": os.getpid(),
        "cwd": str(Path.cwd()),
        "thread_environment": {
            key: os.environ.get(key)
            for key in (
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "TOKENIZERS_PARALLELISM",
            )
        },
    }


class MemorySampler:
    def __init__(self, interval: float):
        self.interval = interval
        self.samples: list[dict] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start = 0.0

    def start(self) -> None:
        self._start = time.perf_counter()
        self._sample()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _sample(self) -> None:
        info = psutil.Process().memory_info()
        peak = getattr(info, "peak_wset", None)
        if peak is None and sys.platform.startswith("linux"):
            import resource

            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        self.samples.append(
            {
                "elapsed_seconds": time.perf_counter() - self._start,
                "rss_bytes": info.rss,
                "vms_bytes": info.vms,
                "os_peak_rss_bytes": peak,
            }
        )

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self._sample()

    def stop(self) -> dict:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        self._sample()
        os_peaks = [
            s["os_peak_rss_bytes"] for s in self.samples if s["os_peak_rss_bytes"] is not None
        ]
        return {
            "sample_interval_seconds": self.interval,
            "sampled_peak_rss_bytes": max(s["rss_bytes"] for s in self.samples),
            "os_peak_rss_bytes": max(os_peaks) if os_peaks else None,
            "os_peak_source": (
                "psutil.peak_wset"
                if sys.platform == "win32"
                else "getrusage.ru_maxrss_kib"
                if os_peaks
                else None
            ),
            "rss_source": "psutil.Process.memory_info.rss",
        }
