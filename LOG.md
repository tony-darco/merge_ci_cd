# Problem Log

Running record of things that broke during the build, written at the moment they happened — not reconstructed afterward. Format:

```
## [Mn] <short title>
- Symptom:
- What I assumed:
- What I tried:
- Root cause:
- Fix:
- Time lost:
```

## [M0] `kubectl apply` rejects the Argo CRDs — annotation too large
- Symptom: `kubectl apply -n argo -f manifests/argo-install/quick-start-minimal.yaml` created most resources fine, but errored on all four large CRDs (`workflows.argoproj.io`, `workflowtemplates.argoproj.io`, `clusterworkflowtemplates.argoproj.io`, `cronworkflows.argoproj.io`) with `metadata.annotations: Too long: may not be more than 262144 bytes`. `workflow-controller` then crash-looped since its own CRDs didn't exist.
- What I assumed: the vendored manifest (pinned to the same v4.1.1 as the installed `argo` CLI, fetched straight from the GitHub release) would apply cleanly with plain `kubectl apply`.
- What I tried: nothing else first — the fix was known on sight (Argo's auto-generated CRDs are large enough that `kubectl apply`'s client-side `last-applied-configuration` annotation blows past Kubernetes' 256KiB annotation limit; this is a known issue with big CRDs generally, not specific to this manifest).
- Root cause: `kubectl apply` (client-side) stores the entire applied manifest as a JSON annotation on the object for future 3-way diffs. Argo's CRDs carry huge OpenAPI schemas and exceed that annotation's size cap.
- Fix: re-ran with `kubectl apply --server-side -n argo -f manifests/argo-install/quick-start-minimal.yaml`, which uses server-side field management instead of the annotation and has no such size limit. All 8 CRDs installed; `workflow-controller` recovered on its own after a couple of restarts once its CRDs existed.
- Time lost: ~5 minutes.

## [M0] Sandboxed browser tool refuses the Argo UI's self-signed HTTPS cert
- Symptom: `argo-server` serves HTTPS by default with a self-signed cert. `curl -k` reaches it fine (200), but the Claude Code browser pane's `navigate`/`preview_start` both silently failed ("navigation ... denied or failed") with no way to click through a cert warning — headless/sandboxed browser automation doesn't offer the "proceed anyway" interstitial a human gets.
- What I assumed: registering the URL in `.claude/launch.json` (the documented way to preview a localhost server) would be enough regardless of TLS.
- What I tried: `preview_start` with a raw `url`; then `.claude/launch.json` pointing at the same `https://localhost:2746` — both failed identically, confirming it's the cert, not the discovery mechanism.
- Root cause: the sandboxed browser has no interactive path to accept a self-signed certificate.
- Fix: patched `argo-server` to serve plain HTTP instead — `kubectl patch deploy argo-server --type=json -p '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--secure=false"}]'`. That alone left the rollout stuck, because the readiness/liveness probes still probed `https://:2746/` and never went Ready against a now-HTTP server; had to also patch `readinessProbe.httpGet.scheme` to `HTTP`. `--secure=false` is a fine tradeoff for a local demo cluster behind a port-forward, not something to carry into any real deployment.
- Time lost: ~10 minutes.

## [M0] Can't parameterize `resources.limits.memory` with a workflow parameter
- Symptom: `argo submit ... --parameter memory-limit=256Mi` failed immediately with `Failed to parse workflow error="quantities must match the regular expression '^([+-]?[0-9.]+)([eEinumkKMGTP]*[-+]?[0-9]*)$'"`, before the workflow ever reached the cluster.
- What I assumed: `{{workflow.parameters.memory-limit}}` inside `resources.limits.memory` would get substituted like any other Argo template variable, the same way `{{workflow.parameters.image}}` worked fine in the container's `image` field.
- What I tried: nothing else — the error message plus knowing Kubernetes resource quantities are a strictly-typed field pointed straight at the cause.
- Root cause: `resources.limits.memory` is a Kubernetes `resource.Quantity` field, which the workflow CRD's schema validates against a strict regex at parse time — *before* Argo's own `{{...}}` template substitution runs. The literal string `{{workflow.parameters.memory-limit}}` doesn't match that regex, so parsing fails before the parameter is ever resolved. `image` worked because container image is a plain string field with no such format constraint.
- Fix: stopped trying to parameterize the quantity at all. Split `sample-pipeline.yaml` into two templates — `test` (default resources) and `test-oom-limited` (hardcoded `memory: 16Mi`) — and pick between them with `argo submit --entrypoint`, which only sets which template runs (a plain string) and has no such validation problem.
- Time lost: ~5 minutes.

## [M0] `argo submit --wait -o json` prints the pre-completion object, not the final status
- Symptom: `argo submit ... --wait -o json` correctly blocked until the workflow finished (confirmed via a separate plain-text `argo submit --wait` run showing `Failed at ...`), but the JSON it printed had `status: {startedAt: null, finishedAt: null}` — no `phase` key at all, so `workflow["status"]["phase"]` raised `KeyError`. Separately, `--wait` also makes the CLI exit non-zero whenever the *workflow* fails, which isn't a script error for these deliberately-broken seeds — had to stop using `check=True` for this call too.
- What I assumed: `-o json` combined with `--wait` would print the fully-resolved final workflow object, the same one `argo get -o json` returns afterward.
- What I tried: ran `argo submit --wait` without `-o json` first to confirm the workflow really was reaching a terminal `Failed` state (it was, in ~10s) before concluding the JSON output itself was the stale part, not the wait behavior.
- Root cause: `argo submit -o json`'s JSON appears to reflect the object as constructed at submission time, not re-fetched after `--wait` unblocks — a CLI quirk, not a controller/status problem.
- Fix: split into three steps instead of one: `argo submit -o name` (submit, get the bare name back immediately), `argo wait <name>` (block until terminal phase), `argo get <name> -o json` (fetch the real final object). More calls, but each does one thing and actually returns what it claims to.
- Time lost: ~10 minutes.

## [M0] `infra-failure`'s captured fixture confirms the empty-logs prediction exactly
- Not a bug — a confirmation worth recording, and the concrete payoff of capturing this fixture live instead of hand-authoring it (DECISIONS.md #22). The real `seed/infra-failure` run's captured fixture has `logs: {"sample-pipeline-zbh8m": ""}` — completely empty, exactly as predicted — and the only signal is `failed_nodes[0].message: "main: OOMKilled (exit code 137)"`. Had this fixture been hand-authored, it's easy to imagine writing a plausible-looking log line containing "OOMKilled" and never noticing that real `kubectl logs` output for this case is empty, and that Argo phrases the message as `"main: OOMKilled (exit code 137)"` specifically (not e.g. `"OOMKilled"` alone or `"container was OOM killed"`). `infra_detector.py` (M1) needs to match against `message`, and needs to not choke on an empty `logs` value.
- Time lost: none — this is exactly what capturing it live was for.

## [M1] `format: "json"` alone isn't enough -- qwen3.5's "response" comes back empty
- Symptom: `POST /api/generate` with `{"model": "qwen3.5:0.8b", "prompt": ..., "format": "json", "stream": false}` returned `"response": ""` -- completely empty -- while the model's actual (garbled, not-valid-JSON) output showed up in a separate `"thinking"` field instead.
- What I assumed: `format: "json"` alone would be enough to get clean structured output back in `response`, the same way it's documented to work for non-reasoning models.
- What I tried: compared against a plain-text prompt first to confirm the model was reachable and responding at all (it was) before suspecting the JSON-mode interaction specifically.
- Root cause: `qwen3.5` is a hybrid reasoning ("thinking") model. By default it streams its reasoning into `thinking` and only puts a final answer in `response` once it decides it's done thinking -- and under strict JSON-mode constraints it apparently sometimes never produces that final answer, leaving `response` empty.
- Fix: added `"think": false` to the request body. With thinking disabled, `response` came back as clean, directly-parseable JSON (`{"ok": true}`) on the same prompt. `providers/ollama.py` sends `think: false` on every structured-output call.
- Time lost: ~10 minutes. Directly confirms the spec's §7.7 warning about small local models and structured output -- and is a concrete data point for how the Triage fallback ladder (DECISIONS.md #16) earns its keep.

## [M2] Diagnosis's `affected_files` came back as an absolute path, silently producing a whole-file-add diff
- Symptom: a live end-to-end diagnosis+fix run against `code-defect` produced a *correct* fix (removed the erroneous `/ 100`) but a garbage diff: `@@ -0,0 +1,5 @@` -- the whole file added as new, instead of a 1-line change.
- What I assumed: `DiagnosisResult.affected_files` would always come back relative to the repo root (e.g. `src/sample_app/discounts.py`), matching what an earlier manual test run had actually produced.
- What I tried: printed `diagnosis.affected_files` directly and found `/Users/tdarco/Documents/Projects/merge_ci_cd/sample-app/src/sample_app/discounts.py` -- an absolute path this run, where a prior run on the same fixture had returned a relative one. Non-deterministic model output, not a one-off fluke to shrug off.
- Root cause: `fix.py`'s `_read_relevant_files` looked up `checkout_path / rel_path` using the path exactly as the Diagnosis LLM returned it. An absolute path doesn't match anything under `checkout_path`, so the file read silently returned nothing, `old_content` defaulted to `""`, and `difflib.unified_diff("", full_new_content)` correctly-but-uselessly described that as "add everything."
- Fix: two layers, not one. (1) Tightened the Diagnosis prompt to explicitly ask for paths "relative to the repo root, exactly as they'd appear in a git diff (e.g. `src/sample_app/discounts.py`), never absolute." (2) Added `_normalize_path()` in `fix.py` as a defensive normalizer regardless of what the prompt asks for -- searches for a `src/` or `tests/` anchor in the path string and keeps everything from there, so an absolute path (local or from a container's `/app/...` layout) still resolves correctly. Prompting alone isn't a fix per spec §7.7; the code has to tolerate the model not listening.
- Time lost: ~15 minutes.

## [M2] Lockfile exception in scope.py double-rejected instead of substituting for the allowlist
- Symptom: `test_accepts_lockfile_change_with_reason` failed -- a diff touching `requirements.txt` with a valid `lockfile_change_reason` was still rejected, with reason `"'requirements.txt' is outside the allowlisted paths (('src/', 'tests/'))"`.
- What I assumed: checking "is this a lockfile with a reason" and "is this path under src/ or tests/" as two independent, both-must-pass conditions would be fine.
- What I tried: nothing else -- the failing assertion's reason string made the actual logic error obvious immediately.
- Root cause: lockfiles like `requirements.txt` live at the repo root, not under `src/` or `tests/` -- so the allowlist check rejected it regardless of whether a valid reason was given. The two checks needed to be alternatives (lockfile-with-reason OR allowlisted path), not both required.
- Fix: restructured to check `is_lockfile` first; if true, only the reason matters (substitutes for the allowlist check entirely); otherwise fall through to the normal prefix check.
- Time lost: ~5 minutes.

## [M2] Diagnosis pointed at test files, not the source file -- Fix Agent hallucinated a whole-file rewrite it couldn't have gotten right
- Symptom: `run_fix_agent.py --seed code-defect` "succeeded" (both guards passed) but the written diff was `@@ -0,0 +1,8 @@` -- claims to *create* `src/sample_app/discounts.py` from nothing, with a hallucinated function signature (`original_price, discount_percent` instead of the real `amount, pct`). That diff cannot `git apply` cleanly against a checkout where the file already exists.
- What I assumed: `DiagnosisResult.affected_files` would name the actual source file implicated in the root cause, since that's what "affected_files" should mean.
- What I tried: printed the diagnosis output directly and found `affected_files: ['.../tests/test_pricing.py', '.../tests/test_discounts.py']` -- this run, Diagnosis named the *test* files that detected the bug, not the source file that caused it. A different, real, non-deterministic diagnosis than the one two runs earlier that correctly named `discounts.py`.
- Root cause: `fix.py`'s file retrieval only reads `diagnosis.affected_files` plus test files pattern-matched from `FAILED ...::` log lines -- neither path led to `discounts.py` this run, so the Fix LLM was never shown the file it was "fixing" and had to invent one from scratch, informed only by the test assertions. It produced plausible-looking, functionally-reasonable logic, but as a diff it's fiction -- it doesn't know it's replacing 5 real existing lines.
- Fix: don't trust `affected_files` as the only signal. Added `_infer_source_files_from_test_imports()` in `fix.py`: scans the failing test files' own `from <pkg>.<module> import ...` statements and resolves each to `src/<pkg>/<module>.py`, adding any that exist on disk to the retrieval set regardless of what Diagnosis named. Also tightened the Diagnosis prompt to ask specifically for "the source file(s) implicated in the root cause, not the test file(s) that merely detected it" -- belt (better prompt) and suspenders (retrieval no longer solely dependent on the model getting that instruction right).
- Time lost: ~20 minutes. This is the sharpest concrete argument yet for why the spec insists on sandboxed verification before any PR: a confidently-produced, guard-passing diff was still substantively wrong.
