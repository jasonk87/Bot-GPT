from verification import (

    choose_verification_steps,
    classify_verification_failure,
    should_continue_repair,
    summarize_verification_results,
)


def test_failure_classifier_categories():
    assert classify_verification_failure("SyntaxError: invalid syntax") == "syntax_error"
    assert classify_verification_failure("ModuleNotFoundError: No module named x") == "import_error"
    assert classify_verification_failure("pytest FAILED test_foo") == "failing_test"
    assert classify_verification_failure("eslint lint issue") == "lint_error"
    assert classify_verification_failure("mypy: error: Incompatible types") == "type_error"


def test_choose_verification_steps_supports_multiple_step_types():
    steps = choose_verification_steps(
        ["app/main.py", "static/main.js", "frontend/view.tsx", "tests/test_app.py"],
        "please fix and run tests",
    )
    step_types = {step.step_type for step in steps}
    assert "lint" in step_types
    assert "build_typecheck" in step_types
    assert "test" in step_types


def test_should_continue_repair_stops_for_blocking_dependency():
    pending = {"classification": "missing_dependency"}
    assert should_continue_repair(pending, attempts=1, max_attempts=3) is False


def test_should_continue_repair_allows_retry_for_fixable_failure():
    pending = {"classification": "failing_test"}
    assert should_continue_repair(pending, attempts=1, max_attempts=3) is True
    assert should_continue_repair(pending, attempts=3, max_attempts=3) is False


def test_summarize_verification_results_includes_status_and_classification():
    summary = summarize_verification_results([
        {
            "step_type": "test",
            "command": "pytest -q",
            "success": False,
            "classification": "failing_test",
        },
        {
            "step_type": "lint",
            "command": "python -m py_compile a.py",
            "success": True,
            "classification": None,
        },
    ])
    assert "FAIL" in summary
    assert "failing_test" in summary
    assert "PASS" in summary
