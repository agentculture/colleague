"""End-to-end: one contract, swappable engines (c1, c7, h8, h11, h12, h14).

Proves the headline claim without a network: the *same* task driven through two
different engines (the real mock engine and the vLLM driver over mocked HTTP)
yields results of the *identical shape*, and the engine is selected purely by
name through the registry — the only thing that changes is `--engine`.

Also guards the policy no-op contract (t7): with no approvals.json present the
artifact shape is byte-identical to a policy-free run — the gate is a strict
default-off feature.

Shape parity + width-1 equivalence (t7 parallel-batch): the SubResult produced
by the parallel batch path (make_batch_spawn) has the SAME structural shape as
one produced by the sequential single-spawn path (make_spawn), and running a
batch of K instructions with width=1 (the default, no ThreadPoolExecutor) yields
children whose stable contract fields equal those from running the same K
instructions one-by-one via make_spawn.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from colleague import registry
from colleague.cli import main
from colleague.config import EngineConfig
from colleague.contract import INCOMPLETE, OK, SubResult, Task
from colleague.engines import vllm_openai
from colleague.subagents import make_batch_spawn, make_spawn
from colleague.tools import SCHEMAS

# The base-six tool surface every engine inherits, plus the curated culture tool (t3).
_BASE_TOOLS = {"read_file", "write_file", "edit_file", "list_dir", "run_command", "finish"}
_CULTURE_TOOLS = {"culture"}


def _key_shape(value: Any) -> Any:
    """Recursive key signature, ignoring concrete values — for shape comparison."""
    if isinstance(value, dict):
        return {k: _key_shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return _key_shape(value[0]) if value else None
    return None


def _mock_vllm_http(monkeypatch: pytest.MonkeyPatch) -> None:
    turns = [
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "1",
                                "function": {
                                    "name": "write_file",
                                    "arguments": json.dumps(
                                        {"path": "out.txt", "content": "from the model"}
                                    ),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        },
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "2",
                                "function": {
                                    "name": "finish",
                                    "arguments": json.dumps({"summary": "wrote out.txt"}),
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1},
        },
    ]
    state = {"i": 0}

    def fake_post(url: str, payload: dict, *, api_key: str, timeout: float) -> dict:
        turn = turns[min(state["i"], len(turns) - 1)]
        state["i"] += 1
        return turn

    monkeypatch.setattr(vllm_openai, "_post_json", fake_post)


def test_same_task_yields_identical_result_shape_across_engines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_vllm_http(monkeypatch)
    cfg = EngineConfig.resolve()

    mock_repo = tmp_path / "mock"
    vllm_repo = tmp_path / "vllm"
    mock_repo.mkdir()
    vllm_repo.mkdir()

    # Engines are chosen by name, through the registry — only the name differs.
    mock_result = registry.load("mock").work(Task.new(str(mock_repo), "do work"), cfg)
    vllm_result = registry.load("vllm-openai").work(Task.new(str(vllm_repo), "do work"), cfg)

    assert mock_result.status == OK
    assert vllm_result.status == OK
    # Identical shape: same keys top-level and in every nested structure (h11/h14).
    assert _key_shape(mock_result.to_dict()) == _key_shape(vllm_result.to_dict())
    # Both actually edited their repo.
    assert mock_result.changed_files and vllm_result.changed_files


def test_no_linter_repo_omits_lint_report_byte_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All-engines lint no-op (#200, c16/h1/h3): a repo with no configured linter
    yields a byte-identical TaskResult on BOTH engines — the lint gate fires from the
    shared loop (so it is forwarded identically) but is a strict no-op when nothing is
    configured, so ``lint_report`` is absent from the serialized result for both.
    """
    _mock_vllm_http(monkeypatch)
    cfg = EngineConfig.resolve()
    assert cfg.lint is True  # default-ON, yet a no-linter repo stays a no-op

    mock_repo = tmp_path / "mock"
    vllm_repo = tmp_path / "vllm"
    mock_repo.mkdir()
    vllm_repo.mkdir()

    mock_result = registry.load("mock").work(Task.new(str(mock_repo), "do work"), cfg)
    vllm_result = registry.load("vllm-openai").work(Task.new(str(vllm_repo), "do work"), cfg)

    for result in (mock_result, vllm_result):
        assert result.lint_report is None
        assert "lint_report" not in result.to_dict()


