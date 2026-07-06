"""Organs check-group + ``colleague organs`` noun (colleague#291 R10 / #297 S10).

Acceptance (from the S10 spec):

1. Bare ``colleague doctor`` with organs configured (lobes armed, an
   ``.eidetic/`` store present) makes ZERO network calls — the existing
   oilcheck no-network guard extends to the organs group.
2. A missing organ is a ``warning`` with a ``uv tool install <dist>``
   remediation hint — NEVER an unhealthy report.
3. ``organs list --json`` agrees with the doctor group: one resolver
   (:func:`colleague.oilcheck.organs.resolve_organs`), two views.
4. The reachability probe is probe-only: never registered, empty when lobes
   is unarmed.
"""

from __future__ import annotations

import json
import socket

import pytest

import colleague.oilcheck as oilcheck
from colleague.cli import main
from colleague.oilcheck import diagnose, organs

_CHECK_KEYS = {"id", "passed", "severity", "message", "remediation"}

_ORGAN_NAMES = [
    "lobes",
    "eidetic",
    "coherence",
    "sloth",
    "data-refinery",
    "agtag",
    "devex",
    "devague",
]


def _no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args, **_kwargs):
        raise AssertionError("organs group opened a socket")

    monkeypatch.setattr(socket, "socket", _boom)


# --- the curated table -----------------------------------------------------


def test_curated_table_names_every_organ() -> None:
    assert [o.name for o in organs.ORGANS] == _ORGAN_NAMES


def test_resolver_entry_shape(tmp_path) -> None:
    entries = organs.resolve_organs(str(tmp_path))
    assert [e["organ"] for e in entries] == _ORGAN_NAMES
    for entry in entries:
        assert set(entry) == {
            "organ",
            "seam",
            "contract",
            "present",
            "version",
            "armed",
            "distribution",
        }
        assert isinstance(entry["present"], bool)
        assert isinstance(entry["armed"], bool)
        assert isinstance(entry["version"], str) and entry["version"]


# --- no-network guard (the oilcheck invariant, extended to organs) ---------


