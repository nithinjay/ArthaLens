"""Run an untrusted-input parser in a separate, resource-limited process (threat model T-21).

A malicious or malformed document can at worst crash, hang or exhaust its own worker:
- isolated interpreter (``python -I``): no PYTHONPATH, user site or current-directory imports
- minimal environment: secrets such as DATABASE_URL or GEMINI_API_KEY are never inherited
- CPU, address-space, file-size and open-file limits (enforced on Linux; macOS ignores some)
- wall-clock timeout with kill, and a cap on how much output is read

Network isolation is not possible from inside a process; the container's egress policy
covers that (Milestone 11).
"""

import asyncio
import os
import resource
import sys
from collections.abc import Sequence
from dataclasses import dataclass


class SandboxError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class SandboxLimits:
    wall_seconds: float = 180.0
    cpu_seconds: int = 150
    memory_bytes: int = 2 * 1024**3
    max_file_bytes: int = 256 * 1024**2  # OCR writes page images to a temp dir
    max_open_files: int = 256
    max_output_bytes: int = 64 * 1024**2


def _apply_limits(limits: SandboxLimits) -> None:  # runs in the child, before exec
    pairs = (
        (resource.RLIMIT_CPU, limits.cpu_seconds),
        (resource.RLIMIT_AS, limits.memory_bytes),
        (resource.RLIMIT_FSIZE, limits.max_file_bytes),
        (resource.RLIMIT_NOFILE, limits.max_open_files),
        (resource.RLIMIT_CORE, 0),
    )
    for which, value in pairs:
        try:
            resource.setrlimit(which, (value, value))
        except (ValueError, OSError):
            pass  # not supported on this platform (e.g. RLIMIT_AS on macOS)


def _child_env() -> dict[str, str]:
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "OMP_THREAD_LIMIT": "1"}
    for name in ("TESSDATA_PREFIX", "TMPDIR"):
        if name in os.environ:
            env[name] = os.environ[name]
    return env


DEFAULT_LIMITS = SandboxLimits()


def python_module(module: str, *args: str) -> list[str]:
    return [sys.executable, "-I", "-m", module, *args]


async def run_sandboxed(
    command: Sequence[str], stdin: bytes, limits: SandboxLimits = DEFAULT_LIMITS
) -> bytes:
    """Run ``command`` with ``stdin``; return stdout. Raise SandboxError on any failure."""
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_child_env(),
        preexec_fn=lambda: _apply_limits(limits),
        close_fds=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(stdin), limits.wall_seconds)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise SandboxError("timeout", f"worker exceeded {limits.wall_seconds}s") from None
    if proc.returncode != 0:
        tail = stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no stderr"]
        raise SandboxError("worker_failed", f"exit {proc.returncode}: {tail[0][:200]}")
    if len(stdout) > limits.max_output_bytes:
        raise SandboxError("output_too_large", f"{len(stdout)} bytes")
    return stdout
