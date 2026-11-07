from concurrent.futures import ThreadPoolExecutor
import json
import multiprocessing
from pathlib import Path
import shutil
import subprocess
import threading
import traceback

import pytest

from wiki_core.config import WikiConfig
from wiki_core.failure_routing import (
    AdmissionDenied, FailureIntent, IssueRef, RoutingError, RunRef, UpstreamMerge,
    route_adoption as _route_adoption, route_failure as _route_failure,
)


@pytest.fixture(autouse=True)
def synthetic_repository(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("data/derived/**\ncustom/cache/**\n")


def route_failure(root, value, **kwargs):
    return _route_failure(root, value, config=WikiConfig(), **kwargs)


def route_adoption(root, value, **kwargs):
    return _route_adoption(root, value, config=WikiConfig(), **kwargs)


class Issues:
    def __init__(self):
        self.items = {}
        self.created = 0
        self.visible = True
        self.timeout_after_create = False
        self.merge = None
        self.payloads = []

    def find(self, target, marker):
        return [self.items[marker]] if self.visible and marker in self.items else []

    def get(self, target, issue):
        return next((x for x in self.items.values() if x.identifier == issue), None) if self.visible else None

    def create(self, target, template, marker):
        self.created += 1
        self.payloads.append((target, template, marker))
        self.items[marker] = IssueRef("issue-1", marker)
        if self.timeout_after_create:
            raise TimeoutError("sensitive provider output must not be persisted")

    def verified_merge(self, target, issue):
        return self.merge


class Workers:
    def __init__(self):
        self.items = {}
        self.started = []
        self.visible = True

    def find(self, executor, key):
        return [self.items[key]] if self.visible and key in self.items else []

    def start(self, executor, key, issue, revision):
        self.started.append((executor, key, issue, revision))
        self.items[key] = RunRef("run-" + str(len(self.started)), key, "queued")


def allow(capability, call):
    return call()


def intent(key="incident-1"):
    return FailureIntent(key, "synthetic-template", "public-kit", "kit-executor", "consumer-coordinator")


def test_create_dispatch_once_and_replay_with_two_concurrent_callers(tmp_path):
    issues, workers = Issues(), Workers()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow), range(2)))
    assert results == [{"issue_id": "issue-1", "state": "queued", "run_id": "run-1"}] * 2
    assert issues.created == 1
    assert len(workers.started) == 1
    assert "incident-1" not in str(issues.payloads)
    receipt = next((tmp_path / "data/derived/wiki/failure-routing").glob("*.json"))
    assert "incident-1" not in receipt.read_text()


def test_unavailable_executor_is_honest_and_later_replay_dispatches(tmp_path):
    issues, workers = Issues(), Workers()
    assert route_failure(tmp_path, intent(), issue_port=issues, executor_port=None, admit=allow) == {"issue_id": "issue-1", "state": "executor_unavailable"}
    assert route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)["state"] == "queued"
    assert issues.created == 1


def test_host_selected_existing_issue_is_read_back_and_linked(tmp_path):
    issues, workers = Issues(), Workers()
    issues.items["older-marker"] = IssueRef("issue-existing", "older-marker")
    existing = FailureIntent("incident-1", "synthetic-template", "public-kit", "kit-executor", "consumer-coordinator", "issue-existing")
    first = route_failure(tmp_path, existing, issue_port=issues, executor_port=workers, admit=allow)
    assert first == {"issue_id": "issue-existing", "state": "queued", "run_id": "run-1"}
    assert route_failure(tmp_path, existing, issue_port=issues, executor_port=workers, admit=allow) == first
    assert issues.created == 0 and len(workers.started) == 1
    issues.merge = UpstreamMerge("a" * 40, True, True, True)
    assert route_adoption(tmp_path, existing, issue_port=issues, executor_port=workers, admit=allow)["state"] == "queued"


def test_unconfirmed_existing_issue_never_creates_new_one(tmp_path):
    issues, workers = Issues(), Workers()
    existing = FailureIntent("incident-1", "synthetic-template", "public-kit", "kit-executor", "consumer-coordinator", "issue-missing")
    assert route_failure(tmp_path, existing, issue_port=issues, executor_port=workers, admit=allow)["state"] == "issue_unconfirmed"
    assert issues.created == 0 and not workers.started


