"""Fail-closed bounded execution for one POSIX process group.

Release-bearing commands must not be considered complete merely because their
direct parent exited.  A command can leave an unreferenced descendant alive or
keep a captured output descriptor open after the parent reports success.  This
module owns that lifecycle: every command starts a new session, every exit path
terminates the complete process group, and output is returned only after the
group is gone and its pipe reached EOF.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from typing import BinaryIO, Callable, Mapping, Sequence


DEFAULT_TERM_TIMEOUT_SECONDS = 5.0
DEFAULT_KILL_TIMEOUT_SECONDS = 5.0
DEFAULT_DRAIN_TIMEOUT_SECONDS = 5.0
_POLL_INTERVAL_SECONDS = 0.02
_READ_CHUNK_BYTES = 64 * 1024
_MAX_READ_CHUNKS_PER_PASS = 16
_MAX_PROCESS_ENVIRONMENT_BYTES = 4 * 1024 * 1024
_MAX_PROCESS_INPUT_BYTES = 16 * 1024 * 1024
_PROCESS_MARKER_KEY = "WIKI_VIVA_INTERNAL_PROCESS_AUTHORITY"
_PROCESS_MARKER_ATTRIBUTE = "_wiki_viva_process_authority"


class ProcessSafetyError(RuntimeError):
    """A bounded process could not satisfy its fail-closed lifecycle."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class BoundedProcessResult:
    returncode: int
    output: bytes


class _DarwinProcessInfo(ctypes.Structure):
    # proc_bsdinfo from <libproc.h>.  Only pbi_uid is used; the complete layout
    # is retained so proc_pidinfo can enforce the exact structure size.
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("pbi_rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


def _valid_marker_chain(value: str) -> bool:
    tokens = value.split(":")
    return 1 <= len(tokens) <= 16 and all(
        len(token) == 64
        and token.isascii()
        and all(character in "0123456789abcdef" for character in token)
        for token in tokens
    )


def _environment_contains_marker(raw: bytes, marker: bytes) -> bool:
    prefix = f"{_PROCESS_MARKER_KEY}=".encode("ascii")
    for item in raw.split(b"\0"):
        if item.startswith(prefix) and marker in item[len(prefix) :].split(b":"):
            return True
    return False


def _linux_marked_processes(marker: bytes) -> set[int]:
    proc = Path("/proc")
    if not proc.is_dir():
        raise ProcessSafetyError(
            "process_tree_audit_unavailable",
            "the Linux descendant process audit is unavailable",
        )
    result: set[int] = set()
    for candidate in proc.iterdir():
        if not candidate.name.isdecimal():
            continue
        pid = int(candidate.name)
        try:
            metadata = candidate.stat()
        except (FileNotFoundError, ProcessLookupError):
            continue
        except OSError as exc:
            raise ProcessSafetyError(
                "process_tree_audit_unavailable",
                "the Linux descendant process audit failed",
            ) from exc
        if metadata.st_uid != os.getuid():
            continue
        try:
            descriptor = os.open(
                candidate / "environ", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            )
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        try:
            raw = bytearray()
            while len(raw) <= _MAX_PROCESS_ENVIRONMENT_BYTES:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                raw.extend(chunk)
            if len(raw) > _MAX_PROCESS_ENVIRONMENT_BYTES:
                raise ProcessSafetyError(
                    "process_tree_audit_unavailable",
                    "a Linux process environment exceeded the audit bound",
                )
            if _environment_contains_marker(bytes(raw), marker):
                result.add(pid)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        finally:
            os.close(descriptor)
    return result


def _darwin_marked_processes(marker: bytes) -> set[int]:
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        libc = ctypes.CDLL(None, use_errno=True)
    except OSError as exc:
        raise ProcessSafetyError(
            "process_tree_audit_unavailable",
            "the Darwin descendant process audit is unavailable",
        ) from exc

    proc_listallpids = libproc.proc_listallpids
    proc_listallpids.argtypes = (ctypes.c_void_p, ctypes.c_int)
    proc_listallpids.restype = ctypes.c_int
    proc_pidinfo = libproc.proc_pidinfo
    proc_pidinfo.argtypes = (
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    )
    proc_pidinfo.restype = ctypes.c_int
    sysctl = libc.sysctl
    sysctl.argtypes = (
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
        ctypes.c_size_t,
    )
    sysctl.restype = ctypes.c_int

    count = proc_listallpids(None, 0)
    if count <= 0 or count > 1_000_000:
        raise ProcessSafetyError(
            "process_tree_audit_unavailable",
            "the Darwin process inventory is invalid",
        )
    pids = (ctypes.c_int * (count + 256))()
    listed = proc_listallpids(pids, ctypes.sizeof(pids))
    if listed < 0 or listed > len(pids):
        raise ProcessSafetyError(
            "process_tree_audit_unavailable",
            "the Darwin process inventory could not be read",
        )

    result: set[int] = set()
    expected_info_size = ctypes.sizeof(_DarwinProcessInfo)
    for pid in pids[:listed]:
        if pid <= 0:
            continue
        info = _DarwinProcessInfo()
        read_size = proc_pidinfo(
            pid, 3, 0, ctypes.byref(info), expected_info_size  # PROC_PIDTBSDINFO
        )
        if read_size != expected_info_size or info.pbi_uid != os.getuid():
            continue
        mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2
        size = ctypes.c_size_t(0)
        if sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
            continue
        if size.value <= 0 or size.value > _MAX_PROCESS_ENVIRONMENT_BYTES:
            continue
        buffer = ctypes.create_string_buffer(size.value)
        if sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) != 0:
            continue
        if _environment_contains_marker(buffer.raw[: size.value], marker):
            result.add(pid)
    return result


