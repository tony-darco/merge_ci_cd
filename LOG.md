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
