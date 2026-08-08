# #387 arm-run protocol (pre-committed before arm 1 task 1)

## Env contract (identical both arms; only COLLEAGUE_MEMORY and the arm path differ)

```text
COLLEAGUE_MODEL=unsloth/Qwen3.6-35B-A3B-NVFP4          # the worker, pinned (t1 recipe)
COLLEAGUE_DEEPTHINK_MODEL=unsloth/Qwen3.6-27B-NVFP4    # distill author pinned to SERVED
COLLEAGUE_DEEPTHINK_BASE_URL=http://localhost:8001/v1  # cortex (row-31 round-4 recipe;
COLLEAGUE_DEEPTHINK_API_KEY=$COLLEAGUE_API_KEY         # muse lingers ready=false)
EIDETIC_DATA_DIR=<arm>/.eidetic/memory                 # t6 finding: no $HOME merge/migration
WEBGLASS_ALLOW_UNSANDBOXED=1                           # host AppArmor userns (t2 record)
WEBGLASS_POLICY_PROFILE=<arm>/.colleague/webglass-profile.json
COLLEAGUE_TIMEOUT=300
# OFF arm only:
COLLEAGUE_MEMORY=0
```

Dispatch always from the colleague checkout (`cd ~/git/colleague && uv run colleague …`)
— the stale-installed-CLI trap invalidated three exp-1 attempts.

## Per-task sequence (g1..g8, strictly serial, ON arm complete before OFF)

1. Rig-quiet check (no other colleague loops; record).
2. Dispatch: `uv run colleague work "<gN brief: instruction + acceptance verbatim>"
   --repo <arm> --engine vllm-openai --pr`
3. Read artifact: task_id, pr_url, tip_sha; WorkStats.model MUST name the 35B
   (a #346 zero-step collapse invalidates the run per h20 — rerun, never average).
4. Integrator verification: serve the game from the PR branch, drive webglass
   (fresh `inspect --url` console lens + selector `#game-state` + task-specific
   presses/screenshot); evidence saved per task.
5. Rule-bound corrections (docs/correction-rules.md @ 0438ec4, SHA re-verified
   at experiment end): correct ONLY to the task's pre-committed acceptance
   criteria; commit corrections onto the PR branch; squash-merge the PR.
6. Immediate grade: `uv run colleague feedback record last --rating N --repo <arm>`
   under the SAME arm env (EIDETIC_DATA_DIR!) — fires grade-time capture.
   Verify sidecar outcome=fired (a skip removes that task from BOTH arms' metric).
7. Record: correction-diff lines (from capture sidecar, verbatim), grade,
   artifact path, PR URL, merge SHA. Pull master; next task.

## Grading rubric (fixed across arms)

5 = acceptance met, zero correction lines; 4 = cosmetic corrections (<10 lines);
3 = functional corrections required to meet acceptance; 2 = major integrator
rework (acceptance substantially unmet); 1 = unusable/collapse (invalidated).
Rating reflects the WORKER's delivery vs the task's pre-committed acceptance
only — never arm identity.

## Metric

Primary: correction-diff lines per task (capture sidecar, verbatim), mean ON vs
OFF. Secondary: steps/tokens per task from WorkStats (verbatim). Duration
reported, never load-bearing. Equal-or-worse ON = FALSIFYING, recorded unspun.