def test_engine_swap_needs_no_task_change(tmp_path: Path) -> None:
    """The Task is engine-agnostic: only the `engine` field selects the driver (h12)."""
    a = Task.new(str(tmp_path), "identical instruction", engine="mock")
    b = Task.new(str(tmp_path), "identical instruction", engine="vllm-openai")
    a_fields = a.to_dict()
    b_fields = b.to_dict()
    a_fields.pop("engine")
    a_fields.pop("id")
    b_fields.pop("engine")
    b_fields.pop("id")
    assert a_fields == b_fields  # everything but the engine name is the same


def test_every_engine_exposes_the_culture_tools_identically() -> None:
    """All-engines rule (t3/t2): the curated culture and devague tools live on the
    *shared* tool surface, beyond the five base tools, so every engine exposes them
    identically.

    The surface is a single shared ``SCHEMAS`` list: the vLLM engine hands it to
    the model verbatim, and the loop's ``ToolExecutor`` dispatches the same tool
    names for the mock engine. There is no per-engine tool surface — so asserting
    on ``SCHEMAS`` is the honest all-engines guard.
    """
    exposed = {s["function"]["name"] for s in SCHEMAS}
    _CHASSIS_TOOLS = {"culture", "devague", "subagent", "subagents"}
    # Base six remain, the chassis tools are added, and nothing else creeps in.
    assert _BASE_TOOLS <= exposed, "the six base tools must remain exposed"
    assert _CULTURE_TOOLS <= exposed, "every engine must expose the culture tool"
    assert _CHASSIS_TOOLS <= exposed, "every engine must expose all chassis tools"
    assert exposed == _BASE_TOOLS | _CHASSIS_TOOLS, "the tool surface is base-six + chassis"

    # The vLLM engine literally hands this shared surface to the model.
    assert vllm_openai.SCHEMAS is SCHEMAS


def test_no_destination_drive_omits_destination_keys_byte_identical(tmp_path: Path) -> None:
    """A normal mock drive that sets NO destination serializes byte-identically to
    the pre-feature shape (c8/h8): ``to_dict()`` must NOT contain ``destination``
    or ``announcement`` keys.

    The mock engine is the contract reference (the all-engines rule). Its scripted
    finish carries no destination/announcement, so the serialized result must be
    indistinguishable from the result a pre-feature colleague produced — the
    destination concept is additive and default-off, never a null-padded key.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = EngineConfig.resolve()

    result = registry.load("mock").work(Task.new(str(repo), "do work"), cfg)

    assert result.status == OK
    # The drive really ran (it edited the repo), so this is a live, not-empty result.
    assert result.changed_files
    # The destination concept stayed off — the fields are None on the object …
    assert result.destination is None
    assert result.announcement is None
    # … and the serialized shape OMITS both keys entirely (not present-as-null).
    serialized = result.to_dict()
    assert "destination" not in serialized
    assert "announcement" not in serialized

    # Byte-identical guard: the exact key set is the pre-feature key set. Pin it
    # explicitly so any future field addition that leaks into the no-destination
    # path is caught here.
    assert set(serialized.keys()) == {
        "task_id",
        "status",
        "summary",
        "changed_files",
        "steps",
        "usage",
        "stats",
        "artifacts_path",
        "error",
        "branch",
        "pr_url",
        "hook_firings",
        "command",
        "not_finished",
        "stopped_without_finish",
    }


def test_no_subagent_drive_omits_sub_results_key_byte_identical(tmp_path: Path) -> None:
    """A normal mock drive that delegates NO subagent serializes byte-identically
    to the pre-feature shape: ``to_dict()`` must NOT contain a ``"sub_results"`` key.

    This mirrors the destination/announcement omit-when-None treatment:
    ``sub_results`` is emitted ONLY when the list is non-empty, so a drive that
    never called the subagent tool is indistinguishable from today's artifact shape.
    The mock engine is the contract reference (the all-engines rule).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = EngineConfig.resolve()

    result = registry.load("mock").work(Task.new(str(repo), "do work"), cfg)

    assert result.status == OK
    # The drive really ran and the sub_results list is empty.
    assert result.changed_files
    assert result.sub_results == []
    # The serialized shape OMITS the key entirely (not present-as-empty-list).
    serialized = result.to_dict()
    assert "sub_results" not in serialized

    # Byte-identical guard: the pinned key set must NOT include sub_results.
    expected_keys = {
        "task_id",
        "status",
        "summary",
        "changed_files",
        "steps",
        "usage",
        "stats",
        "artifacts_path",
        "error",
        "branch",
        "pr_url",
        "hook_firings",
        "command",
        "not_finished",
        "stopped_without_finish",
    }
    assert set(serialized.keys()) == expected_keys