def test_organs_group_opens_no_socket_even_with_organs_configured(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arm everything armable: lobes via env, memory via an .eidetic/ store.
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")
    (tmp_path / ".eidetic").mkdir()
    _no_socket(monkeypatch)
    checks = organs.checks(repo_path=str(tmp_path))  # must not raise
    assert checks
    for check in checks:
        assert set(check) == _CHECK_KEYS


def test_bare_diagnose_with_organs_configured_opens_no_socket(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The whole registered pipeline (organs included) stays no-network.
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")
    (tmp_path / ".eidetic").mkdir()
    monkeypatch.chdir(tmp_path)
    _no_socket(monkeypatch)
    report = diagnose(repo_path=str(tmp_path))
    assert set(report) == {"healthy", "checks"}
    assert any(c["id"].startswith("organ_") for c in report["checks"])


# --- missing organ: warning + remediation, never unhealthy ------------------


def test_missing_organ_is_warning_with_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(organs.shutil, "which", lambda _name: None)
    checks = organs.checks()
    assert len(checks) == len(organs.ORGANS)
    by_id = {c["id"]: c for c in checks}
    for organ in organs.ORGANS:
        check = by_id["organ_" + organ.name.replace("-", "_")]
        assert check["passed"] is False
        assert check["severity"] == "warning"
        assert f"uv tool install {organ.distribution}" in check["remediation"]


def test_all_organs_missing_never_flips_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(organs.shutil, "which", lambda _name: None)
    monkeypatch.setattr(oilcheck, "CHECK_GROUPS", [organs.checks])
    monkeypatch.setattr(oilcheck, "_REPO_AWARE_GROUPS", frozenset({organs.checks}))
    report = diagnose()
    assert report["healthy"] is True
    assert all(c["severity"] == "warning" for c in report["checks"])


def test_present_organ_is_passing_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(organs.shutil, "which", lambda _name: "/usr/bin/" + _name)
    checks = organs.checks()
    for check in checks:
        assert check["passed"] is True
        assert check["severity"] == "info"
        assert "version" in check["message"]


def test_group_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("resolver exploded")

    monkeypatch.setattr(organs, "resolve_organs", _boom)
    checks = organs.checks()  # contract: never raise
    assert len(checks) == 1
    assert checks[0]["id"] == "organs_probe_error"
    assert checks[0]["severity"] == "warning"


def test_armed_check_error_degrades_to_unarmed(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_repo):
        raise RuntimeError("armed check exploded")

    broken = organs.Organ(
        name="broken",
        binary="definitely-not-on-path-xyz",
        distribution="broken-cli",
        seam="test",
        contract="test",
        armed_check=_boom,
    )
    entry = organs.resolve_organ(broken)
    assert entry["armed"] is False
    assert entry["present"] is False


# --- version resolution ------------------------------------------------------


def test_version_unknown_when_binary_absent() -> None:
    entry = organs.resolve_organ(
        organs.Organ(
            name="ghost",
            binary="definitely-not-on-path-xyz",
            distribution="ghost-cli",
            seam="test",
            contract="test",
            armed_check=organs._not_yet_wired,
        )
    )
    assert entry["present"] is False
    assert entry["version"] == "unknown"


def test_version_unknown_when_distribution_not_importable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Present on PATH but not an importable distribution (the isolated
    # `uv tool install` case) — honest "unknown", never a crash.
    monkeypatch.setattr(organs.shutil, "which", lambda _name: "/usr/bin/x")
    entry = organs.resolve_organ(
        organs.Organ(
            name="isolated",
            binary="x",
            distribution="definitely-not-an-installed-dist",
            seam="test",
            contract="test",
            armed_check=organs._not_yet_wired,
        )
    )
    assert entry["present"] is True
    assert entry["version"] == "unknown"


def test_version_read_from_importlib_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(organs.shutil, "which", lambda _name: "/usr/bin/x")
    monkeypatch.setattr(organs, "_pkg_version", lambda _dist: "1.2.3")
    entry = organs.resolve_organ(organs.ORGANS[0])
    assert entry["version"] == "1.2.3"


# --- armed-state resolution --------------------------------------------------


def test_lobes_armed_from_env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    monkeypatch.delenv("CONVERTIBLE_LOBES_URL", raising=False)
    entries = {e["organ"]: e for e in organs.resolve_organs(str(tmp_path))}
    assert entries["lobes"]["armed"] is False
    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")
    entries = {e["organ"]: e for e in organs.resolve_organs(str(tmp_path))}
    assert entries["lobes"]["armed"] is True


def test_eidetic_armed_requires_store(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COLLEAGUE_MEMORY", raising=False)
    entries = {e["organ"]: e for e in organs.resolve_organs(str(tmp_path))}
    assert entries["eidetic"]["armed"] is False  # no .eidetic/ store
    (tmp_path / ".eidetic").mkdir()
    entries = {e["organ"]: e for e in organs.resolve_organs(str(tmp_path))}
    assert entries["eidetic"]["armed"] is True  # memory default-ON + store


def test_eidetic_armed_respects_memory_opt_out(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".eidetic").mkdir()
    monkeypatch.setenv("COLLEAGUE_MEMORY", "0")
    entries = {e["organ"]: e for e in organs.resolve_organs(str(tmp_path))}
    assert entries["eidetic"]["armed"] is False


def test_planned_organs_report_unarmed(tmp_path) -> None:
    entries = {e["organ"]: e for e in organs.resolve_organs(str(tmp_path))}
    for name in ("coherence", "sloth", "data-refinery"):
        assert entries[name]["armed"] is False
    for name in ("agtag", "devex", "devague"):
        assert entries[name]["armed"] is True  # unconditional curated tools


# --- probe-only reachability -------------------------------------------------


def test_probe_checks_not_registered() -> None:
    assert organs.probe_checks not in oilcheck.CHECK_GROUPS


def test_probe_checks_empty_when_lobes_unarmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COLLEAGUE_LOBES_URL", raising=False)
    monkeypatch.delenv("CONVERTIBLE_LOBES_URL", raising=False)
    assert organs.probe_checks() == []


def test_probe_unreachable_gateway_is_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    from colleague import lobes as lobes_mod

    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")
    monkeypatch.setattr(lobes_mod, "resolve_roles", lambda _url: None)
    checks = organs.probe_checks()
    assert len(checks) == 1
    assert checks[0]["id"] == "organ_lobes_reachable"
    assert checks[0]["passed"] is False
    assert checks[0]["severity"] == "warning"


def test_probe_reachable_gateway_reports_roles_and_embedder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from colleague import lobes as lobes_mod
    from colleague.lobes import LobesRoles, RoleInfo

    def _role(model: str) -> RoleInfo:
        return RoleInfo(
            model=model,
            endpoint="http://lobes.example:8000",
            path="/v1/chat/completions",
            context=65536,
            ready=True,
            responsibilities=(),
            forbidden_responsibilities=(),
        )

    monkeypatch.setenv("COLLEAGUE_LOBES_URL", "http://lobes.example:8001")
    monkeypatch.setattr(
        lobes_mod,
        "resolve_roles",
        lambda _url: LobesRoles(cortex=_role("qwen"), senses=_role("gemma")),
    )
    monkeypatch.setattr(
        organs, "_embedder_endpoint", lambda _gw: "http://lobes.example:8000/v1/embeddings"
    )
    checks = organs.probe_checks()
    ids = [c["id"] for c in checks]
    assert ids == ["organ_lobes_reachable", "organ_lobes_embedder_endpoint"]
    assert all(c["passed"] for c in checks)
    assert "qwen" in checks[0]["message"] and "gemma" in checks[0]["message"]


# --- one resolver, two views: the CLI noun agrees with the doctor group -----


def test_organs_list_json_agrees_with_doctor_group(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["organs", "list", "--repo", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    cli_entries = payload["organs"]

    doctor_checks = organs.checks(repo_path=str(tmp_path))

    assert [e["organ"] for e in cli_entries] == _ORGAN_NAMES
    assert len(doctor_checks) == len(cli_entries)
    for entry, check in zip(cli_entries, doctor_checks):
        expected_id = "organ_" + entry["organ"].replace("-", "_")
        assert check["id"] == expected_id
        # present <-> passed: the two views derive from the SAME resolver.
        assert check["passed"] is entry["present"]
        if not entry["present"]:
            assert f"uv tool install {entry['distribution']}" in check["remediation"]


def test_organs_list_text(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["organs", "list", "--repo", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    for name in _ORGAN_NAMES:
        assert name in out
    assert "seam:" in out and "contract:" in out


def test_organs_overview(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["organs", "overview"])
    assert rc == 0
    assert "organ" in capsys.readouterr().out.lower()


def test_explain_organs(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "organs"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "organ" in out.lower()
    assert "docs/organs.md" in out


def test_doctor_json_carries_organ_checks(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    rc = main(["doctor", "--json", "--repo", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)
    organ_ids = {c["id"] for c in payload["checks"] if c["id"].startswith("organ_")}
    assert organ_ids == {"organ_" + n.replace("-", "_") for n in _ORGAN_NAMES}
    # A missing organ never flips doctor unhealthy: any organ failure is a warning.
    for check in payload["checks"]:
        if check["id"].startswith("organ_") and not check["passed"]:
            assert check["severity"] == "warning"
    assert rc in (0, 1)  # health decided by the OTHER groups, never by organs