def test_timeout_and_unobservable_issue_never_retry_blindly(tmp_path):
    issues, workers = Issues(), Workers()
    issues.visible = False
    issues.timeout_after_create = True
    assert route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)["state"] == "outcome_uncertain"
    assert route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)["state"] == "outcome_uncertain"
    assert issues.created == 1
    assert not workers.started
    issues.visible = True
    assert route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)["state"] == "queued"
    assert issues.created == 1


def test_crash_before_create_reconciles_without_blind_retry(tmp_path):
    class SimulatedCrash(BaseException):
        pass
    issues, workers = Issues(), Workers()
    def crash(*_args):
        raise SimulatedCrash()
    issues.create = crash
    with pytest.raises(SimulatedCrash):
        route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)
    issues.create = lambda *_args: pytest.fail("must not retry an ambiguous effect")
    assert route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)["state"] == "outcome_uncertain"
    assert not workers.started


def test_crash_after_create_is_recovered_by_readback_without_duplication(tmp_path):
    class SimulatedCrash(BaseException):
        pass
    issues, workers = Issues(), Workers()
    create = issues.create
    def crash_after(*args):
        create(*args)
        raise SimulatedCrash()
    issues.create = crash_after
    with pytest.raises(SimulatedCrash):
        route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)
    issues.create = lambda *_args: pytest.fail("must link observed issue")
    assert route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)["state"] == "queued"
    assert issues.created == 1 and len(workers.started) == 1


def test_provider_exception_is_not_exposed_in_traceback(tmp_path):
    issues = Issues()
    def fail(*_args):
        raise RuntimeError("private provider response")
    issues.find = fail
    with pytest.raises(RoutingError) as error:
        route_failure(tmp_path, intent(), issue_port=issues, executor_port=None, admit=allow)
    assert "private provider response" not in "".join(traceback.format_exception(error.value))


def test_admission_refusal_does_not_create_effect_and_can_be_retried(tmp_path):
    issues, workers = Issues(), Workers()
    def denied(capability, call):
        if capability == "issue.create":
            raise AdmissionDenied()
        return call()
    assert route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=denied)["state"] == "admission_denied"
    assert issues.created == 0 and not workers.started
    assert route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)["state"] == "queued"


def test_executor_admission_can_be_revoked_after_issue_creation(tmp_path):
    issues, workers = Issues(), Workers()
    def denied(capability, call):
        if capability == "executor.start":
            raise AdmissionDenied()
        return call()
    assert route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=denied) == {"issue_id": "issue-1", "state": "admission_denied"}
    assert issues.created == 1 and not workers.started
    assert route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)["state"] == "queued"
    assert issues.created == 1 and len(workers.started) == 1


def test_same_key_different_intent_is_refused(tmp_path):
    issues = Issues()
    route_failure(tmp_path, intent(), issue_port=issues, executor_port=None, admit=allow)
    altered = FailureIntent("incident-1", "other-template", "public-kit", "kit-executor", "consumer-coordinator")
    with pytest.raises(RoutingError, match="receipt_conflict"):
        route_failure(tmp_path, altered, issue_port=issues, executor_port=None, admit=allow)
    assert issues.created == 1


def test_repair_and_adoption_are_distinct_and_require_verified_merge(tmp_path):
    issues, workers = Issues(), Workers()
    assert route_adoption(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)["state"] == "issue_unconfirmed"
    route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)
    assert route_adoption(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)["state"] == "upstream_not_merged"
    revision = "a" * 40
    issues.merge = UpstreamMerge(revision, True, False, True)
    assert route_adoption(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)["state"] == "upstream_not_ready"
    assert len(workers.started) == 1
    issues.merge = UpstreamMerge(revision, True, True, True)
    handoff = route_adoption(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)
    assert handoff == {"issue_id": "issue-1", "upstream_revision": revision, "state": "queued", "run_id": "run-2"}
    assert workers.started[1][0] == "consumer-coordinator" and workers.started[1][3] == revision
    assert route_adoption(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow) == handoff
    issues.merge = UpstreamMerge("b" * 40, True, True, True)
    with pytest.raises(RoutingError, match="revision_conflict"):
        route_adoption(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)
    assert len(workers.started) == 2