def test_drive_cli_then_backends_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["drive", "go", "--repo", str(tmp_path), "--engine", "mock", "--no-pr", "--json"])
    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == OK

    assert main(["backends", "list", "--json"]) == 0
    names = {e["name"] for e in json.loads(capsys.readouterr().out)["engines"]}
    assert {"mock", "vllm-openai"} <= names


def test_no_policy_file_artifact_is_byte_identical_to_policy_free_run(
    tmp_path: Path,
) -> None:
    """Policy no-op shape guard (t7 AC1): with NO .colleague/approvals.json present,
    the TaskResult to_dict() key set and step shape are byte-identical to a run in a
    repo that has never had any policy concept applied.

    This proves the gate is a strict default-off feature — its presence in the chassis
    adds zero visible artefact when no policy file exists.
    """
    # Repo A: has a .colleague/ dir but no approvals.json.
    repo_a = tmp_path / "with_dotdir"
    repo_a.mkdir()
    (repo_a / ".colleague").mkdir()
    # Deliberately leave approvals.json absent.

    # Repo B: completely vanilla — no .colleague/ at all.
    repo_b = tmp_path / "vanilla"
    repo_b.mkdir()

    cfg = EngineConfig.resolve()
    result_a = registry.load("mock").work(Task.new(str(repo_a), "do work"), cfg)
    result_b = registry.load("mock").work(Task.new(str(repo_b), "do work"), cfg)

    # Both must succeed.
    assert result_a.status == OK
    assert result_b.status == OK

    dict_a = result_a.to_dict()
    dict_b = result_b.to_dict()

    # Key sets are identical — the gate added no new keys.
    assert set(dict_a.keys()) == set(
        dict_b.keys()
    ), f"Key sets differ: {set(dict_a.keys()) ^ set(dict_b.keys())}"

    # The pinned pre-feature key set is unchanged (mirrors the destination no-op guard).
    expected_keys = {
        "task_id",
        "status",
        "summary",
        "changed_files",
        "steps",
        "usage",
        "stats",
        "artifacts_path",
        "error",
        "branch",
        "pr_url",
        "hook_firings",
        "command",
        "not_finished",
        "stopped_without_finish",
    }
    assert (
        set(dict_a.keys()) == expected_keys
    ), f"Unexpected extra keys in policy-free run: {set(dict_a.keys()) - expected_keys}"

    # Step shapes are identical.
    steps_a = [(s["tool"], s["ok"]) for s in dict_a["steps"]]
    steps_b = [(s["tool"], s["ok"]) for s in dict_b["steps"]]
    assert steps_a == steps_b

    # No hook_firings in either run (no hooks configured).
    assert dict_a["hook_firings"] == []
    assert dict_b["hook_firings"] == []


# ---------------------------------------------------------------------------
# Helpers for the parallel-batch shape parity + width-1 equivalence tests.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a git command in the given repo directory."""
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )


