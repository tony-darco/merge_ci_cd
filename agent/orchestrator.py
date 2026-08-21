"""M4: the real CLI driver from here on -- replaces the earlier idea of a
separate demo script entirely. Wires the M1-M3 agent functions and M2/M3
guards into a LangGraph StateGraph with real conditional edges: multi-agent
orchestration is the actual product this system builds (DECISIONS.md #14),
so it has to exist at whichever milestone the project stops at, not past it.

No checkpointing/persistence: state lives in-process for one run (a later
hardening concern, not required for the demoable checkpoint).

Usage: python -m agent.orchestrator --seed <name>
"""

import argparse
import re
import subprocess
import tempfile
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, StateGraph

from agent.agents.diagnosis import run_diagnosis
from agent.agents.fix import run_fix
from agent.agents.triage import run_triage
from agent.agents.verify import run_verification
from agent.confidence import compute_confidence
from agent.guards.anticheat import check_diff
from agent.guards.cascade_filter import select_root_failure
from agent.guards.flake_retry import (
    retry_flaky_test_locally,
    should_proceed_to_diagnosis_after_retry,
)
from agent.guards.scope import ScopeCheckResult, validate_diff
from agent.llm.interface import LLMProvider
from agent.llm.providers.ollama import OllamaProvider
from agent.llm.schema import (
    FIXABLE_CATEGORIES,
    AntiCheatResult,
    DiagnosisResult,
    FailureContext,
    FixResult,
    TriageResult,
    VerificationResult,
)
from agent.tests.fixtures import load_fixture

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_APP_DIR = REPO_ROOT / "sample-app"

# N=2 total fix attempts (spec §5.5) and a defensive backstop on total LLM
# calls per run -- both enforced in the graph's routing logic, not just
# documented.
MAX_FIX_ATTEMPTS = 2
MAX_LLM_CALLS = 10

_FAILED_NODE_PATTERN = re.compile(r"^FAILED (\S+)", re.MULTILINE)


class GraphState(TypedDict, total=False):
    context: FailureContext
    checkout_path: Path
    provider: LLMProvider
    triage: TriageResult
    retry_reproduced: bool
    diagnosis: DiagnosisResult
    fix: FixResult
    fix_attempts: int
    scope_result: ScopeCheckResult
    anticheat_result: AntiCheatResult
    verification: VerificationResult
    llm_calls: int
    confidence: str


def _extract_failed_node_ids(logs: dict[str, str]) -> list[str]:
    ids: list[str] = []
    for log in logs.values():
        for match in _FAILED_NODE_PATTERN.finditer(log):
            if match.group(1) not in ids:
                ids.append(match.group(1))
    return ids


def _test_function_name(node_id: str) -> str:
    return node_id.rsplit("::", 1)[-1]


# --- nodes -------------------------------------------------------------

def _node_triage(state: GraphState) -> dict:
    result = run_triage(state["context"], state["provider"])
    return {"triage": result, "llm_calls": state.get("llm_calls", 0) + 1}


def _node_flaky_retry(state: GraphState) -> dict:
    node_ids = _extract_failed_node_ids(state["context"].logs)
    if not node_ids:
        # nothing parseable to re-run -- treat as a real, reproducing
        # failure rather than silently discarding it as "just a flake."
        return {"retry_reproduced": True}
    reproduced = retry_flaky_test_locally(state["checkout_path"], node_ids[0])
    return {"retry_reproduced": reproduced}


def _node_diagnosis(state: GraphState) -> dict:
    root_node = select_root_failure(state["context"].failed_nodes)
    result = run_diagnosis(state["context"], root_node, state["provider"])
    called_llm = result.root_cause != "insufficient evidence"
    return {"diagnosis": result, "llm_calls": state.get("llm_calls", 0) + (1 if called_llm else 0)}