def test_closed_issue_blocks_repair_but_allows_verified_merge_handoff(tmp_path):
    issues, workers = Issues(), Workers()
    assert route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)["state"] == "queued"
    marker = next(iter(issues.items))
    issues.items[marker] = IssueRef("issue-1", marker, "closed")
    assert route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow) == {"issue_id": "issue-1", "state": "issue_closed"}
    assert len(workers.started) == 1
    assert route_adoption(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)["state"] == "upstream_not_merged"
    issues.merge = UpstreamMerge("a" * 40, True, True, True)
    assert route_adoption(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)["state"] == "queued"
    assert workers.started[1][0] == "consumer-coordinator"


def test_existing_closed_issue_never_starts_repair(tmp_path):
    issues, workers = Issues(), Workers()
    issues.items["older-marker"] = IssueRef("issue-existing", "older-marker", "closed")
    existing = FailureIntent("incident-1", "synthetic-template", "public-kit", "kit-executor", "consumer-coordinator", "issue-existing")
    assert route_failure(tmp_path, existing, issue_port=issues, executor_port=workers, admit=allow) == {"issue_id": "issue-existing", "state": "issue_closed"}
    assert not workers.started and issues.created == 0
    issues.merge = UpstreamMerge("a" * 40, True, True, True)
    assert route_adoption(tmp_path, existing, issue_port=issues, executor_port=workers, admit=allow)["state"] == "queued"
    assert workers.started[0][0] == "consumer-coordinator"


def test_conflicting_provider_readback_does_not_create_or_dispatch(tmp_path):
    issues, workers = Issues(), Workers()
    issues.find = lambda target, marker: [IssueRef("one", marker), IssueRef("two", marker)]
    with pytest.raises(RoutingError, match="provider_conflict"):
        route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)
    assert issues.created == 0 and not workers.started


def test_symlink_receipt_directory_fails_closed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    parent = tmp_path / "data/derived/wiki"
    parent.mkdir(parents=True)
    (parent / "failure-routing").symlink_to(outside, target_is_directory=True)
    with pytest.raises(RoutingError, match="receipt_path_invalid"):
        route_failure(tmp_path, intent(), issue_port=Issues(), executor_port=None, admit=allow)
    assert list(outside.iterdir()) == []


def test_receipts_follow_consumer_derived_path_and_reject_escape(tmp_path):
    paths = dict(WikiConfig().paths)
    paths["derived_root"] = "custom/cache"
    config = WikiConfig(paths=paths)
    result = _route_failure(tmp_path, intent(), config=config, issue_port=Issues(), executor_port=None, admit=allow)
    assert result["state"] == "executor_unavailable"
    assert len(list((tmp_path / "custom/cache/failure-routing").glob("*.json"))) == 1
    paths["derived_root"] = "../outside"
    with pytest.raises(RoutingError, match="receipt_path_invalid"):
        _route_failure(tmp_path, intent("escape"), config=WikiConfig(paths=paths), issue_port=Issues(), executor_port=None, admit=allow)


def test_nonignored_storage_fails_before_provider_effects(tmp_path):
    paths = dict(WikiConfig().paths)
    paths["derived_root"] = "public"
    issues, workers = Issues(), Workers()
    with pytest.raises(RoutingError, match="receipt_not_private"):
        _route_failure(tmp_path, intent(), config=WikiConfig(paths=paths), issue_port=issues, executor_port=workers, admit=allow)
    assert not (tmp_path / "public").exists()
    assert issues.created == 0 and not workers.started


def test_ignore_revoked_during_admission_prevents_provider_effect(tmp_path):
    issues, workers = Issues(), Workers()
    def revoke_ignore(capability, call):
        if capability == "issue.create":
            (tmp_path / ".gitignore").write_text("")
        return call()
    result = route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=revoke_ignore)
    assert result["state"] == "outcome_uncertain"
    assert issues.created == 0 and not workers.started