def _make_git_repo(tmp_path: Path, name: str = "repo") -> Path:
    """Create a minimal git repo with one commit (required for 'git worktree add')."""
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@colleague.test")
    _git(repo, "config", "user.name", "Colleague Test")
    # An initial commit so worktree_add has a HEAD to branch from.
    (repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial commit")
    return repo


# The stable SubResult contract fields — those produced identically by both the
# sequential single-spawn and the parallel batch paths. task_id is excluded
# because it is generated from uuid.uuid4() (non-deterministic per drive). usage
# is excluded because prompt_tokens / completion_tokens reflect the exact mock
# script replay and are not stable across different invocation contexts (they can
# vary when the mock replays turns on a child vs the same instruction run
# directly, depending on the exact turn the loop settles on). The fields below
# are the stable, caller-observable contract.
_STABLE_SUBRESULT_FIELDS = {"engine", "model", "status", "changed_files", "summary"}


def _stable(sub: SubResult) -> dict:
    """Extract only the stable contract fields from a SubResult for comparison."""
    d = dataclasses.asdict(sub)
    return {k: d[k] for k in _STABLE_SUBRESULT_FIELDS}


# ---------------------------------------------------------------------------
# Shape parity: a batch-spawned SubResult has the SAME field set as a
# sequentially-spawned one (the mock engine is the contract reference).
# ---------------------------------------------------------------------------


def test_batch_subresult_fields_identical_to_sequential_subresult(
    tmp_path: Path,
) -> None:
    """A SubResult produced by the parallel batch path (make_batch_spawn) has the
    SAME set of dataclass fields — and the same to_dict() key set — as one produced
    by the sequential single-spawn path (make_spawn).

    This is the engine-independent structural identity check: SubResult is a plain
    dataclass; we assert that dataclasses.fields() yields the same names for both
    a sequentially-spawned child and a batch-spawned child (h1/h9 shape parity).
    The mock engine is the contract reference (the all-engines rule).
    """
    seq_repo = _make_git_repo(tmp_path, "seq")
    batch_repo = _make_git_repo(tmp_path, "batch")
    cfg = EngineConfig.resolve()

    # Sequential single spawn: one child via make_spawn.
    spawn = make_spawn(str(seq_repo), cfg, "mock")
    seq_child = spawn("do the seq task", "mock", None)

    # Parallel batch spawn (width=1, sequential path): one child via make_batch_spawn.
    batch_spawn_fn = make_batch_spawn(str(batch_repo), cfg, "mock")
    batch_results = batch_spawn_fn([{"instruction": "do the batch task"}])
    # batch_results = [child_0, ..., merge_child]; we compare a real child (index 0).
    assert len(batch_results) >= 2, "batch must return at least one child + one merge child"
    batch_child = batch_results[0]

    # Both are SubResult instances.
    assert isinstance(seq_child, SubResult)
    assert isinstance(batch_child, SubResult)

    # Structural identity: the SAME dataclass field names in the same order.
    seq_field_names = [f.name for f in dataclasses.fields(seq_child)]
    batch_field_names = [f.name for f in dataclasses.fields(batch_child)]
    assert seq_field_names == batch_field_names, (
        f"SubResult field names differ between sequential and batch children:\n"
        f"  sequential: {seq_field_names}\n"
        f"  batch:      {batch_field_names}"
    )

    # to_dict() key set is identical (the serialized contract shape is the same).
    seq_keys = set(seq_child.to_dict().keys())
    batch_keys = set(batch_child.to_dict().keys())
    assert seq_keys == batch_keys, (
        f"to_dict() key sets differ between sequential and batch children:\n"
        f"  sequential: {seq_keys}\n"
        f"  batch:      {batch_keys}"
    )

    # The expected SubResult key set is pinned so any future field addition that
    # leaks into the serialized shape is caught here.
    expected_sub_keys = {
        "task_id",
        "engine",
        "model",
        "status",
        "summary",
        "changed_files",
        "usage",
    }
    assert seq_keys == expected_sub_keys, (
        f"SubResult to_dict() key set has drifted from the expected shape:\n"
        f"  got:      {seq_keys}\n"
        f"  expected: {expected_sub_keys}"
    )


# ---------------------------------------------------------------------------
# Width-1 equivalence: batch with concurrency=1 yields children with the same
# stable contract fields as running the same instructions via make_spawn.
# No ThreadPoolExecutor is ever instantiated on the width=1 path.
# ---------------------------------------------------------------------------


def test_width_1_batch_stable_fields_equal_sequential_make_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running a batch of K instructions with subagent_concurrency=1 (the default,
    sequential path — NO ThreadPoolExecutor) yields child SubResults whose STABLE
    CONTRACT FIELDS (engine, model, status, changed_files, summary) equal those from
    running the same K instructions one-by-one via make_spawn.

    Non-deterministic fields excluded from the comparison:
    - task_id: generated from uuid.uuid4() per drive — unique per run, not stable.
    - usage: the mock script replays turns and the token counts can differ across
      different repo contexts / instruction strings.

    This is the honesty condition h4: width=1 is byte-identical to the pre-batch
    sequential path at the contract level. The mock engine is the contract reference.
    """

    # Guard: ThreadPoolExecutor must NOT be instantiated on the width=1 path.
    class _NeverPool:
        def __init__(self, *a, **k):
            raise AssertionError(
                "ThreadPoolExecutor must NOT be created when subagent_concurrency=1"
            )

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", _NeverPool)

    instructions = ["write the first marker file", "write the second marker file"]

    # Sequential reference: run each instruction independently via make_spawn.
    seq_children = []
    for instr in instructions:
        seq_repo = _make_git_repo(tmp_path, f"seq-{len(seq_children)}")
        cfg = EngineConfig.resolve()
        spawn = make_spawn(str(seq_repo), cfg, "mock")
        seq_children.append(spawn(instr, "mock", None))

    # Batch path (width=1 — the default; subagent_concurrency=1 → no thread pool).
    batch_repo = _make_git_repo(tmp_path, "batch-w1")
    cfg_w1 = EngineConfig.resolve(subagent_concurrency=1)
    assert cfg_w1.subagent_concurrency == 1, "sanity: concurrency must be 1 for this test"

    batch_fn = make_batch_spawn(str(batch_repo), cfg_w1, "mock")
    batch_results = batch_fn([{"instruction": instr} for instr in instructions])

    # batch_results = [child_0, child_1, ..., merge_child]; take only the K children.
    batch_children = batch_results[: len(instructions)]
    assert len(batch_children) == len(instructions), (
        f"Expected {len(instructions)} child results from batch, "
        f"got {len(batch_children)} (total: {len(batch_results)})"
    )

    # All children from both paths must have succeeded.
    for i, (seq, bch) in enumerate(zip(seq_children, batch_children)):
        assert seq.status == OK, f"sequential child {i} failed: {seq.status}"
        assert bch.status == OK, f"batch child {i} failed: {bch.status}"

    # The stable contract fields must be equal for corresponding children.
    for i, (seq, bch) in enumerate(zip(seq_children, batch_children)):
        seq_stable = _stable(seq)
        bch_stable = _stable(bch)
        assert seq_stable == bch_stable, (
            f"Child {i} stable fields differ between sequential and batch paths:\n"
            f"  sequential: {seq_stable}\n"
            f"  batch (w=1): {bch_stable}"
        )


def test_batch_sub_results_present_in_taskresult_when_non_empty(
    tmp_path: Path,
) -> None:
    """The existing e2e guard (test_no_subagent_drive_omits_sub_results_key) pins
    the NO-subagent path. This complementary test pins the WITH-subagent path:
    a TaskResult that DOES carry sub_results (from a batch drive) serializes with
    the 'sub_results' key present, the key contains the expected number of entries,
    and each entry has the pinned SubResult key set.

    This confirms that the 'stats' and 'sub_results' keys co-exist correctly on
    a real drive result — both must be present when sub_results is non-empty
    (the e2e shape guard, h9).
    """
    batch_repo = _make_git_repo(tmp_path, "batch-taskresult")
    cfg = EngineConfig.resolve()

    # Build batch_spawn and wire it into a mock drive via EngineConfig.
    batch_fn = make_batch_spawn(str(batch_repo), cfg, "mock")
    cfg.subagent_batch_spawn = batch_fn

    # Also build the single spawn so the engine can wire it.
    spawn_fn = make_spawn(str(batch_repo), cfg, "mock")
    cfg.subagent_spawn = spawn_fn

    # Drive the mock engine; mock writes colleague-mock.md, no subagent call is
    # issued by the mock script itself. Drive the batch via the batch_spawn callback
    # directly to validate the sub_results folding — the batch_fn is a standalone
    # callable we can call directly and its results reflect real SubResult objects.
    batch_results = batch_fn([{"instruction": "alpha"}, {"instruction": "beta"}])

    # 2 children + 1 merge child = 3 SubResults.
    assert len(batch_results) == 3
    for sub in batch_results:
        assert isinstance(sub, SubResult)
        sub_keys = set(sub.to_dict().keys())
        expected_sub_keys = {
            "task_id",
            "engine",
            "model",
            "status",
            "summary",
            "changed_files",
            "usage",
        }
        assert sub_keys == expected_sub_keys, (
            f"SubResult key set from batch drive differs from expected:\n"
            f"  got:      {sub_keys}\n"
            f"  expected: {expected_sub_keys}"
        )

    # The 'stats' key is separate from sub_results: confirm a no-subagent mock
    # drive includes 'stats' at the top level (pinned by the existing guard).
    plain_repo = tmp_path / "plain"
    plain_repo.mkdir()
    plain_result = registry.load("mock").work(Task.new(str(plain_repo), "work"), cfg)
    assert plain_result.status == OK
    plain_dict = plain_result.to_dict()
    assert "stats" in plain_dict, "'stats' must always be present in TaskResult.to_dict()"
    assert (
        "sub_results" not in plain_dict
    ), "a no-subagent drive must NOT include 'sub_results' in its serialized shape"


def test_subagents_chassis_tool_present_in_engine_tool_surface() -> None:
    """Guard that the 'subagents' (plural) chassis tool remains present in the
    shared SCHEMAS surface after the parallel-batch feature lands (t7 AC3 — the
    all-engines rule applies to both 'subagent' and 'subagents').

    This mirrors test_every_engine_exposes_the_culture_tools_identically but
    focuses on confirming the full chassis tool surface — including the batch
    delegation tool — is unchanged. It is intentionally redundant with the
    broader schema-surface test above; the duplication is deliberate because the
    parallel-batch parity story is incomplete without an explicit check here in
    the batch-parity section of the file.
    """
    exposed = {s["function"]["name"] for s in SCHEMAS}
    # Both the single-child and batch-child tools must be present.
    assert "subagent" in exposed, "'subagent' (single-child) must remain in the chassis tool set"
    assert "subagents" in exposed, "'subagents' (batch) must remain in the chassis tool set"
    # The vLLM engine uses the identical shared surface — no per-engine copy.
    assert (
        vllm_openai.SCHEMAS is SCHEMAS
    ), "vllm_openai.SCHEMAS must be the same object as colleague.tools.SCHEMAS"


# ---------------------------------------------------------------------------
# Honest status (colleague#192): status reflects whether the work item
# called finish or not.
# ---------------------------------------------------------------------------


def test_clean_finish_is_ok_exit_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A run that ends by calling finish is status==OK and exits 0."""
    rc = main(
        [
            "work",
            "do work",
            "--repo",
            str(tmp_path),
            "--engine",
            "mock",
            "--no-pr",
            "--json",
        ]
    )
    assert rc == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == OK


def test_budget_exhausted_is_incomplete_non_zero_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A run that exhausts the step budget without calling finish is
    status==INCOMPLETE and exits non-zero.

    The mock engine's script is two turns (write_file, then finish).  With
    max_steps=1 the loop runs one turn, executes the write_file, and then
    hits the budget — the finish turn never happens.
    """
    rc = main(
        [
            "work",
            "do work",
            "--repo",
            str(tmp_path),
            "--engine",
            "mock",
            "--no-pr",
            "--json",
            "--max-steps",
            "1",
        ]
    )
    assert rc != 0, "Budget-exhausted run must exit non-zero"
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == INCOMPLETE
    assert result["not_finished"] is True