def _marked_processes(marker: str | None) -> set[int]:
    if marker is None:
        return set()
    encoded = marker.encode("ascii")
    if sys.platform.startswith("linux"):
        return _linux_marked_processes(encoded)
    if sys.platform == "darwin":
        return _darwin_marked_processes(encoded)
    raise ProcessSafetyError(
        "process_tree_audit_unavailable",
        "the descendant process audit is unavailable on this platform",
    )


def start_process_group(
    argv: Sequence[str],
    *,
    cwd: os.PathLike[str] | str,
    env: Mapping[str, str],
    stdin: int | BinaryIO | None,
    stdout: int | BinaryIO | None,
    stderr: int | BinaryIO | None,
    popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
) -> subprocess.Popen[bytes]:
    """Start one marked new session whose escaped descendants remain auditable."""

    ambient_chain = os.environ.get(_PROCESS_MARKER_KEY)
    explicit_chain = env.get(_PROCESS_MARKER_KEY)
    if (
        ambient_chain is not None
        and explicit_chain is not None
        and ambient_chain != explicit_chain
    ):
        raise ProcessSafetyError(
            "process_marker_conflict",
            "the bounded process environment conflicts with inherited authority",
        )
    inherited_chain = explicit_chain or ambient_chain
    if inherited_chain is not None and not _valid_marker_chain(inherited_chain):
        raise ProcessSafetyError(
            "process_marker_invalid",
            "the inherited bounded-process authority is invalid",
        )
    marker = secrets.token_hex(32)
    process_environment = dict(env)
    process_environment[_PROCESS_MARKER_KEY] = (
        f"{inherited_chain}:{marker}" if inherited_chain else marker
    )
    process: subprocess.Popen[bytes] | None = None
    try:
        process = popen_factory(
            [str(value) for value in argv],
            cwd=cwd,
            env=process_environment,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        setattr(process, _PROCESS_MARKER_ATTRIBUTE, marker)
    except BaseException as active_error:
        if process is not None:
            try:
                setattr(process, _PROCESS_MARKER_ATTRIBUTE, marker)
                terminate_process_group(process)
            except BaseException as cleanup_error:
                raise ProcessSafetyError(
                    "process_group_cleanup_failed",
                    "the interrupted process start could not be terminated and verified",
                ) from cleanup_error
        raise active_error
    return process


def _process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Darwin can transiently report EPERM while the final group member is
        # becoming unreapable by this process.  Treat it as still present; the
        # bounded TERM/KILL wait must eventually observe ESRCH or fail closed.
        return True
    return True


def _closure_members(pgid: int, marker: str | None) -> tuple[bool, set[int]]:
    marked = _marked_processes(marker)
    marked.discard(os.getpid())
    return _process_group_exists(pgid), marked


def _signal_process_closure(pgid: int, marker: str | None, sig: int) -> None:
    if _process_group_exists(pgid):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Darwin can transiently report EPERM after the session leader has
            # exited but before the empty process group reports ESRCH.  Do not
            # claim success here: the bounded closure wait below must still
            # observe the group disappear, otherwise cleanup fails closed.
            pass
    for pid in _marked_processes(marker):
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            raise ProcessSafetyError(
                "process_tree_unverifiable",
                "a marked descendant could not be terminated",
            ) from exc


def _wait_for_process_closure_exit(
    process: subprocess.Popen[bytes],
    pgid: int,
    marker: str | None,
    *,
    timeout: float,
) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        process.poll()
        group_exists, marked = _closure_members(pgid, marker)
        if not group_exists and not marked:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(_POLL_INTERVAL_SECONDS, remaining))


