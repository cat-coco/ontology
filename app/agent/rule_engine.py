from __future__ import annotations

from typing import Any

from app.models import RuleResult


class RuleEngine:
    """确定性规则引擎：阈值判断不交给LLM。"""

    def evaluate_rule(self, rule: dict[str, Any], runtime_state: dict[str, Any]) -> RuleResult:
        metrics = self._extract_metrics(runtime_state)
        actual = float(metrics.get(rule["metric"], 0.0))
        threshold = float(rule["threshold"])
        triggered = self._compare(actual, rule["operator"], threshold)
        return RuleResult(
            rule_id=rule["id"],
            name=rule["name"],
            metric=rule["metric"],
            actual_value=actual,
            operator=rule["operator"],
            threshold=threshold,
            triggered=triggered,
            trigger_action=rule["triggerAction"],
        )

    def evaluate_rules_by_ids(
        self,
        rule_ids: list[str],
        kg_response: dict[str, Any],
        runtime_state: dict[str, Any],
    ) -> list[RuleResult]:
        rules = {r["id"]: r for r in kg_response["data"]["rules"]}
        return [self.evaluate_rule(rules[rid], runtime_state) for rid in rule_ids if rid in rules]

    def is_evidence_complete(self, kg_response: dict[str, Any], runtime_state: dict[str, Any]) -> bool:
        requirements = [x for x in kg_response["data"].get("evidenceRequirements", []) if x.get("required")]
        evidence = runtime_state.get("facts", {}).get("evidence", [])
        matched_types = {x.get("type") for x in evidence if x.get("matched")}
        return all(req.get("type") in matched_types for req in requirements)

    def transition_condition_satisfied(
        self,
        transition: dict[str, Any],
        kg_response: dict[str, Any],
        runtime_state: dict[str, Any],
    ) -> bool:
        condition = transition.get("condition", {"type": "always"})
        kind = condition.get("type", "always")

        if kind == "always":
            return True
        if kind == "rule_triggered":
            rule_id = condition["ruleId"]
            expected = bool(condition.get("expected", True))
            result = self._find_rule_result(runtime_state, rule_id)
            return result is not None and bool(result["triggered"]) is expected
        if kind == "evidence_complete":
            expected = bool(condition.get("expected", True))
            return self.is_evidence_complete(kg_response, runtime_state) is expected
        return False

    @staticmethod
    def _find_rule_result(runtime_state: dict[str, Any], rule_id: str) -> dict[str, Any] | None:
        for result in runtime_state.get("rule_results", []):
            if result.get("rule_id") == rule_id:
                return result
        return None

    @staticmethod
    def _extract_metrics(runtime_state: dict[str, Any]) -> dict[str, float]:
        facts = runtime_state.get("facts", {})
        report_item = facts.get("reportItem") or {}
        contributors = facts.get("contributors") or []
        return {
            "changeRate": float(report_item.get("changeRate", 0.0) or 0.0),
            "majorContributorChangeRate": max(
                [float(x.get("changeRate", 0.0) or 0.0) for x in contributors] or [0.0]
            ),
        }

    @staticmethod
    def _compare(a: float, op: str, b: float) -> bool:
        return {
            ">": a > b,
            ">=": a >= b,
            "<": a < b,
            "<=": a <= b,
            "==": a == b,
            "!=": a != b,
        }.get(op, False)
