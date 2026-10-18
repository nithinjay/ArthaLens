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


class _OutputTooLarge(Exception):
    pass


STDERR_TAIL_BYTES = 64 * 1024


async def _read_capped(stream: asyncio.StreamReader, cap: int) -> bytes:
    """Read until EOF, failing as soon as more than ``cap`` bytes arrive (never buffers more)."""
    buf = bytearray()
    while chunk := await stream.read(64 * 1024):
        if len(buf) + len(chunk) > cap:
            raise _OutputTooLarge
        buf += chunk
    return bytes(buf)


async def _read_tail(stream: asyncio.StreamReader, keep: int) -> bytes:
    """Drain a stream, keeping only its last ``keep`` bytes (for error messages)."""
    buf = bytearray()
    while chunk := await stream.read(64 * 1024):
        buf += chunk
        del buf[:-keep]
    return bytes(buf)


async def run_sandboxed(
    command: Sequence[str], stdin: bytes, limits: SandboxLimits = DEFAULT_LIMITS
) -> bytes:
    """Run ``command`` with ``stdin``; return stdout. Raise SandboxError on any failure.

    Output is read as it is produced and the worker is killed the moment it exceeds
    ``max_output_bytes``, so a hostile document can't make this process buffer gigabytes.
    """
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_child_env(),
        preexec_fn=lambda: _apply_limits(limits),
        close_fds=True,
    )
    assert proc.stdin and proc.stdout and proc.stderr  # noqa: S101 - PIPE guarantees these

    async def feed() -> None:
        try:
            proc.stdin.write(stdin)  # type: ignore[union-attr]
            await proc.stdin.drain()  # type: ignore[union-attr]
        except (BrokenPipeError, ConnectionResetError):
            pass  # the worker stopped reading; its exit status will say why
        finally:
            proc.stdin.close()  # type: ignore[union-attr]

    too_large = False
    try:
        async with asyncio.timeout(limits.wall_seconds):
            try:
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(feed())
                    out_task = tg.create_task(_read_capped(proc.stdout, limits.max_output_bytes))
                    err_task = tg.create_task(_read_tail(proc.stderr, STDERR_TAIL_BYTES))
                    tg.create_task(proc.wait())
            except* _OutputTooLarge:
                too_large = True
    except TimeoutError:
        await _kill(proc)
        raise SandboxError("timeout", f"worker exceeded {limits.wall_seconds}s") from None
    if too_large:
        await _kill(proc)
        raise SandboxError("output_too_large", f"more than {limits.max_output_bytes} bytes")

    if proc.returncode != 0:
        tail = err_task.result().decode("utf-8", "replace").strip().splitlines()[-1:]
        raise SandboxError(
            "worker_failed", f"exit {proc.returncode}: {(tail or ['no stderr'])[0][:200]}"
        )
    return out_task.result()


async def _kill(proc: asyncio.subprocess.Process) -> None:
    """Kill the worker and reap it. The pipes must be drained too: asyncio pauses a pipe whose
    reader stopped early, and then never sees EOF, so wait() alone would hang."""
    if proc.returncode is None:
        proc.kill()
    await asyncio.gather(*(_drain(s) for s in (proc.stdout, proc.stderr) if s is not None))
    await proc.wait()


async def _drain(stream: asyncio.StreamReader) -> None:
    while await stream.read(64 * 1024):
        pass
