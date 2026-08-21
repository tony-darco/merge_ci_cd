from agent.guards.scope import validate_diff

_VALID_DIFF = """--- a/src/sample_app/discounts.py
+++ b/src/sample_app/discounts.py
@@ -2,4 +2,4 @@
     if not 0 <= pct <= 100:
         raise ValueError(f"bad")
     result = amount * (1 - pct / 100)
-    return result / 100
+    return result
"""


def test_accepts_valid_in_scope_diff():
    result = validate_diff(_VALID_DIFF)
    assert result.rejected is False
    assert result.reasons == []


def test_rejects_diff_touching_ci_config():
    diff = """--- a/manifests/sample-pipeline.yaml
+++ b/manifests/sample-pipeline.yaml
@@ -1,1 +1,1 @@
-old
+new
"""
    result = validate_diff(diff)
    assert result.rejected is True
    assert any("manifests/sample-pipeline.yaml" in r for r in result.reasons)


def test_rejects_diff_outside_allowlisted_paths():
    diff = """--- a/README.md
+++ b/README.md
@@ -1,1 +1,1 @@
-old
+new
"""
    result = validate_diff(diff)
    assert result.rejected is True
    assert any("allowlisted" in r for r in result.reasons)


def test_rejects_diff_exceeding_line_budget():
    old_lines = "\n".join(f"line{i}" for i in range(200)) + "\n"
    new_lines = "\n".join(f"line{i}_changed" for i in range(200)) + "\n"
    import difflib
    diff = "".join(difflib.unified_diff(
        old_lines.splitlines(keepends=True), new_lines.splitlines(keepends=True),
        fromfile="a/src/sample_app/big.py", tofile="b/src/sample_app/big.py",
    ))
    result = validate_diff(diff)
    assert result.rejected is True
    assert any("line budget" in r or "150-line" in r for r in result.reasons)


def test_rejects_lockfile_change_without_reason():
    diff = """--- a/requirements.txt
+++ b/requirements.txt
@@ -1,1 +1,1 @@
-pytest>=8
+pytest>=9
"""
    result = validate_diff(diff, lockfile_change_reason=None)
    assert result.rejected is True
    assert any("lockfile_change_reason" in r for r in result.reasons)


def test_accepts_lockfile_change_with_reason():
    diff = """--- a/requirements.txt
+++ b/requirements.txt
@@ -1,1 +1,1 @@
-pytest>=8
+pytest>=9
"""
    result = validate_diff(diff, lockfile_change_reason="bumping pytest for a security fix")
    assert result.rejected is False


def test_rejects_diff_touching_agent_source():
    diff = """--- a/agent/guards/scope.py
+++ b/agent/guards/scope.py
@@ -1,1 +1,1 @@
-old
+new
"""
    result = validate_diff(diff)
    assert result.rejected is True
    assert any("agent's own source" in r for r in result.reasons)


def test_rejects_unparseable_diff():
    result = validate_diff("this is not a diff at all")
    assert result.rejected is True
