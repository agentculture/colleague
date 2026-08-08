# t2 verification record — webglass 0.6.0 usable-bar (webglass-cli#9)

Date: 2026-08-07 (UTC) · webglass-cli 0.6.0 (`f1e555b`) · host: spark dev box
Fixtures: `keys.html` (keydown → console + `#agent-state` JSON), `throws.html`
(throws on load), `clean.html`, `throws-on-key.html` (probe beyond the bar) —
served by `python3 -m http.server 8571 --bind 127.0.0.1`.
Policy profile: `{"name": "t2-fixture", "declared_targets": ["127.0.0.1:8571"]}`.

## Sandbox posture (recorded honestly)

Host has `kernel.apparmor_restrict_unprivileged_userns=1`; sandboxed Chromium
launch aborts with webglass's structured refusal (never a silent
`--no-sandbox`). Run under `WEBGLASS_ALLOW_UNSANDBOXED=1` — the sanctioned
trusted-harness opt-in; every session record renders the sandbox-disabled
marker in plain sight. Page content = our own fixtures + the game under test,
localhost only. Hardening path (operator, needs sudo): an AppArmor profile for
the Playwright Chromium binaries mirroring `/etc/apparmor.d/chrome`, or
webglass's CI-recipe sysctl.

## The seven items (plan t2 acceptance) — ALL PASS

| # | Item | Evidence |
|---|------|----------|
| 1 | localhost open under policy | No profile → `policy_denied`, rule `target-deny-loopback`, exit 1 (structured, not silent). With profile → `lifecycle_state: succeeded`, status 200. |
| 2 | console/page-error evidence | `throws.html` → `page_errors: [{text: "Error: fixture-boom…", source_url, line: 5}]` + console log captured. `clean.html` → explicitly empty `console_messages: []` and `page_errors: []`. |
| 3 | selector-scoped extract | `--selector '#agent-state'` returns exactly the one element's content (`{"keys":[]}`) in `--json`. |
| 4 | action press | `press ArrowRight ArrowRight Space e --delay-ms 50` → result carries `key_log`; page state shows `{"keys":["ArrowRight","ArrowRight"," ","e"]}` (correct KeyboardEvent.key semantics — Space arrives as `" "`). |
| 5 | screenshot to file | `--out shot.png` → PNG image data 780x493, decodable. |
| 6 | session reattach across one-shot calls | create → open (inv 2) → press (inv 3) → extract (inv 4) → inspect (inv 5) → screenshot (inv 6) → close (inv 7); state set in inv 3 visible in inv 4. |
| 7 | agent-first contract | `--json` on every verb; results→stdout, diagnostics→stderr; exit 1 on policy denial, 2 on launch failure, 0 on success. |

## Boundary found beyond the bar (reported on webglass-cli#9)

Post-navigation console/page-error capture is navigation-window-scoped: a
runtime error thrown by a keydown handler (`throws-on-key.html`, press `x`)
is invisible — the press result carries only `key_log`, and a later
live-session `inspect --lens console` returns empty lists. Architectural
consequence of one-shot CLI + live CDP (events between invocations fire while
nobody is attached). Load-time and early-frame errors ARE captured (fresh
`inspect --url` restarts the page), so the NEBULA dead-on-load false-positive
stays closed.

**Mitigation (adopted, pre-arm):** the game template's state contract carries
`state.lastError` (null when healthy) wired to
`window.onerror`/`onunhandledrejection` — action-triggered failures become
observable via item-3 extraction. Template commit `15eb0b9`;
`docs/correction-rules.md` untouched (frozen at `0438ec4`).

Also observed: the sandbox-disabled marker renders on session records but not
on page-operation results from ephemeral sessions (honesty nit, reported).

## Verdict

t2 acceptance met in full; game arms UNHELD. Colleague-side consumption stays
`run_command` through the approval gate — zero colleague code diff.
