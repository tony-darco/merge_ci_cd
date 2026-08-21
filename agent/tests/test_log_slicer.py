from agent.context.log_slicer import slice_log

# A large synthetic log with a real error near the top and a lot of noise
# after it, so tail-first slicing alone would lose the actual signal if
# error-marker anchoring weren't also in play.
_SYNTHETIC_LOG = (
    "Traceback (most recent call last):\n"
    '  File "app.py", line 42, in run\n'
    "    raise ValueError('bad config')\n"
    "ValueError: bad config\n"
    + ("noise noise noise this line is just filler output\n" * 20000)
)


def test_small_context_model_gets_a_meaningfully_smaller_slice():
    small = slice_log(_SYNTHETIC_LOG, "deepseek-coder:latest")  # 16384 ctx
    large = slice_log(_SYNTHETIC_LOG, "qwen3.5:latest")  # 262144 ctx
    assert len(small) < len(large)


def test_small_context_slice_stays_under_budget():
    small = slice_log(_SYNTHETIC_LOG, "deepseek-coder:latest")
    # 16384 ctx * ~3.5 chars/token is roughly 57k chars before reserve_ratio;
    # the untruncated synthetic log is ~1M chars, so a real budget cap must bite.
    assert len(small) < len(_SYNTHETIC_LOG) / 10


def test_slice_preserves_error_marker_even_when_far_from_tail():
    small = slice_log(_SYNTHETIC_LOG, "deepseek-coder:latest")
    assert "ValueError: bad config" in small


def test_untruncated_log_returned_as_is_when_it_fits():
    short_log = "FAILED tests/test_x.py::test_y - AssertionError\n"
    sliced = slice_log(short_log, "qwen3.5:latest")
    assert short_log in sliced


def test_output_is_delimited_as_untrusted_data():
    sliced = slice_log("some log content", "qwen3.5:latest")
    assert "<untrusted_log_data>" in sliced
    assert "</untrusted_log_data>" in sliced
