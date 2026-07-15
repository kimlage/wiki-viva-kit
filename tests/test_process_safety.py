from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

import wiki_core.process_safety as process_safety


def _wait_for_pid_exit(pid: int) -> None:
    for _attempt in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    pytest.fail(f"descendant {pid} survived bounded process-group teardown")


def _python_program(program: str, *arguments: str) -> list[str]:
    return [sys.executable, "-c", program, *arguments]


def test_normal_parent_exit_terminates_unreferenced_descendant(
    tmp_path: Path,
) -> None:
    pid_path = tmp_path / "child.pid"
    program = (
        "import os,subprocess,sys;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,"
        "start_new_session=False);"
        "open(sys.argv[1],'w',encoding='ascii').write(str(child.pid));"
        "print('safe-output',flush=True)"
    )

    result = process_safety.run_bounded_process(
        _python_program(program, str(pid_path)),
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        timeout=5,
        output_limit=1024,
    )

    assert result.returncode == 0
    assert result.output == b"safe-output\n"
    _wait_for_pid_exit(int(pid_path.read_text(encoding="ascii")))


def test_normal_parent_exit_does_not_wait_on_descendant_held_stdout(
    tmp_path: Path,
) -> None:
    pid_path = tmp_path / "child.pid"
    program = (
        "import os,subprocess,sys;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "stdin=subprocess.DEVNULL,stdout=sys.stdout,stderr=sys.stderr,"
        "start_new_session=False);"
        "open(sys.argv[1],'w',encoding='ascii').write(str(child.pid));"
        "print('bounded-output',flush=True)"
    )
    started = time.monotonic()

    result = process_safety.run_bounded_process(
        _python_program(program, str(pid_path)),
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        timeout=5,
        output_limit=1024,
    )

    assert time.monotonic() - started < 3
    assert result.returncode == 0
    assert result.output == b"bounded-output\n"
    _wait_for_pid_exit(int(pid_path.read_text(encoding="ascii")))


def test_descendant_that_starts_a_new_session_is_still_terminated(
    tmp_path: Path,
) -> None:
    pid_path = tmp_path / "escaped.pid"
    program = (
        "import subprocess,sys;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,"
        "start_new_session=True);"
        "open(sys.argv[1],'w',encoding='ascii').write(str(child.pid));"
        "print('parent-complete',flush=True)"
    )

    result = process_safety.run_bounded_process(
        _python_program(program, str(pid_path)),
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        timeout=5,
        output_limit=1024,
    )

    assert result.returncode == 0
    assert result.output == b"parent-complete\n"
    _wait_for_pid_exit(int(pid_path.read_text(encoding="ascii")))


def test_sigterm_resistant_descendant_is_killed_within_second_bound(
    tmp_path: Path,
) -> None:
    pid_path = tmp_path / "resistant.pid"
    ready_path = tmp_path / "resistant.ready"
    child = (
        "import os,signal,sys,time;"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "open(sys.argv[1],'w',encoding='ascii').write(str(os.getpid()));"
        "open(sys.argv[2],'w',encoding='ascii').write('ready');"
        "time.sleep(60)"
    )
    parent = (
        "import pathlib,subprocess,sys,time\n"
        "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2],sys.argv[3]],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,"
        "start_new_session=True)\n"
        "deadline=time.monotonic()+3\n"
        "ready=pathlib.Path(sys.argv[3])\n"
        "while not ready.exists() and time.monotonic()<deadline:\n"
        "    time.sleep(.01)\n"
        "print('parent-complete',flush=True)\n"
    )
    # Use a small TERM grace only in this synthetic test; production retains
    # the five-second TERM and five-second KILL verification bounds.
    result = process_safety.run_bounded_process(
        _python_program(parent, child, str(pid_path), str(ready_path)),
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        timeout=5,
        output_limit=1024,
        term_timeout=0.1,
        kill_timeout=1,
    )

    assert ready_path.exists()
    assert result.returncode == 0
    assert result.output == b"parent-complete\n"
    _wait_for_pid_exit(int(pid_path.read_text(encoding="ascii")))


def test_base_exception_still_terminates_group_and_closes_pipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_path = tmp_path / "parent.pid"
    real_read = process_safety._read_available
    raised = False

    def interrupt_once(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal raised
        if pid_path.exists() and not raised:
            raised = True
            raise KeyboardInterrupt("synthetic interruption")
        return real_read(*args, **kwargs)

    monkeypatch.setattr(process_safety, "_read_available", interrupt_once)
    program = (
        "import os,sys,time;"
        "open(sys.argv[1],'w',encoding='ascii').write(str(os.getpid()));"
        "time.sleep(60)"
    )

    with pytest.raises(KeyboardInterrupt, match="synthetic interruption"):
        process_safety.run_bounded_process(
            _python_program(program, str(pid_path)),
            cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin"},
            timeout=5,
            output_limit=1024,
        )

    _wait_for_pid_exit(int(pid_path.read_text(encoding="ascii")))


def test_bounded_file_backed_input_is_delivered_exactly(tmp_path: Path) -> None:
    payload = b"public-synthetic-input\n" * 32_768
    program = (
        "import hashlib,sys;"
        "sys.stdout.write(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())"
    )

    result = process_safety.run_bounded_process(
        _python_program(program),
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        timeout=5,
        output_limit=1024,
        input_bytes=payload,
    )

    assert result.returncode == 0
    assert result.output == hashlib.sha256(payload).hexdigest().encode("ascii")


def test_fast_oversized_output_fails_with_bounded_reason(tmp_path: Path) -> None:
    with pytest.raises(process_safety.ProcessSafetyError) as caught:
        process_safety.run_bounded_process(
            _python_program("print('x' * 4096)"),
            cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin"},
            timeout=5,
            output_limit=64,
        )

    assert caught.value.reason == "output_limit"


def test_nested_bound_preserves_outer_descendant_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outer = "a" * 64
    inner = "b" * 64
    environments: list[dict[str, str]] = []
    real_popen = subprocess.Popen

    def recording_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        environments.append(dict(kwargs["env"]))
        return real_popen(*args, **kwargs)

    monkeypatch.setenv(process_safety._PROCESS_MARKER_KEY, outer)
    monkeypatch.setattr(process_safety.secrets, "token_hex", lambda _size: inner)
    process = process_safety.start_process_group(
        _python_program("pass"),
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        popen_factory=recording_popen,
    )
    process_safety.terminate_process_group(process)

    assert environments[0][process_safety._PROCESS_MARKER_KEY] == f"{outer}:{inner}"
