from agent.config import VERIFIER
from agent.verifiers.base import Verifier


def get_verifier() -> Verifier:
    if VERIFIER == "argo":
        from agent.verifiers.argo import ArgoVerifier

        return ArgoVerifier()
    from agent.verifiers.docker import DockerVerifier

    return DockerVerifier()