def _node_fix(state: GraphState) -> dict:
    feedback = None
    previous_verification = state.get("verification")
    if previous_verification is not None and not previous_verification.passed:
        feedback = previous_verification.delta
    result = run_fix(
        state["diagnosis"], state["context"], state["checkout_path"], state["provider"],
        verification_feedback=feedback,
    )
    return {
        "fix": result,
        "fix_attempts": state.get("fix_attempts", 0) + 1,
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def _node_scope_guard(state: GraphState) -> dict:
    result = validate_diff(state["fix"].diff, state["fix"].lockfile_change_reason)
    return {"scope_result": result}


def _node_anticheat_guard(state: GraphState) -> dict:
    failing_names = [_test_function_name(n) for n in _extract_failed_node_ids(state["context"].logs)]
    result = check_diff(state["fix"].diff, failing_names)
    return {"anticheat_result": result}


def _node_verify(state: GraphState) -> dict:
    result = run_verification(state["checkout_path"], state["fix"].diff)
    return {"verification": result}


def _node_confidence(state: GraphState) -> dict:
    score = compute_confidence(state["verification"], state["diagnosis"], state["fix"], state["fix_attempts"])
    return {"confidence": score}


# --- routing -------------------------------------------------------------

def _route_after_triage(state: GraphState) -> str:
    category = state["triage"].category
    if category in FIXABLE_CATEGORIES:
        return "diagnosis"
    if category == "FLAKY":
        return "flaky_retry"
    return "refused"


def _route_after_flaky_retry(state: GraphState) -> str:
    return "diagnosis" if should_proceed_to_diagnosis_after_retry(state["retry_reproduced"]) else "confirmed_flake"


def _route_after_diagnosis(state: GraphState) -> str:
    if state["diagnosis"].root_cause == "insufficient evidence":
        return "insufficient_evidence"
    return "fix"


def _route_after_scope(state: GraphState) -> str:
    return "rejected" if state["scope_result"].rejected else "anticheat_guard"


def _route_after_anticheat(state: GraphState) -> str:
    result = state["anticheat_result"]
    if result.rejected:
        return "rejected"
    if result.requires_human_review:
        return "human_review"
    return "verify"


def _route_after_verify(state: GraphState) -> str:
    if state["verification"].passed:
        return "confidence"
    if state["fix_attempts"] < MAX_FIX_ATTEMPTS and state.get("llm_calls", 0) < MAX_LLM_CALLS:
        return "retry_fix"
    return "unresolved"


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("triage", _node_triage)
    graph.add_node("flaky_retry", _node_flaky_retry)
    graph.add_node("diagnosis", _node_diagnosis)
    graph.add_node("fix", _node_fix)
    graph.add_node("scope_guard", _node_scope_guard)
    graph.add_node("anticheat_guard", _node_anticheat_guard)
    graph.add_node("verify", _node_verify)
    graph.add_node("confidence", _node_confidence)

    graph.set_entry_point("triage")
    graph.add_conditional_edges("triage", _route_after_triage, {
        "diagnosis": "diagnosis", "flaky_retry": "flaky_retry", "refused": END,
    })
    graph.add_conditional_edges("flaky_retry", _route_after_flaky_retry, {
        "diagnosis": "diagnosis", "confirmed_flake": END,
    })
    graph.add_conditional_edges("diagnosis", _route_after_diagnosis, {
        "fix": "fix", "insufficient_evidence": END,
    })
    graph.add_edge("fix", "scope_guard")
    graph.add_conditional_edges("scope_guard", _route_after_scope, {
        "anticheat_guard": "anticheat_guard", "rejected": END,
    })
    graph.add_conditional_edges("anticheat_guard", _route_after_anticheat, {
        "verify": "verify", "rejected": END, "human_review": END,
    })
    graph.add_conditional_edges("verify", _route_after_verify, {
        "confidence": "confidence", "retry_fix": "fix", "unresolved": END,
    })
    graph.add_edge("confidence", END)
    return graph.compile()


def run_orchestrator(seed: str, provider: LLMProvider | None = None) -> GraphState:
    provider = provider or OllamaProvider()
    context = load_fixture(seed)
    branch = f"seed/{seed}"

    with tempfile.TemporaryDirectory(prefix=f"orchestrator-{seed}-") as scratch:
        subprocess.run(
            ["git", "-C", str(SAMPLE_APP_DIR), "worktree", "add", "--detach", scratch, branch],
            check=True, capture_output=True, text=True,
        )
        try:
            graph = build_graph()
            initial_state: GraphState = {
                "context": context,
                "checkout_path": Path(scratch),
                "provider": provider,
                "fix_attempts": 0,
                "llm_calls": 0,
            }
            final_state = graph.invoke(initial_state)
        finally:
            subprocess.run(
                ["git", "-C", str(SAMPLE_APP_DIR), "worktree", "remove", "--force", scratch],
                check=False, capture_output=True, text=True,
            )
    return final_state


def describe_outcome(state: GraphState) -> str:
    if "confidence" in state:
        v = state["verification"]
        total = len(v.patched_summary.passed_tests) + len(v.patched_summary.failed_tests)
        return (
            f"RESULT: verified fix, confidence={state['confidence']}, "
            f"{len(v.patched_summary.passed_tests)}/{total} passing, "
            f"{len(v.regressions)} regressions, {state.get('fix_attempts', 0)} fix attempt(s)"
        )
    if "verification" in state and not state["verification"].passed:
        return (
            f"RESULT: unresolved after {state.get('fix_attempts', 0)} fix attempt(s) -- "
            f"{state['verification'].delta}"
        )
    if "anticheat_result" in state and state["anticheat_result"].requires_human_review:
        return f"RESULT: flagged for human review -- {state['anticheat_result'].review_reasons}"
    if "anticheat_result" in state and state["anticheat_result"].rejected:
        return f"RESULT: rejected by anti-cheat guard -- {state['anticheat_result'].reject_reasons}"
    if "scope_result" in state and state["scope_result"].rejected:
        return f"RESULT: rejected by scope guard -- {state['scope_result'].reasons}"
    if "diagnosis" in state and state["diagnosis"].root_cause == "insufficient evidence":
        return "RESULT: refused -- insufficient evidence for diagnosis"
    if "retry_reproduced" in state and not state["retry_reproduced"]:
        return "RESULT: confirmed flake on retry -- no fix needed"
    if "triage" in state:
        return f"RESULT: refused at triage -- category={state['triage'].category}, reasoning={state['triage'].reasoning}"
    return "RESULT: unknown terminal state"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", required=True)
    args = parser.parse_args()

    final_state = run_orchestrator(args.seed)
    print(describe_outcome(final_state))


if __name__ == "__main__":
    main()
