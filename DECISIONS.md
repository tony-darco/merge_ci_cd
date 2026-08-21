# Architecture Decision Record

ADR-style entries for every non-obvious choice made while building the Agentic CI/CD Fixer, written at the moment of the decision, not reconstructed afterward. See the project spec and `/Users/tdarco/.claude/plans/agentic-ci-cd-fixer-transient-breeze.md` for full context.

---

### 1. Argo Workflows over Jenkins

**Decision:** Build on Argo Workflows.
**Context:** Need a pipeline engine that can trigger post-failure logic without deep platform surgery.
**Alternatives considered:** Jenkins (mature, but plugin-based extension is messier and less declarative; no native Kubernetes-native sandboxing story).
**Consequences:** Kubernetes-native, extensible via exit handlers and lifecycle hooks with no forking required. Ties the whole project to a Kubernetes cluster being available.
**Confidence:** High.

### 2. Track A: extend, don't fork

**Decision:** Build the agentic layer as an exit-handler container invoked by Argo, not as a fork of Argo's Go codebase.
**Context:** Argo Workflows is a Go Kubernetes controller. Modifying internals means learning Go, the controller pattern, and CRD reconciliation before writing a single agent.
**Alternatives considered:** Track B (fork Argo, add a UI panel rendering the reasoning trace inline) — rejected as a day-one approach, kept as a stretch goal only if everything else lands early.
**Consequences:** Zero Go code. All customization lives in YAML manifests, exit hooks, and agent containers. Makes it easy to reuse elsewhere; makes deep UI integration (trace rendered inline in the Argo UI) unreachable without the fork.
**Confidence:** High.

### 3. k3d over kind

**Decision:** Local Kubernetes cluster via k3d.
**Context:** Need a local cluster on a Mac with Docker already installed; neither k3d nor kind was present.
**Alternatives considered:** kind — closer to "vanilla" upstream Kubernetes behavior, but heavier and slower to boot, and needs a separate local registry setup for image loading.
**Consequences:** Lighter, faster iteration. `k3d image import` avoids standing up a local registry — used repeatedly in M0's fixture-capture loop.
**Confidence:** High.

### 4. Python throughout

**Decision:** Orchestrator (LangGraph), sample app, and the Fix Agent's edit target all in Python.
**Context:** Spec explicitly leaves the target stack open ("pick one, make it excellent").
**Alternatives considered:** Node for the sample app (more realistic for non-Python product teams, but adds a second language to reason about for no benefit to this build).
**Consequences:** One toolchain end to end. LangGraph is Python-native, so this also avoids a cross-language orchestration boundary.
**Confidence:** High.

### 5. Signal-derived confidence over self-reported LLM confidence

**Decision:** Agents never emit a confidence field. Confidence is computed downstream from observable signals (verification pass/fail, diff size, retry count, etc.).
**Context:** Self-reported LLM confidence is poorly calibrated and undermines trust the first time a 95% turns out wrong.
**Alternatives considered:** Ask the model directly for a confidence score — rejected outright per spec.
**Consequences:** Confidence scoring (M4) is a pure function over already-produced results, easy to test and audit. No agent schema anywhere carries a confidence field.
**Confidence:** High.

### 6. Human-in-the-loop over auto-merge

**Decision:** Every PR requires human approval regardless of computed confidence score. The system never merges; it proposes.
**Context:** Core non-negotiable from the spec's goals.
**Alternatives considered:** Auto-merge above a high-confidence threshold — explicitly out of scope.
**Consequences:** M6's PR creation always opens for review (ready-for-review or draft, never merged). Removes an entire class of blast-radius risk from a wrong fix.
**Confidence:** High.

### 7. Provider-agnostic LLM interface over vendor lock-in

**Decision:** Every agent calls through a single internal `agent/llm/interface.py`; no agent talks to a vendor SDK directly.
**Context:** Spec requires pluggable backends (Ollama, Anthropic, OpenAI) selectable per stage/agent.
**Alternatives considered:** Call the Ollama HTTP API directly from each agent — rejected, would hardcode the provider into agent logic and block future provider swaps.
**Consequences:** Ollama is the only implementation built now, but adding Anthropic/OpenAI later means writing a new `providers/*.py`, not touching any agent.
**Confidence:** High.