def terminate_process_group(
    process: subprocess.Popen[bytes],
    *,
    term_timeout: float = DEFAULT_TERM_TIMEOUT_SECONDS,
    kill_timeout: float = DEFAULT_KILL_TIMEOUT_SECONDS,
) -> None:
    """Terminate and verify the complete session led by ``process``.

    ``run_bounded_process`` always uses ``start_new_session=True``, so the
    direct child's pid is also the immutable pgid for its descendant closure.
    The pgid can remain alive after the parent has already been reaped.
    """

    pgid = int(process.pid)
    if pgid <= 1:
        raise ProcessSafetyError(
            "process_group_invalid", "the bounded process group is invalid"
        )

    marker = getattr(process, _PROCESS_MARKER_ATTRIBUTE, None)
    if marker is not None and (
        not isinstance(marker, str) or len(marker) != 64 or not marker.isascii()
    ):
        raise ProcessSafetyError(
            "process_marker_invalid", "the bounded process marker is invalid"
        )

    _signal_process_closure(pgid, marker, signal.SIGTERM)
    if not _wait_for_process_closure_exit(process, pgid, marker, timeout=term_timeout):
        _signal_process_closure(pgid, marker, signal.SIGKILL)
        if not _wait_for_process_closure_exit(
            process, pgid, marker, timeout=kill_timeout
        ):
            raise ProcessSafetyError(
                "process_tree_survived",
                "the bounded descendant closure survived SIGTERM and SIGKILL",
            )

    # Poll performs the final waitpid for a direct child that already exited.
    # A live direct child with no matching pgid would violate the new-session
    # invariant and must never be treated as a completed command.
    if process.poll() is None:
        raise ProcessSafetyError(
            "process_group_unverifiable",
            "the bounded parent survived outside its certified process group",
        )


def _read_available(
    stream: BinaryIO,
    output: bytearray,
    *,
    output_limit: int,
    retain_output: bool,
) -> tuple[bool, bool]:
    """Drain currently available bytes without blocking.

    Returns ``(eof, output_limit_exceeded)``.  Once a limit is exceeded the
    caller can continue draining without retaining attacker-controlled bytes.
    """

    exceeded = False
    chunks_read = 0
    while chunks_read < _MAX_READ_CHUNKS_PER_PASS:
        try:
            chunk = os.read(stream.fileno(), _READ_CHUNK_BYTES)
        except BlockingIOError:
            return False, exceeded
        except InterruptedError:
            continue
        if not chunk:
            return True, exceeded
        chunks_read += 1
        if retain_output:
            remaining = output_limit + 1 - len(output)
            if remaining > 0:
                output.extend(chunk[:remaining])
            if len(chunk) > remaining or len(output) > output_limit:
                return False, True
    return False, exceeded


def _drain_to_eof(
    stream: BinaryIO,
    output: bytearray,
    *,
    output_limit: int,
    retain_output: bool,
    timeout: float,
) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    exceeded = False
    while True:
        eof, newly_exceeded = _read_available(
            stream,
            output,
            output_limit=output_limit,
            retain_output=retain_output and not exceeded,
        )
        exceeded = exceeded or newly_exceeded
        if eof:
            return exceeded
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProcessSafetyError(
                "process_pipe_survived",
                "the bounded process output pipe remained open after teardown",
            )
        time.sleep(min(_POLL_INTERVAL_SECONDS, remaining))