def test_missing_git_repository_fails_before_provider_effects(tmp_path):
    shutil.rmtree(tmp_path / ".git")
    issues, workers = Issues(), Workers()
    with pytest.raises(RoutingError, match="repository_unavailable"):
        route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)
    assert issues.created == 0 and not workers.started


def test_force_tracked_receipt_fails_before_provider_effects(tmp_path):
    issues, workers = Issues(), Workers()
    assert route_failure(tmp_path, intent(), issue_port=issues, executor_port=None, admit=allow)["state"] == "executor_unavailable"
    receipt = next((tmp_path / "data/derived/wiki/failure-routing").glob("*.json"))
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", str(receipt)], check=True)
    with pytest.raises(RoutingError, match="receipt_not_private"):
        route_failure(tmp_path, intent(), issue_port=issues, executor_port=workers, admit=allow)
    assert issues.created == 1 and not workers.started


def test_independent_incident_continues_after_another_has_uncertain_issue(tmp_path):
    stuck, healthy = Issues(), Issues()
    stuck.visible = False
    stuck.timeout_after_create = True
    workers = Workers()
    assert route_failure(tmp_path, intent("stuck"), issue_port=stuck, executor_port=workers, admit=allow)["state"] == "outcome_uncertain"
    assert route_failure(tmp_path, intent("healthy"), issue_port=healthy, executor_port=workers, admit=allow)["state"] == "queued"


def test_slow_incident_does_not_block_an_unrelated_front(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class SlowIssues(Issues):
        def create(self, target, template, marker):
            entered.set()
            assert release.wait(timeout=5)
            super().create(target, template, marker)
    slow, healthy, workers = SlowIssues(), Issues(), Workers()
    with ThreadPoolExecutor(max_workers=2) as pool:
        waiting = pool.submit(route_failure, tmp_path, intent("slow"), issue_port=slow, executor_port=workers, admit=allow)
        try:
            assert entered.wait(timeout=5)
            independent = pool.submit(route_failure, tmp_path, intent("healthy"), issue_port=healthy, executor_port=workers, admit=allow)
            assert independent.result(timeout=2)["state"] == "queued"
        finally:
            release.set()
        assert waiting.result(timeout=5)["state"] == "queued"


class FileIssues:
    def __init__(self, root):
        self.root = Path(root)

    def find(self, target, marker):
        file = self.root / "provider-issue.json"
        if not file.exists():
            return []
        data = json.loads(file.read_text())
        return [IssueRef(data["id"], data["marker"])]

    def create(self, target, template, marker):
        with (self.root / "issue-effects.txt").open("a") as stream:
            stream.write("create\n")
        (self.root / "provider-issue.json").write_text(json.dumps({"id": "issue-1", "marker": marker}))


class FileWorkers:
    def __init__(self, root):
        self.root = Path(root)

    def find(self, executor, key):
        file = self.root / "provider-worker.json"
        if not file.exists():
            return []
        data = json.loads(file.read_text())
        return [RunRef(data["id"], data["key"], "queued")]

    def start(self, executor, key, issue, revision):
        with (self.root / "worker-effects.txt").open("a") as stream:
            stream.write("start\n")
        (self.root / "provider-worker.json").write_text(json.dumps({"id": "run-1", "key": key}))


def _multiprocess_route(root, queue):
    try:
        queue.put(route_failure(Path(root), intent(), issue_port=FileIssues(root), executor_port=FileWorkers(root), admit=allow))
    except Exception as exc:
        queue.put(type(exc).__name__)


def test_same_host_separate_processes_share_reservation(tmp_path):
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [context.Process(target=_multiprocess_route, args=(str(tmp_path), queue)) for _ in range(2)]
    for process in processes:
        process.start()
    results = [queue.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0
    assert results == [{"issue_id": "issue-1", "state": "queued", "run_id": "run-1"}] * 2
    assert (tmp_path / "issue-effects.txt").read_text().splitlines() == ["create"]
    assert (tmp_path / "worker-effects.txt").read_text().splitlines() == ["start"]