### 8. Ollama as the dev/test backend

**Decision:** All development and testing against a local Ollama host (`http://192.168.1.17:11434`).
**Context:** Free, local, matches the spec's stated baseline model family (`qwen3.5`), and doubles as the self-hosted/air-gapped story the spec highlights as a differentiator.
**Alternatives considered:** A hosted API (Anthropic/OpenAI) for dev — rejected, adds cost and network dependency to the inner dev loop with no benefit given the provider abstraction already exists.
**Consequences:** Structured-output reliability has to be handled defensively (§7.7) since local models are less consistent at clean JSON than frontier hosted models.
**Confidence:** High.

### 9. Repo root is the project root

**Decision:** `git init` directly in `merge_ci_cd`; no nested `agentic-cicd-fixer/` directory.
**Context:** The spec's suggested repo layout uses `agentic-cicd-fixer/` as an example name, but the actual checkout is already named `merge_ci_cd`.
**Alternatives considered:** Nest a nested nested directory to match the spec literally — rejected, adds a redundant path level for no benefit.
**Consequences:** Every path in the plan and this repo is one level shorter than the spec's literal example.
**Confidence:** High.

### 10. `sample-app/` is a separate, independently-versioned git repo

**Decision:** The "victim" codebase (`sample-app/`) has its own `.git`, its own commit history and branches, and is gitignored by the outer repo — not a subfolder, not a submodule.
**Context:** Seed branches (`seed/code-defect`, `seed/infra-failure`, `seed/flaky-test`, `seed/config-secret`) need to be branches of *just the victim app*.
**Alternatives considered:** `sample-app/` as a subfolder of the same repo as the agent code — rejected: every seed branch would fork the entire monorepo's state, including whatever `agent/` code existed at branch-creation time, so a later bugfix to e.g. `agent/guards/redaction.py` wouldn't exist on an older seed branch without a rebase.
**Consequences:** Commit-SHA and changed-files semantics are clean and meaningful. The Fix Agent's "cannot touch its own source" constraint (§7.3) becomes a filesystem-level guarantee — a checkout of `sample-app` alone never has agent source present on disk — not just a path-string blocklist.
**Confidence:** High.

### 11. `uv` over plain `pip`/`venv` for the `agent` package

**Decision:** `agent/` is managed via `uv` with a committed `uv.lock`.
**Context:** From-scratch project, no existing tooling constraints.
**Alternatives considered:** Plain `pip` + `requirements.txt` — rejected, no reproducible lockfile.
**Consequences:** Fast, reproducible envs. `uv.lock` also becomes a real example of a lockfile that `guards/scope.py` must protect from unreasoned agent edits.
**Confidence:** Medium — first time using `uv` on this project, no track record yet.

### 12. `unidiff` over hand-rolled diff parsing

**Decision:** `guards/scope.py` and `guards/anticheat.py` parse unified diffs via the `unidiff` pip package.
**Context:** Both guards are security-relevant — they gate what an LLM-generated diff is allowed to do.
**Alternatives considered:** Regex-based diff parsing — rejected, diff-parsing edge cases (renames, binary files, multiple hunks) are exactly the kind of thing that must not be buggy in guard code that's the last line of defense before a diff is trusted.
**Consequences:** One more dependency, but a battle-tested one for a task that's easy to get subtly wrong by hand.
**Confidence:** High.

### 13. Fixtures-before-cluster over cluster-first

