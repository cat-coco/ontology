from __future__ import annotations

from pathlib import Path
from typing import Any

from app.gateways.llm_gateway import LlmGateway
from app.models import PlannerDecision


class DynamicPlannerSkill:
    """
    场景级Planner Skill执行器。

    关键点：Planner Skill本身也由KG返回metadata；本地Demo根据KG返回的resource加载Skill文档。
    未来KG可以直接返回Skill正文/版本/URI，或者从Skill Registry远程拉取。
    """

    def __init__(self, llm: LlmGateway):
        self.llm = llm
        self.project_root = Path(__file__).resolve().parents[2]
        self._cache: dict[str, str] = {}

    def plan_next(
        self,
        *,
        intent: dict[str, Any],
        ontology_context: dict[str, Any],
        kg_response: dict[str, Any],
        runtime_state: dict[str, Any],
        candidate_transitions: list[dict[str, Any]],
    ) -> PlannerDecision:
        workflow = kg_response["data"]["workflowDefinition"]
        nodes = {n["id"]: n for n in workflow["nodes"]}
        skills = {s["id"]: s for s in kg_response["data"]["skills"]}
        planner_meta = kg_response["data"]["plannerSkill"]
        skill_text = self._load_skill(planner_meta)

        candidates = []
        for transition in candidate_transitions:
            node = nodes[transition["to"]]
            skill = skills[node["skillId"]]
            candidates.append({
                **transition,
                "targetNode": node,
                "targetSkill": skill,
            })

        context = {
            "planner_skill_metadata": planner_meta,
            "planner_skill": skill_text,
            "intent": intent,
            "ontology_summary": {
                "report_item": ontology_context.get("report_item"),
                "relations": ontology_context.get("relations", []),
            },
            "analysis_method": kg_response["data"]["analysisMethod"],
            "rules": kg_response["data"]["rules"],
            "evidence_requirements": kg_response["data"].get("evidenceRequirements", []),
            "runtime_state": self._planner_state(runtime_state),
            "candidate_transitions": candidates,
        }
        return self.llm.plan_next(context)

    def _load_skill(self, planner_meta: dict[str, Any]) -> str:
        resource = planner_meta.get("resource")
        if not resource:
            raise RuntimeError("KG返回的plannerSkill缺少resource")
        if resource in self._cache:
            return self._cache[resource]
        path = self.project_root / resource
        if not path.exists():
            raise FileNotFoundError(f"KG声明的Planner Skill资源不存在: {path}")
        text = path.read_text(encoding="utf-8")
        self._cache[resource] = text
        return text

    @staticmethod
    def _planner_state(state: dict[str, Any]) -> dict[str, Any]:
        facts = state.get("facts", {})
        return {
            "current_node_id": state.get("current_node_id"),
            "executed_skills": state.get("executed_skills", []),
            "available_fact_keys": sorted(facts.keys()),
            "reportItem": facts.get("reportItem"),
            "contributors": facts.get("contributors", [])[:3],
            "businessEvents": facts.get("businessEvents", []),
            "evidence": facts.get("evidence", []),
            "rule_results": state.get("rule_results", []),
            "manualEvidenceRequest": facts.get("manualEvidenceRequest"),
        }
