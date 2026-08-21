import pytest

from agent.llm.registry import ModelNotAvailableError, get_context_window, list_available_models, validate_model_available


def test_list_available_models_includes_configured_models():
    models = list_available_models()
    assert "qwen3.5:latest" in models


def test_validate_model_available_passes_for_pulled_model():
    validate_model_available("qwen3.5:0.8b")  # should not raise


def test_validate_model_available_raises_for_missing_model():
    with pytest.raises(ModelNotAvailableError):
        validate_model_available("definitely-not-a-real-model:latest")


def test_get_context_window_matches_known_value():
    assert get_context_window("qwen3.5:latest") == 262144