**Decision:** M0 captures/hand-authors JSON fixtures once (`fixtures/<seed>/context.json`); M1-M4 — the agents, the actual product — are built and tested entirely against those fixtures, with zero cluster dependency. Argo becomes an integration step (M5), not a prerequisite for agent development.
**Context:** The original milestone ordering front-loaded Kubernetes/Argo plumbing ahead of the agents. If time ran short under that ordering, the likely outcome was working infrastructure and no agents — the least differentiating part of the project finished, the most differentiating part unstarted.
**Alternatives considered:** Cluster-first ordering (original spec's milestone numbering, M0=cluster, M1=plumbing, M2=agents...) — rejected after the first plan review specifically because it inverted risk vs. value.
**Consequences:** M1-M4 can be developed and tested with `k3d cluster delete` already run — proven, not assumed, as an explicit M0 exit check. The cost is that fixtures are a fixed snapshot; M5's live-captured payload has to be checked for structural drift against them.
**Confidence:** High — this was the single most consequential revision from plan review.

### 14. LangGraph + confidence scoring live at M4, not M5

**Decision:** The LangGraph `StateGraph` orchestration and the confidence-scoring module are built at M4, the "minimum demoable system" checkpoint — not deferred to a later milestone.
**Context:** Multi-agent orchestration across distinct, separable roles is the core architectural claim of this project ("a real multi-agent architecture... not one LLM call wrapped in a retry loop").
**Alternatives considered:** A straight-line scripted driver at M4, with real orchestration deferred to M5 — this was the original plan's approach, rejected on review because it put the project's actual differentiator two milestones past the point the project might have to stop at.
**Consequences:** M4 is more work than a script would have been, but the "minimum demoable system" checkpoint is honest — it demonstrates the thing the project is actually about, not a placeholder for it.
**Confidence:** High.

### 15. Verification builds one dependency-baked image, mounts source + diff at run time

**Decision:** Verification does not `docker build` a fresh image per candidate fix. One image with dependencies baked in is built once (rebuilt only when `requirements.txt` changes); each verification run bind-mounts a source checkout and an optional diff file into a container at `docker run` time.
**Context:** A rebuild-per-attempt loop on a Python base image costs minutes per cycle, and verification runs dozens of times during Fix Agent debugging.
**Alternatives considered:** Build two fresh images (baseline + patched) per verification attempt, as originally planned — rejected on review as an unforced bottleneck identified before it became painful in practice.
**Consequences:** Verification iteration drops from minutes to seconds per attempt. The same pattern is carried into M5's Argo sandbox (diff supplied as an input artifact against one pre-built pod image).
**Confidence:** High.

### 16. Triage has a two-model fallback ladder

**Decision:** Triage's first attempt uses `qwen3.5:0.8b`. If structured-output schema validation exhausts its retries, Triage escalates once to `qwen3.5:latest` before giving up. The trace event's `model` field always records whichever model actually produced the verdict.
**Context:** A 0.8B model reliably emitting schema-valid JSON for a six-way classification, every time, is optimistic — not a hard requirement to build around from day one, but a real risk not to plan for.
**Alternatives considered:** Single fixed model for Triage (either always the small one, accepting failures, or always the larger one, losing the cost/latency benefit of the tiered design) — rejected in favor of a ladder that gets both.
**Consequences:** Slightly more complex Triage logic; a concrete thing to observe and log once real Ollama calls are made — see LOG.md for how this actually lands.
**Confidence:** Medium — the ladder's necessity is a prediction, not yet observed.

### 17. `CONFIG_OR_SECRET` gets a deterministic pre-LLM detector plus its own seed

**Decision:** `agent/guards/secret_detector.py`, mirroring `infra_detector.py`, pattern-matches auth/credential failure signatures (401/403, "authentication failed", "invalid credentials", "missing required environment variable") and short-circuits Triage directly to `CONFIG_OR_SECRET`, bypassing the LLM. A `seed/config-secret` branch and fixture exist to exercise it.
**Context:** `CONFIG_OR_SECRET` was the only MVP triage category with no pre-LLM detector and no seed in the original plan, unlike `INFRA_FAILURE`.
**Alternatives considered:** Rely on the LLM classifier alone for this category — rejected: expired/missing credentials are a class the system must never attempt to "fix," and that guarantee shouldn't hinge on a 0.8B model classifying correctly under load.
**Consequences:** One more deterministic guard to maintain, but a hard guarantee against ever proposing a "fix" for an auth failure, independent of model quality.
**Confidence:** High.

### 18. Argo lifecycle hooks over classic `onExit` + `when:`

**Decision:** `spec.hooks.exit` with `expression: workflow.status == 'Failed'` (used starting M5).
**Context:** Need the exit handler to fire only on failure, not on every completion.
**Alternatives considered:** Classic `onExit` template plus an in-template `when:` condition — works, but always fires and self-filters rather than natively expressing the condition.
**Consequences:** Cleaner manifest, condition expressed once at the hook declaration rather than duplicated inside the template logic.
**Confidence:** Medium — not yet implemented (M5 work); reasoning is sound based on Argo's documented hook semantics but unverified in this project.

### 19. Seeded flaky test via `random.random()` threshold, not timing

**Decision:** `seed/flaky-test`'s flaky test fails ~15-20% of the time via an unseeded `random.random()` comparison, not a timing/sleep-based race.
**Context:** Need a controllable, reproducible-in-aggregate failure rate for testing the flake-retry path.
**Alternatives considered:** Timing-based flakiness (e.g., a race against a sleep) — rejected: failure rate would depend on container CPU contention, making it flaky about its own flakiness and harder to reason about during debugging.
**Consequences:** Failure rate is a simple, auditable constant in test code.
**Confidence:** High.

### 20. `kubectl logs` via a scoped ServiceAccount over the Argo Server REST API

**Decision:** Log fetching (M0's fixture capture, M5's live exit handler) uses `kubectl logs <pod>` via a scoped ServiceAccount, not the Argo Server REST API.
**Context:** Both are valid extension points per the spec.
**Alternatives considered:** Argo Server REST API — would give richer log/node metadata in one call, but requires argo-server to be reachable and authenticated from inside a pod (or from the capture script), an extra moving part.
**Consequences:** Fewer moving parts for now. If a later milestone needs richer metadata than `kubectl logs` + `argo get -o json` provides, revisit.
**Confidence:** Medium.

### 21. Verification Agent is fully deterministic, not LLM-backed

**Decision:** `agent/agents/verify.py` never calls an LLM. It runs the test suite and computes a pass/fail delta purely programmatically.
**Context:** The spec's per-agent model tier table lists Verification as "Small/local — mostly deterministic; LLM only summarizes," implying an optional LLM summarization step.
**Alternatives considered:** A small local model summarizing verification results for the trace/PR body — deferred as a documented, clearly-labeled optional enhancement, not required for the M4 exit criterion.
**Consequences:** Verification is simpler to test (no mocking an LLM call, no structured-output retry logic in the hot path that runs dozens of times per debugging session) and faster.
**Confidence:** High.

### 22. `infra-failure`'s fixture is captured live; `flaky-test` and `config-secret` stay hand-authored

**Decision:** `fixtures/infra-failure/context.json` is captured from a real k3d/Argo run of `seed/infra-failure`, not hand-authored. `fixtures/flaky-test/context.json` and `fixtures/config-secret/context.json` remain hand-authored.
**Context:** `infra_detector.py` is tested against the `infra-failure` fixture. Hand-authoring that fixture's log content would make the test circular — write the log to match the detector's pattern, then assert the pattern matches. The cluster is already up for `m0-bad-import`/`code-defect` capture, so the marginal cost of also running `seed/infra-failure` through it is one workflow submission.
**Alternatives considered:** Hand-author all three non-trivial fixtures for simplicity — rejected specifically for `infra-failure` because it defeats the purpose of having a detector test at all. Kept for `flaky-test` (nondeterministic by construction — "already failed" is simpler to author than to orchestrate a live probabilistic trigger) and `config-secret` (needs a deliberately embedded secret-shaped string for the redaction test, which is easier to guarantee by hand-authoring).
**Consequences:** `infra_detector.py` has to handle whatever real k3d OOMKill output actually looks like — including the likelihood that `kubectl logs` on an OOMKilled pod returns empty, pushing the real signal into Argo node status instead of log text. `secret_detector.py`'s test, by contrast, validates against synthetic input only — flagged explicitly as an M7 hardening item to re-capture `config-secret` (and ideally `flaky-test`) against real cluster runs.
**Confidence:** High.

### 23. Orchestrator state is a plain `TypedDict`, not a pydantic model, with no checkpointing

**Decision:** `agent/orchestrator.py`'s `GraphState` is a `TypedDict`, and `build_graph()` compiles with no checkpointer — state lives in-process for the duration of one `graph.invoke()` call and is discarded after.
**Context:** LangGraph's `StateGraph` supports both `TypedDict` and pydantic-model state schemas. Every other I/O contract in this project is pydantic (decision context, spec §9.2) — reaching for pydantic here too would be the "obvious" choice.
**Alternatives considered:** A pydantic `GraphState` — rejected because the graph's state also has to hold non-serializable runtime objects (`LLMProvider`, a `Path` to a live worktree) that don't need validation and would just add friction; the individual node payloads (`TriageResult`, `DiagnosisResult`, ...) are already pydantic, so validation isn't lost, just not re-applied at the state-container level. A checkpointer (e.g. `MemorySaver`) — explicitly deferred per the approved plan: "no checkpointing/persistence yet... that's a later hardening concern, not required for the demoable checkpoint."
**Consequences:** `run_orchestrator()` owns the worktree's lifecycle directly (create before `graph.invoke()`, remove in `finally`) rather than the graph managing resource cleanup itself — resuming a run after a crash isn't possible yet, which is fine until M5+ needs long-running/resumable executions against a real cluster.
**Confidence:** Medium — right for a single-process demo; will need revisiting once M5's Argo integration wants a graph run to survive across separate exit-hook invocations.

### 24. Flaky-test retry runs locally against a worktree, not via a live cluster resubmission

**Decision:** `agent/guards/flake_retry.py::retry_flaky_test_locally()` re-runs the specific failing test node with a direct `pytest` subprocess call against a local git worktree checkout — no Docker, no Argo, no cluster.
**Context:** `flake_retry.py`'s original M1 docstring assumed the retry boolean would eventually come from "a real re-submission" the orchestrator supplies once a live cluster exists — written when the working assumption was that this capability would arrive alongside cluster integration. The approved plan places LangGraph orchestration at M4, explicitly with no cluster dependency ("Runnable end-to-end from the terminal with no cluster present"), which arrives one full milestone before M5's Argo integration — so a literal live re-submission isn't available yet at the milestone that needs to exercise this path.
**Alternatives considered:** A second hand-authored "retry passed" fixture variant, selected by some out-of-band signal — considered in M1's design but never built; would have made the retry outcome fixed and fake rather than a real signal, and doesn't extend cleanly to "what if a real seed's flaky test needs retrying." Waiting until M5 to build any retry path at all — rejected because the plan requires the retry path to be exercised at M4, not left as a TODO past the milestone the project might stop at.
**Consequences:** The retry is real, not simulated — `seed/flaky-test`'s test genuinely re-executes and can land either way (~15-20% reproduce rate by construction, decision #19), so both branches of the routing logic get exercised across enough runs rather than deterministically once. Only works because the flaky seed test has zero package dependency (plain `random.random()`, no `sample_app` import) — a flaky test that needed the package installed would need a heavier retry mechanism (e.g. routing through the M3 Docker verification image instead of a bare subprocess).
**Confidence:** Medium — solid for this specific seed; the "no package dependency" assumption is called out because it won't hold for every future flaky fixture.

### 25. Confidence score is computed from the diff's actual line count, not the Fix Agent's self-reported `blast_radius`

**Decision:** `agent/confidence.py::compute_confidence()` uses `fix.diff.count("\n")` as its diff-size signal, ignoring `FixResult.blast_radius` (a free-text string the Fix LLM writes describing its own change).
**Context:** Decision #5 already establishes that confidence must be signal-derived, never LLM self-report. `blast_radius` is exactly the kind of field that decision warns about: it's the model's own description of how big its change is, generated in the same call that produced the change.
**Alternatives considered:** Parsing `blast_radius` text for a rough size estimate — rejected outright; using it, even indirectly, reintroduces the self-report dependency decision #5 was written to rule out. `blast_radius` is kept in `FixResult` purely as a human-readable trace/PR-description field, not as confidence input.
**Consequences:** Confidence's diff-size signal is exact and independent of how well the model describes its own work, at the cost of being a cruder proxy (raw line count) than a model's semantic summary might have offered.
**Confidence:** High.
