"""Memory scope + visibility convention drift-test.

Eidetic-cli publishes a "memory scope + visibility convention v1"
(eidetic-cli docs/contract.md, issue #28) that every consumer of the eidetic
memory store — including colleague's colleague/memory.py runtime integration —
must pin with a drift test.

This test verifies colleague's consumer-side of that contract:
1. colleague/memory.py shells out to eidetic with exactly
   --scope colleague --visibility public (public-by-default, scope named by
   culture.yaml suffix)
2. The scope name "colleague" equals this repo's culture.yaml agent suffix
3. A mismatch here means either colleague/memory.py or the eidetic convention
   changed — fix whichever side diverged and bump the contract version, don't
   silence the test.

Citation: eidetic-cli docs/contract.md v1, issue agentculture/eidetic-cli#28.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml


def test_memory_scope_is_colleague() -> None:
    """recall() and remember() shell out with --scope colleague."""
    memory_module_path = Path(__file__).parent.parent / "colleague" / "memory.py"
    source = memory_module_path.read_text()

    # Assert recall() builds argv with --scope colleague --visibility public
    assert (
        '"--scope"' in source and '"colleague"' in source
    ), "recall() must carry --scope colleague"
    assert (
        '"--visibility"' in source and '"public"' in source
    ), "recall() must carry --visibility public"

    # Assert remember() builds argv with --scope colleague --visibility public
    # (grep is just a basic sanity check; the full contract is that both
    # functions use the same scope/visibility)
    recall_pattern = (
        r'argv\s*=\s*\[\s*"eidetic",\s*"recall".*?'
        r'"--scope",\s*"colleague".*?"--visibility",\s*"public"'
    )
    remember_pattern = (
        r'argv\s*=\s*\[\s*"eidetic",\s*"remember".*?'
        r'"--scope",\s*"colleague".*?"--visibility",\s*"public"'
    )

    assert re.search(recall_pattern, source, re.DOTALL), (
        "recall() argv must contain --scope colleague " "--visibility public in that order"
    )
    assert re.search(remember_pattern, source, re.DOTALL), (
        "remember() argv must contain --scope colleague " "--visibility public in that order"
    )


def test_memory_scope_matches_culture_yaml_suffix() -> None:
    """The scope 'colleague' matches this repo's culture.yaml agent suffix.

    Per eidetic-cli contract v1, scope naming is
    "culture.yaml-suffix-per-repo", meaning the scope name must equal this
    repo's culture.yaml top-level agent suffix (the canonical identity the
    CLI reports via `eidetic whoami`).
    """
    repo_root = Path(__file__).parent.parent
    culture_yaml_path = repo_root / "culture.yaml"

    assert culture_yaml_path.exists(), (
        f"culture.yaml must exist at {culture_yaml_path} "
        "(colleague/memory.py hardcodes scope name 'colleague', "
        "which must match the agent suffix)"
    )

    with open(culture_yaml_path) as f:
        culture = yaml.safe_load(f)

    # Extract the first agent's suffix (canonical per eidetic contract)
    agents = culture.get("agents", [])
    assert agents, "culture.yaml must define at least one agent"
    first_agent = agents[0]
    suffix = first_agent.get("suffix")

    assert suffix == "colleague", (
        f"culture.yaml first agent suffix must be 'colleague' "
        f"(colleague/memory.py hardcodes scope='colleague'); got '{suffix}'"
    )
