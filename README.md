# Agentic CI/CD Fixer

An agentic layer on top of Argo Workflows: when a CI pipeline fails, it diagnoses the root cause, proposes a minimal fix, verifies that fix in a sandbox, and reports a signal-derived confidence score — with a human always in the loop. It never merges anything itself.

## What this actually is

A pipeline failure isn't automatically "this needs a code fix." It might be a flaky test, an OOMKilled pod, an expired credential, or a real bug. Treating all four the same — or worse, having an LLM "fix" the ones that aren't fixable — is how you get a system nobody trusts. So this project is built as a chain of narrow, single-purpose agents, each with a job it's good at, gated by deterministic guards that don't depend on a model behaving correctly:

```
Triage → Diagnosis → Fix → Scope Guard → Anti-Cheat Guard → Verify → Confidence
```

- **Triage** classifies the failure into one of six categories. Two of them (`INFRA_FAILURE`, `CONFIG_OR_SECRET`) are caught by deterministic pattern detectors *before* any LLM call — an OOMKilled pod or an auth failure should never depend on a small model classifying correctly under load. Only `CODE_DEFECT`/`DEPENDENCY_ISSUE` proceed toward a fix; `FLAKY` gets one real retry before either being confirmed a flake or promoted to a real diagnosis.
- **Diagnosis** produces a root-cause hypothesis with cited log evidence — a hypothesis with no evidence backing it is rejected — and degrades to "insufficient evidence" rather than hallucinating when the log is empty or too short.
- **Fix** reads only the relevant source files (following the failing test's own imports if Diagnosis pointed at the wrong file) and returns full replacement file content, which is then diffed against the real file with `difflib` — never a raw LLM-generated diff, which is a much less reliable format for small models to produce correctly.
- **Scope Guard** and **Anti-Cheat Guard** are pure static analysis over the diff, enforced in code: a path allowlist, a line budget, a lockfile-needs-a-reason rule, and rejection of the obvious ways a naive agent "succeeds" — deleting the failing test, adding `@pytest.mark.skip`, weakening an assertion. None of this is prompt-only; a rule that only lives in the prompt isn't a rule.
- **Verify** is fully deterministic, not LLM-backed: it runs the real test suite against baseline and patched checkouts and diffs the results by test id. Two interchangeable backends share one interface — Docker locally, and real Argo Workflows in a sandbox namespace with a default-deny egress policy. The sandboxed one proves its own isolation before running anything and fails closed if it can't.
- **Confidence** is computed purely from signals already produced by the run above — verification result, diagnosis ambiguity, diff size, fix-attempt count — never from an LLM self-reporting how confident it is.
- **The PR** is opened only when a fix actually verified, only when explicitly asked for, and always left open for a human. Its body is assembled from the run's own recorded trace, states plainly what "verified" did and did not mean, and describes the environment the tests really ran in rather than claiming isolation it may not have had.

All of this is orchestrated as a real [LangGraph](https://github.com/langchain-ai/langgraph) `StateGraph` ([agent/orchestrator.py](agent/orchestrator.py)), not a linear script — multi-agent orchestration with real conditional edges (refuse, retry-with-feedback, human-review-stop) is the actual architectural claim of this project, not incidental plumbing.

Every decision any agent makes is recorded as a structured `TraceEvent` ([agent/trace.py](agent/trace.py)) with a `reasoning` field that's *validated non-empty* — a decision with no reasoning is treated as a bug, not a logging gap. Alongside that, [DECISIONS.md](DECISIONS.md) and [LOG.md](LOG.md) are living, non-negotiable deliverables: an ADR-style record of every architectural call (including the ones that turned out wrong) and a running log of what actually broke during the build and how it got fixed. Most agentic-CI demos don't publish that record; this one treats it as the most differentiating artifact of the project.

**Status: complete (M0–M7).** The full loop runs live: a real Argo pipeline fails, an exit hook fires, the agents diagnose and fix, the fix is verified in a locked-down sandbox namespace, and a pull request is opened for human review with a confidence score and the decision trace that produced it.

## The two writeups

The most differentiating artifacts here are not the code:

- **[DECISIONS.md](DECISIONS.md)** — an ADR-style record of all 35 architectural decisions, each with the alternatives considered and a stated confidence level, written at the moment of the decision rather than reconstructed afterward. Includes the ones that turned out wrong.
- **[LOG.md](LOG.md)** — every problem that broke the build, written while it was broken: the symptom, what I assumed, what I tried, the actual root cause, and the fix. Many entries are more instructive than the code they explain — a NetworkPolicy that looked broken and wasn't, a scoped RBAC identity that was never actually in use, and a triage model measured at 67% accuracy on the project's own running example.

## Setup

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Docker (for the verification sandbox)
- An [Ollama](https://ollama.com) host reachable over the network, with these models pulled: `qwen3.5:0.8b`, `qwen3.5:latest`, `qwen3-coder:30b`
- `k3d`, `argo` CLI, `kubectl` — only needed to redo M0's fixture capture or for future M5 work; **not needed** to run M1–M4

```bash
brew install k3d argo uv
```

### Install dependencies

```bash
uv sync
```

### Recreate the sample app

The agents' target codebase (`sample-app/`) is a **separate git repository** with its own branches — one per seeded failure type — so that a "seed" branch forks only the victim app, never this project's own source (see [DECISIONS.md #10](DECISIONS.md)). It's gitignored and has no remote, so a fresh clone of this repo doesn't include it:

```bash
uv run scripts/bootstrap_sample_app.py
```

This recreates `sample-app/` with `main` plus five seed branches (`seed/m0-bad-import`, `seed/code-defect`, `seed/infra-failure`, `seed/flaky-test`, `seed/config-secret`). Every test and script in this repo depends on it existing.

### Point at your Ollama host

```bash
export OLLAMA_BASE_URL=http://your-ollama-host:11434   # defaults to http://192.168.1.17:11434
```

Then confirm all four configured models are actually pulled:

```bash
uv run python -m agent.startup
```

## Running it

### Run the full loop against a live cluster

```bash
k3d cluster create agentic-fixer --agents 1
kubectl create namespace argo
kubectl apply -n argo --server-side -f manifests/argo-install/quick-start-minimal.yaml
kubectl apply -f manifests/sandbox-namespace.yaml
kubectl get secret my-minio-cred -n argo -o yaml \
  | sed 's/namespace: argo/namespace: agentic-fixer-sandbox/' | kubectl apply -f -
kubectl apply -f manifests/exit-handler-rbac.yaml -f manifests/verify-workflow.yaml -f manifests/exit-hook.yaml

docker build -t agentic-fixer-agent:latest .
docker build -f verify/Dockerfile -t agentic-fixer-verify:base .
k3d image import agentic-fixer-agent:latest agentic-fixer-verify:base -c agentic-fixer

uv run scripts/submit_pipeline.py --seed code-defect
```

The pipeline fails, the exit hook fires, and the agent runs in-cluster. Watch it with
`argo logs <workflow> -n argo`, and see the sandboxed verification workflows with
`kubectl get workflows -n agentic-fixer-sandbox`.

### Run the orchestrator against a fixture

```bash
uv run python -m agent.orchestrator --seed code-defect
```

```
RESULT: verified fix, confidence=HIGH, 14/14 passing, 0 regressions, 1 fix attempt(s)
```

Available `--seed` values, each backed by a pre-captured fixture under [fixtures/](fixtures/) (no live cluster needed):

| seed | what happens |
|---|---|
| `code-defect` | a real bug (`apply_percentage_discount` divides by 100 twice) — full pipeline: diagnosed, fixed, verified, scored |
| `infra-failure` | OOMKilled pod — refused at Triage by the deterministic infra detector, never reaches the LLM |
| `config-secret` | missing/invalid `API_TOKEN` — refused at Triage by the deterministic secret detector, never reaches the LLM |
| `flaky-test` | a test that fails ~15% of the time by construction — Triage classifies it `FLAKY`, then the orchestrator actually re-runs the real test locally; it's either confirmed a flake (most runs) or promoted to a real diagnosis |
| `m0-bad-import` | a trivial `ModuleNotFoundError` — captured to prove the pipeline/UI works end-to-end at M0; not one of the four paths in M4's exit criteria, but nothing stops you running it through the orchestrator too |

Each run creates and tears down a scratch git worktree of the seed branch automatically — your `sample-app/` working tree is never touched.

### Run the test suite

```bash
uv run pytest agent/tests/ -v
```

90 tests as of M7. Tests that hit real external systems (GitHub, a live cluster) are
marked `live` and excluded from a bare `pytest`; run them with `pytest -m live`.
Otherwise: Most are fixture-driven and need neither network nor Docker; `test_verify.py` needs Docker (it builds and runs the verification image for real); 13 tests across `test_triage.py`, `test_diagnosis.py`, `test_triage_fallback.py`, `test_registry.py`, and `test_log_slicer.py` call the real Ollama host and will fail with `httpx.ConnectTimeout` if it's unreachable — that's a network problem, not a code problem (see the M4 entries in [LOG.md](LOG.md) for exactly this happening and getting resolved).

### Run just the Fix Agent

Useful for iterating on Diagnosis/Fix without the full graph:

```bash
uv run scripts/run_fix_agent.py --seed code-defect
```

Writes the resulting diff to `out/<seed>-fix.diff` and prints both guards' verdicts.

### Open a real pull request

```bash
uv run python -m agent.orchestrator --seed code-defect --open-pr
```

Off by default: opening a PR is a side effect on a real repository and shouldn't happen
because someone re-ran a demo. Only reachable when verification actually passed.

### Redo the M0 fixture capture (optional)

Only needed if you want to regenerate `fixtures/*/context.json` from a real cluster run instead of using the ones already committed:

```bash
k3d cluster create agentic-fixer --agents 1
kubectl create namespace argo
kubectl apply -n argo --server-side -f manifests/argo-install/quick-start-minimal.yaml
kubectl -n argo port-forward svc/argo-server 2746:2746 &

uv run scripts/submit_pipeline.py --seed code-defect
uv run scripts/capture_fixture.py --seed code-defect --workflow-name <name-from-submit>

k3d cluster delete agentic-fixer   # nothing past M0 needs the cluster alive
```

## Using it

**Reading a result.** `describe_outcome()` prints one line summarizing where the run stopped and why — a verified fix with its confidence tier, a Triage refusal with its category and reasoning, a scope/anti-cheat rejection with its specific reasons, or a human-review flag. That line is derived from the same `TraceEvent`s recorded during the run, not a separate summary — nothing is reported that isn't traceable.

**Reading the trace.** Every run appends structured `TraceEvent`s to `traces/<run-id>.jsonl` — one per agent decision, each with a mandatory non-empty `reasoning`, cited `evidence`, `alternatives_rejected`, and (for LLM-backed decisions) which model actually produced it. This is the audit trail; a future PR body (M6) will be built directly from it.

**Trusting a fix.** Don't take a passing scope/anti-cheat check as proof the diff is *correct* — those guards check that the diff stays in-bounds and isn't gaming the tests, not that it fixes the right thing. `confidence=HIGH` requires all three: verification passed with zero regressions, Diagnosis had one unambiguous hypothesis (no `alternative_hypothesis`), and the fix was small and landed on the first attempt. Anything short of that — a second attempt needed, an alternative hypothesis considered, a larger diff — comes back `MEDIUM`, and a failed verification is always `LOW`. Confidence is never asked of the model; it's computed after the fact from what actually happened.

**When a run doesn't finish cleanly**, the outcome tells you why, and it's always one of a small set of reasons: Triage refused (not a fixable category), Diagnosis had insufficient evidence, a guard rejected the diff outright, a guard flagged it for mandatory human review, or verification never passed after the retry budget (2 fix attempts) was exhausted. None of these are errors — they're the system correctly declining to act past what it can verify.

**Extending it.** Adding a new seeded failure type means: a new branch in `sample-app` (or update `scripts/bootstrap_sample_app.py` to generate it), a fixture under `fixtures/<name>/context.json` matching `FailureContext`'s schema ([agent/llm/schema.py](agent/llm/schema.py)), and — if it needs to bypass the LLM the way `INFRA_FAILURE`/`CONFIG_OR_SECRET` do — a new deterministic detector under `agent/guards/`, added to `_DETECTORS` in [agent/agents/triage.py](agent/agents/triage.py).

## Project layout

```
agent/
  agents/        triage.py, diagnosis.py, fix.py, verify.py
  guards/        scope.py, anticheat.py, infra_detector.py, secret_detector.py,
                 redaction.py, evidence_check.py, cascade_filter.py, flake_retry.py
  llm/           provider-agnostic interface, schema.py (every I/O contract), Ollama provider
  context/       log_slicer.py -- context-window-aware slicing with prompt-injection delimiters
  confidence.py  signal-derived confidence scoring
  orchestrator.py  the LangGraph StateGraph and CLI driver
  trace.py       the decision-trace data model
  tests/         68 tests, mostly fixture-driven
fixtures/        one context.json per seeded failure type, the fixed contract between
                 a live cluster and fixture-driven agent development
manifests/       Argo install manifests + the sample pipeline definition
scripts/         bootstrap_sample_app.py, submit_pipeline.py, capture_fixture.py, run_fix_agent.py
verify/          the Docker verification image (build once, mount source + diff per run)
sample-app/      separate git repo, the agents' target codebase (gitignored, not in this repo's history)
DECISIONS.md     ADR-style record of every architectural decision, including the wrong ones
LOG.md           running log of what broke during the build and how it got fixed
```