def run_bounded_process(
    argv: Sequence[str],
    *,
    cwd: os.PathLike[str] | str,
    env: Mapping[str, str],
    timeout: float,
    output_limit: int,
    input_bytes: bytes | None = None,
    input_limit: int = _MAX_PROCESS_INPUT_BYTES,
    stderr: int | BinaryIO | None = subprocess.STDOUT,
    popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    term_timeout: float = DEFAULT_TERM_TIMEOUT_SECONDS,
    kill_timeout: float = DEFAULT_KILL_TIMEOUT_SECONDS,
    drain_timeout: float = DEFAULT_DRAIN_TIMEOUT_SECONDS,
) -> BoundedProcessResult:
    """Run one bounded command and return output only after verified teardown.

    The error ``reason`` values ``timeout`` and ``output_limit`` are stable so
    callers can preserve their domain-specific public error codes.
    """

    if timeout <= 0 or output_limit < 0 or input_limit < 0:
        raise ValueError("bounded process limits must be positive")
    if input_bytes is not None and (
        not isinstance(input_bytes, bytes) or len(input_bytes) > input_limit
    ):
        raise ProcessSafetyError(
            "process_input_oversized",
            "the bounded process input exceeds its fixed authority",
        )

    output = bytearray()
    trigger: str | None = None
    returncode: int | None = None
    cleanup_error: BaseException | None = None
    pipe_error: BaseException | None = None
    active_error: BaseException | None = None
    pipe_is_nonblocking = False
    stream: BinaryIO | None = None
    input_stream: BinaryIO | None = None
    process: subprocess.Popen[bytes] | None = None
    try:
        if input_bytes is not None:
            input_stream = tempfile.TemporaryFile()
            input_stream.write(input_bytes)
            input_stream.flush()
            input_stream.seek(0)
        process = start_process_group(
            argv,
            cwd=cwd,
            env=env,
            stdin=input_stream if input_stream is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=stderr,
            popen_factory=popen_factory,
        )
        stream = process.stdout
        if stream is None:
            raise ProcessSafetyError(
                "process_pipe_missing", "the bounded process output pipe is missing"
            )
        started = time.monotonic()
        os.set_blocking(stream.fileno(), False)
        pipe_is_nonblocking = True
        while True:
            _eof, exceeded = _read_available(
                stream, output, output_limit=output_limit, retain_output=True
            )
            if exceeded:
                trigger = "output_limit"
                break
            returncode = process.poll()
            if returncode is not None:
                break
            if time.monotonic() - started > timeout:
                trigger = "timeout"
                break
            time.sleep(_POLL_INTERVAL_SECONDS)
    except BaseException as exc:
        active_error = exc
    finally:
        if process is not None:
            try:
                terminate_process_group(
                    process, term_timeout=term_timeout, kill_timeout=kill_timeout
                )
            except BaseException as exc:
                cleanup_error = exc

        if stream is not None:
            try:
                if pipe_is_nonblocking:
                    final_exceeded = _drain_to_eof(
                        stream,
                        output,
                        output_limit=output_limit,
                        retain_output=trigger != "output_limit",
                        timeout=drain_timeout,
                    )
                    if trigger is None and final_exceeded:
                        trigger = "output_limit"
                else:
                    pipe_error = ProcessSafetyError(
                        "process_pipe_unverifiable",
                        "the bounded process output pipe could not be made non-blocking",
                    )
            except BaseException as exc:
                pipe_error = exc
            finally:
                try:
                    stream.close()
                except BaseException as exc:
                    if pipe_error is None:
                        pipe_error = exc
        if input_stream is not None:
            try:
                input_stream.close()
            except BaseException as exc:
                if pipe_error is None:
                    pipe_error = exc

    if cleanup_error is not None:
        raise ProcessSafetyError(
            "process_group_cleanup_failed",
            "the bounded process group could not be terminated and verified",
        ) from cleanup_error
    if pipe_error is not None:
        if isinstance(pipe_error, ProcessSafetyError):
            raise pipe_error
        raise ProcessSafetyError(
            "process_pipe_cleanup_failed",
            "the bounded process output pipe could not be drained and closed",
        ) from pipe_error
    if active_error is not None:
        raise active_error
    if trigger is not None:
        raise ProcessSafetyError(trigger, f"bounded process {trigger}")
    if returncode is None:
        raise ProcessSafetyError(
            "process_parent_unverifiable",
            "the bounded process parent did not report a return code",
        )
    if process is None:
        raise ProcessSafetyError(
            "process_parent_unverifiable",
            "the bounded process parent was not created",
        )
    marker = getattr(process, _PROCESS_MARKER_ATTRIBUTE)
    if marker.encode("ascii") in output:
        raise ProcessSafetyError(
            "process_marker_exposed",
            "the bounded process exposed its internal descendant authority",
        )
    return BoundedProcessResult(returncode=returncode, output=bytes(output))
