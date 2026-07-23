"""Unit tests for the pure cores in promotion_core.py (Gate 2, slice 04 equivalent).

External behaviour only — no workspace, no network, no MLflow SDK calls.
Mirrors the style of modelops_reviewer/tests/test_review_core.py.

Covers:
  - build_promotion_prompt  (prompt construction from metrics + config diff)
  - parse_decision          (defensive JSON parsing: clean, fenced, malformed, missing fields)
  - bootstrap_decision      (auto-APPROVE when no champion exists)
  - compare_metrics         (metric comparison logic)
"""

import json
import pathlib
import sys

import pytest

# Support running from repo root without installing the package
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src" / "ml"))

import promotion_core

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

CHALLENGER = {"mae": 8.5, "max_acceptable_mae": 12.0}
CHAMPION = {"mae": 9.2, "max_acceptable_mae": 12.0}
DIFF = (
    "--- champion/config.yml\n+++ challenger/config.yml\n"
    "@@ -3 +3 @@\n-  n_estimators: 50\n+  n_estimators: 100\n"
)


def _valid_response(**overrides) -> dict:
    base = {
        "decision": "APPROVE",
        "findings": [],
        "justification": "Challenger MAE is lower than champion; config change is benign.",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# build_promotion_prompt
# ---------------------------------------------------------------------------

class TestBuildPromptContent:
    def test_returns_two_strings(self):
        system, user = promotion_core.build_promotion_prompt(CHALLENGER, CHAMPION, DIFF)
        assert isinstance(system, str) and isinstance(user, str)

    def test_system_mentions_approve_or_block(self):
        system, _ = promotion_core.build_promotion_prompt(CHALLENGER, CHAMPION, DIFF)
        assert "APPROVE" in system and "BLOCK" in system

    def test_user_contains_ml_rules_section(self):
        _, user = promotion_core.build_promotion_prompt(CHALLENGER, CHAMPION, DIFF)
        assert "ML HANDBOOK RULES" in user

    def test_user_contains_challenger_and_champion_metrics(self):
        _, user = promotion_core.build_promotion_prompt(CHALLENGER, CHAMPION, DIFF)
        assert "CHALLENGER METRICS" in user
        assert "CHAMPION METRICS" in user
        assert "8.5" in user   # challenger MAE
        assert "9.2" in user   # champion MAE

    def test_user_contains_config_diff(self):
        _, user = promotion_core.build_promotion_prompt(CHALLENGER, CHAMPION, DIFF)
        assert "n_estimators" in user

    def test_no_champion_shows_bootstrap_message(self):
        _, user = promotion_core.build_promotion_prompt(CHALLENGER, None, "(no champion)")
        assert "first deployment" in user or "no current champion" in user

    def test_no_champion_empty_dict_shows_bootstrap_message(self):
        _, user = promotion_core.build_promotion_prompt(CHALLENGER, {}, "(no champion)")
        assert "first deployment" in user or "no current champion" in user

    def test_custom_ml_rules_injected(self):
        custom_rules = "- CUSTOM-01 [BLOCKER]: Always deploy on Tuesdays."
        _, user = promotion_core.build_promotion_prompt(
            CHALLENGER, CHAMPION, DIFF, ml_rules=custom_rules
        )
        assert "CUSTOM-01" in user

    def test_default_rules_used_when_none(self):
        _, user = promotion_core.build_promotion_prompt(CHALLENGER, CHAMPION, DIFF, ml_rules=None)
        assert "ML-01" in user or "ML-02" in user  # from DEFAULT_ML_RULES

    def test_no_config_diff_shows_placeholder(self):
        _, user = promotion_core.build_promotion_prompt(CHALLENGER, CHAMPION, config_diff=None)
        assert "no config changes" in user


# ---------------------------------------------------------------------------
# parse_decision
# ---------------------------------------------------------------------------

class TestParseDecisionClean:
    def test_approve_dict_passthrough(self):
        result = promotion_core.parse_decision(_valid_response())
        assert result["decision"] == "APPROVE"
        assert isinstance(result["findings"], list)
        assert isinstance(result["justification"], str)

    def test_block_dict_passthrough(self):
        result = promotion_core.parse_decision(_valid_response(decision="BLOCK"))
        assert result["decision"] == "BLOCK"

    def test_json_string_parsed(self):
        result = promotion_core.parse_decision(json.dumps(_valid_response()))
        assert result["decision"] == "APPROVE"

    def test_decision_coerced_uppercase(self):
        result = promotion_core.parse_decision(
            {"decision": "approve", "findings": [], "justification": "ok"}
        )
        assert result["decision"] == "APPROVE"


class TestParseDecisionFencedJSON:
    def test_json_code_fence_stripped(self):
        raw = "```json\n" + json.dumps(_valid_response(decision="BLOCK")) + "\n```"
        result = promotion_core.parse_decision(raw)
        assert result["decision"] == "BLOCK"

    def test_plain_code_fence_stripped(self):
        raw = "```\n" + json.dumps(_valid_response()) + "\n```"
        result = promotion_core.parse_decision(raw)
        assert result["decision"] == "APPROVE"

    def test_prose_wrapped_json_extracted(self):
        raw = "Sure! Here's my decision:\n" + json.dumps(_valid_response()) + "\nHope that helps."
        result = promotion_core.parse_decision(raw)
        assert result["decision"] == "APPROVE"

    def test_fence_with_trailing_prose(self):
        raw = (
            "```json\n" + json.dumps(_valid_response(decision="BLOCK")) + "\n```\nAdditional notes."
        )
        result = promotion_core.parse_decision(raw)
        assert result["decision"] == "BLOCK"


class TestParseDecisionMalformed:
    def test_not_json_defaults_to_block(self):
        result = promotion_core.parse_decision("This is not JSON at all.")
        assert result["decision"] == "BLOCK"

    def test_empty_string_defaults_to_block(self):
        result = promotion_core.parse_decision("")
        assert result["decision"] == "BLOCK"

    def test_none_defaults_to_block(self):
        result = promotion_core.parse_decision(None)
        assert result["decision"] == "BLOCK"

    def test_invalid_decision_value_defaults_to_block(self):
        result = promotion_core.parse_decision(
            {"decision": "MAYBE", "findings": [], "justification": "x"}
        )
        assert result["decision"] == "BLOCK"

    def test_missing_decision_key_defaults_to_block(self):
        result = promotion_core.parse_decision({"findings": [], "justification": "x"})
        assert result["decision"] == "BLOCK"

    def test_missing_justification_gets_placeholder(self):
        result = promotion_core.parse_decision({"decision": "APPROVE", "findings": []})
        assert isinstance(result["justification"], str)
        assert len(result["justification"]) > 0

    def test_missing_findings_gets_empty_list(self):
        result = promotion_core.parse_decision({"decision": "APPROVE", "justification": "ok"})
        assert result["findings"] == []

    def test_findings_non_list_coerced_to_empty(self):
        result = promotion_core.parse_decision(
            {"decision": "APPROVE", "findings": "not a list", "justification": "ok"}
        )
        assert result["findings"] == []

    def test_never_raises(self):
        for bad in [42, [], {}, b"bytes", object()]:
            result = promotion_core.parse_decision(bad)
            assert result["decision"] in ("APPROVE", "BLOCK")

    def test_partial_json_balanced_brace_extraction(self):
        # Balanced JSON followed by trailing garbage
        raw = json.dumps(_valid_response(decision="APPROVE")) + " } extra garbage {"
        result = promotion_core.parse_decision(raw)
        assert result["decision"] == "APPROVE"


class TestParseDecisionFindings:
    def test_findings_coerced_to_clean_dicts(self):
        raw = _valid_response(
            decision="BLOCK",
            findings=[
                {"rule_id": "ML-03", "severity": "BLOCKER", "message": "MAE regressed"},
                {"rule_id": "ML-02", "severity": "suggestion", "message": "Test not updated"},
            ],
        )
        result = promotion_core.parse_decision(raw)
        assert len(result["findings"]) == 2
        assert result["findings"][0]["rule_id"] == "ML-03"
        assert result["findings"][1]["severity"] == "SUGGESTION"  # coerced to upper

    def test_non_dict_findings_entries_skipped(self):
        raw = _valid_response(
            findings=[{"rule_id": "ML-01", "severity": "BLOCKER", "message": "x"}, "not a dict"]
        )
        result = promotion_core.parse_decision(raw)
        assert len(result["findings"]) == 1


# ---------------------------------------------------------------------------
# bootstrap_decision
# ---------------------------------------------------------------------------

class TestBootstrapDecision:
    def test_no_champion_returns_approve(self):
        result = promotion_core.bootstrap_decision(champion_exists=False)
        assert result is not None
        assert result["decision"] == "APPROVE"

    def test_no_champion_justification_mentions_bootstrap(self):
        result = promotion_core.bootstrap_decision(champion_exists=False)
        justification = result["justification"].lower()
        assert "bootstrap" in justification or "first" in justification

    def test_no_champion_empty_findings(self):
        result = promotion_core.bootstrap_decision(champion_exists=False)
        assert result["findings"] == []

    def test_champion_exists_returns_none(self):
        result = promotion_core.bootstrap_decision(champion_exists=True)
        assert result is None

    def test_bootstrap_decision_contract(self):
        result = promotion_core.bootstrap_decision(champion_exists=False)
        assert set(result.keys()) >= {"decision", "findings", "justification"}


# ---------------------------------------------------------------------------
# compare_metrics
# ---------------------------------------------------------------------------

class TestCompareMetrics:
    def test_challenger_better_than_champion(self):
        result = promotion_core.compare_metrics(challenger_mae=8.0, champion_mae=9.0)
        assert result["better"] is True
        assert result["delta"] == pytest.approx(-1.0)
        assert result["pct_change"] < 0

    def test_challenger_worse_than_champion(self):
        result = promotion_core.compare_metrics(challenger_mae=10.0, champion_mae=9.0)
        assert result["better"] is False
        assert result["delta"] == pytest.approx(1.0)
        assert result["pct_change"] > 0

    def test_equal_mae_is_not_regression(self):
        result = promotion_core.compare_metrics(challenger_mae=9.0, champion_mae=9.0)
        assert result["better"] is True
        assert result["delta"] == pytest.approx(0.0)

    def test_summary_contains_both_maes(self):
        result = promotion_core.compare_metrics(challenger_mae=8.5, champion_mae=9.2)
        assert "8.5" in result["summary"] and "9.2" in result["summary"]

    def test_degradation_summary_mentions_blocker(self):
        result = promotion_core.compare_metrics(challenger_mae=15.0, champion_mae=9.0)
        assert "BLOCKER" in result["summary"] or "degraded" in result["summary"]

    def test_zero_champion_mae_no_division_error(self):
        result = promotion_core.compare_metrics(challenger_mae=0.0, champion_mae=0.0)
        assert result["better"] is True
        assert result["pct_change"] == 0.0
