# Build Plan — Colleague turns a model into a repo worker by tailoring the model-facing runtime surface — tool names, availability, descriptions, default limits, and a short prompt overlay — to that model's mind, while the operator's Task to TaskResult contract stays stable. One runtime, tailored minds. A per-model 'profile.json' (repo-local, overriding a shipped package default) declares the tailoring.

slug: `colleague-turns-a-model-into-a-repo-worker-by-tail` · status: `exported` · from frame: `colleague-turns-a-model-into-a-repo-worker-by-tail`

> Colleague turns a model into a repo worker by tailoring the model-facing runtime surface — tool names, availability, descriptions, default limits, and a short prompt overlay — to that model's mind, while the operator's Task to TaskResult contract stays stable. One runtime, tailored minds. A per-model 'profile.json' (repo-local, overriding a shipped package default) declares the tailoring.

## Tasks

### t1 — Add colleague/profile.py: the model-profile manifest schema + loader, with package-default resolution and one worked example.

- covers: c10, h1, c15, h6
- acceptance:
  - load_profile(repo, model) round-trips a profile.json (save -> load -> identical surface); unknown keys ignored; an absent or malformed file returns an empty Profile with no exception raised.
  - A bundled package-default profile under colleague/profiles/ applies when no repo-local profile exists; a repo-local .colleague/<model>/profile.json overrides it field-by-field.
  - Resolution uses sanitize_model exact paths so model X never loads model Y's profile; stdlib json only (zero-deps guard still passes).

### t2 — Add tool-surface tailoring in colleague/tools.py: build the model-facing SCHEMAS from a profile (aliases, description overrides, availability) and return the alias->canonical map.

- depends on: t1
- covers: c11, c12, h3
- acceptance:
  - tailor_schemas(profile) renames an aliased tool (write_file->edit) in the model-facing schema and returns the mapping {edit: write_file}.
  - A description override replaces the canonical tool description in the model-facing schema only.
  - Disabling an OPTIONAL tool removes it; disabling finish or any base-five tool is ignored with a warning and the tool remains in the schema.

### t3 — Layer profile default limits into EngineConfig limit resolution: precedence explicit-arg > env > profile > built-in.

- depends on: t1
- covers: c13, h4
- acceptance:
  - A COLLEAGUE_MAX_STEPS env var overrides a profile max_steps; a profile max_steps overrides the built-in default of 40; an explicit arg overrides all.
  - Applies to max_steps, context_budget_tokens, and max_output_chars identically.

### t4 — Append the profile system_prompt overlay as the terminal layer of system_prompt_for (after AGENTS.colleague.<model>.md).

- depends on: t1
- covers: c14, h5
- acceptance:
  - With both AGENTS.colleague.<model>.md and a profile system_prompt present, the composed prompt contains both in the documented order (AGENTS layers first, profile overlay last).
  - An absent profile system_prompt leaves the composed prompt byte-identical to today.

### t5 — Wire the profile through the drive loop (colleague/loop.py + engines): load once via config.model, pass tailored schemas to the model, and translate an aliased call name to canonical before dispatch AND before recording.

- depends on: t1, t2, t3
- covers: c17, h2, c20, h16
- acceptance:
  - A mock drive with a profile aliasing write_file->edit: the model emits 'edit', the write_file handler runs, and the artifact step-trace + DriveStats per-tool counts record 'write_file' (canonical).
  - Profile loading + tailoring is runtime-owned (loop/engine base) so no backend module re-implements it (boundary test).

### t6 — Add the 'colleague profile' introspection noun (overview, show --model <m> [--repo PATH] [--json], explain catalog entry), rendering the composed model-facing surface.

- depends on: t1, t2, t4
- covers: c16, h7, c3, h12, c21, h17
- acceptance:
  - colleague profile show --model <m> --json emits the composed surface: effective tool names with aliases, disabled tools, limits, and which AGENTS/skills/hooks/policy/profile layers are present.
  - A model with no profile reports a clean default state (not an error); overview and an 'explain profile' catalog entry exist.
  - show reflects the composed result of a repo-local profile over a shipped package default (end-to-end).

### t7 — Reframe README + CLAUDE.md to 'one runtime, model-tailored work surfaces / tailored minds', document the model-profile layer and its honest limits, and add docs/features/model-profiles.md.

- depends on: t1, t5, t6
- covers: c18, h9, c4, h13, c5, c22, h18
- acceptance:
  - README and CLAUDE.md describe model-tailored runtime surfaces and the model-profile layer, including before->after and why; the doc-test-alignment check passes.
  - Docs explicitly list tool parameter-name aliasing and structured retry as out-of-scope follow-ups, and never claim a --no-hooks flag, an MCP surface, or a router.

### t8 — Integration + guard tests: strict no-op byte-identity, all-engines parity, and contract stability across profiles.

- depends on: t5, t6
- covers: c19, h15, c1, h10, c2, h11, h14, h8
- acceptance:
  - A test asserts the no-profile path yields the pre-feature SCHEMAS list, system prompt, and limits; test_e2e_mock.py and test_zero_deps.py pass unchanged.
  - The same task+profile yields an identical tailored tool schema and limits under --engine mock and --engine vllm-openai (e2e shape test).
  - Switching profiles changes the model-facing surface but the Task/TaskResult artifact shape stays byte-identical across models (contract-stability test).

## Risks

- [follow_up] Tool parameter-name aliasing (renaming tool argument keys per model) deferred — most fragile to model schema tolerance.
- [follow_up] Structured (non-prose) refusal/retry/repair mechanism deferred to a follow-up.
- [out_of_scope] Automatic task->model->profile routing policy is out of scope (re-spec territory).
- [follow_up] Curate package-default profiles for additional model families beyond the single v1 worked example.
- [unknown_nonblocking] Profile load site: load once in the drive path (repo_path + model both known) and flow to BOTH limits (config) and tools (loop) without double-loading. (task t5)
