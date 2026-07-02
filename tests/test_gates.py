from __future__ import annotations

from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.web.gates import gates_payload, read_receipts, run_gate, write_receipt


def _config() -> WikiConfig:
    return WikiConfig(repo_id="gate-test")


def test_no_receipts_reports_not_run(tmp_path: Path) -> None:
    payload = gates_payload(tmp_path, _config())
    assert payload["status"] == "not_run"
    assert all(g["status"] == "not_run" for g in payload["gates"])


def test_receipts_flip_the_status_green(tmp_path: Path) -> None:
    config = _config()
    # A gate that last passed shows green — the whole point (the old code could
    # never leave 'not_run').
    for gate_id in ("wiki_audit", "methodology_coverage", "operation_compile", "input_stage", "pytest"):
        write_receipt(tmp_path, config, gate_id, ok=True, returncode=0)
    payload = gates_payload(tmp_path, config)
    assert payload["status"] == "pass"
    assert all(g["status"] == "pass" for g in payload["gates"])
    assert all(g["finished_at"] for g in payload["gates"])


def test_any_failure_makes_overall_fail(tmp_path: Path) -> None:
    config = _config()
    write_receipt(tmp_path, config, "wiki_audit", ok=True, returncode=0)
    write_receipt(tmp_path, config, "pytest", ok=False, returncode=1)
    payload = gates_payload(tmp_path, config)
    assert payload["status"] == "fail"
    by_id = {g["id"]: g["status"] for g in payload["gates"]}
    assert by_id["wiki_audit"] == "pass"
    assert by_id["pytest"] == "fail"
    # Gates never run stay honest.
    assert by_id["operation_compile"] == "not_run"


def test_partial_when_some_pass_none_fail(tmp_path: Path) -> None:
    config = _config()
    write_receipt(tmp_path, config, "wiki_audit", ok=True, returncode=0)
    assert gates_payload(tmp_path, config)["status"] == "partial"


def test_run_gate_unknown_id_errors(tmp_path: Path) -> None:
    result = run_gate(tmp_path, _config(), "not_a_gate")
    assert result["ok"] is False
    assert "unknown gate" in result["error"]
    assert read_receipts(tmp_path, _config()) == {}


def test_run_gate_persists_receipt(tmp_path: Path) -> None:
    # `true` isn't one of our gates, but running a real gate here would need a
    # full wiki; instead assert the receipt/return contract via a passing gate
    # whose script is trivially absent → nonzero, receipt still written.
    config = _config()
    result = run_gate(tmp_path, config, "wiki_audit", timeout_seconds=30)
    assert result["gate_id"] == "wiki_audit"
    assert "returncode" in result
    # A receipt exists regardless of pass/fail — the run happened.
    assert "wiki_audit" in read_receipts(tmp_path, config)
