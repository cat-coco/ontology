from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from typing import Any

from app.agent.planner_skill import DynamicPlannerSkill
from app.agent.rule_engine import RuleEngine
from app.agent.skill_registry import SkillRegistry
from app.config import settings
from app.gateways.fact_gateway import MockFactDataGateway
from app.gateways.kg_gateway import MockKnowledgeGraphGateway
from app.gateways.llm_gateway import create_llm_gateway
from app.models import (
    AgentAnalysisResponse,
    AgentStep,
    AnalysisIntent,
    AnalysisRequest,
    PlannerDecision,
    RuleResult,
)
from app.ontology.service import OntologyService


class FinancialReportAnomalyAgent:
    """
    v2.1 知识 + 数据双驱动动态 Agent Runtime。

    业务步骤不写死在 Python 中：
    - Ontology/KG 定义语义、规则、Skill、Workflow 和合法路径；
    - 关系库/业务接口返回实时事实；
    - 确定性 Rule Engine 将事实转成路径门控信号；
    - LLM Planner Skill 每轮在 KG 允许的候选路径中选择下一 Skill；
    - Runtime Guardrail 校验 Planner 选择是否满足 KG/规则约束。

    为了让前端清晰感知“为什么走这一步”，stream_events 会把 Planner 的输入、
    候选路径、规则门控、LLM 选择、Guardrail 和 Skill 执行分别作为 SSE 事件输出。
    """

    MAX_ITERATIONS = 12

    def __init__(self):
        self.ontology = OntologyService()
        self.kg = MockKnowledgeGraphGateway()
        self.fact = MockFactDataGateway()
        self.rule_engine = RuleEngine()
        self.llm = create_llm_gateway()
        self.planner = DynamicPlannerSkill(self.llm)
        self.skills = SkillRegistry(self.fact, self.llm)

    def analyze(self, request: AnalysisRequest) -> AgentAnalysisResponse:
        for event in self.stream_events(request):
            if event["event"] == "complete":
                return AgentAnalysisResponse.model_validate(event["data"])
        raise RuntimeError("Agent执行未产生complete事件")

    def stream_events(self, request: AnalysisRequest) -> Iterator[dict[str, Any]]:
        trace_id = str(uuid.uuid4())
        intent = self._extract_intent(request)
        ontology_context = self.ontology.get_report_item_context(intent.report_item)
        ontology_context["core_semantics"] = self.ontology.core_semantics()
        kg_response = self.kg.query_analysis_knowledge(intent)

        workflow = kg_response["data"]["workflowDefinition"]
        node_map = {n["id"]: n for n in workflow["nodes"]}
        skill_map = {s["id"]: s for s in kg_response["data"]["skills"]}

        runtime_state: dict[str, Any] = {
            "trace_id": trace_id,
            "current_node_id": None,
            "facts": {},
            "rule_results": [],
            "executed_skills": [],
            "execution_history": [],
            "planner_history": [],
            # 审计数据是Runtime的一等状态，而不是只存在于SSE前端。
            # 这样即使百炼未完整返回reasoning/evidence_chain，complete事件仍可追溯。
            "audit_reasoning": [],
            "evidence_chain": [],
        }
        steps: list[AgentStep] = []
        planner_decisions: list[PlannerDecision] = []
        final_report: dict[str, Any] = {}

        yield self._event("started", {
            "trace_id": trace_id,
            "intent": intent.model_dump(),
            "llm_provider": settings.llm_provider,
            "architecture": "Ontology/KG + Fact Data + Rule Gate + LLM Planner Skill + Runtime Guardrail",
            "ui_event_delay_ms": settings.ui_event_delay_ms,
        })
        yield self._event("knowledge", {
            "ontology": ontology_context,
            "kg": kg_response,
            "planner_skill": kg_response["data"]["plannerSkill"],
            "analysis_method": kg_response["data"]["analysisMethod"],
            "workflow": workflow,
            "message": "领域知识已加载：Ontology定义语义，KG定义规则/Skill/执行图，Planner Skill描述专家分析策略。",
        })
        yield self._event("kg", kg_response)

        for iteration in range(1, self.MAX_ITERATIONS + 1):
            # 1) Runtime 根据 KG + 当前规则/事实计算本轮候选路径。
            candidates = self._candidate_transitions(
                current_node_id=runtime_state["current_node_id"],
                kg_response=kg_response,
                runtime_state=runtime_state,
            )
            candidate_views = [
                self._candidate_audit_view(c, node_map, skill_map, kg_response, runtime_state)
                for c in candidates
            ]
            valid_candidates = [x for x in candidates if x["conditionSatisfied"]]
            if not valid_candidates:
                raise RuntimeError(
                    f"当前节点{runtime_state['current_node_id']}没有满足条件的后继路径；请检查KG Workflow和规则数据。"
                )

            # 前端先看到 Planner 本轮“拿到了什么知识、什么数据”。
            yield self._event("planner_round", {
                "iteration": iteration,
                "phase": "start",
                "current_node_id": runtime_state["current_node_id"],
                "runtime": self._runtime_snapshot(runtime_state),
                "knowledge_signals": {
                    "analysis_method": kg_response["data"]["analysisMethod"],
                    "planner_skill": kg_response["data"]["plannerSkill"],
                    "rules": kg_response["data"]["rules"],
                },
                "data_signals": self._data_signals(runtime_state),
                "message": f"Planner Round {iteration}：读取领域知识和最新运行数据，准备规划下一步。",
            })
            yield self._event("planner_candidates", {
                "iteration": iteration,
                "candidates": candidate_views,
                "valid_count": len(valid_candidates),
                "message": "KG给出可行路径，Rule Engine / Evidence Gate 将当前数据转换为路径门控结果。",
            })
            yield self._event("planner_call", {
                "iteration": iteration,
                "status": "running",
                "provider": settings.llm_provider,
                "model": settings.bailian_model if settings.llm_provider == "bailian" else "mock-llm-planner",
                "planner_skill": kg_response["data"]["plannerSkill"],
                "message": "调用 LLM Planner Skill：在满足KG约束的候选路径中选择下一Skill。",
            })

            # 2) LLM Planner Skill 选择下一 Skill。这里是同步调用，但 planner_call 已先通过 SSE 发给前端。
            raw_decision = self.planner.plan_next(
                intent=intent.model_dump(),
                ontology_context=ontology_context,
                kg_response=kg_response,
                runtime_state=runtime_state,
                candidate_transitions=candidates,
            )
            decision = self._guardrail_planner_decision(
                decision=raw_decision,
                valid_candidates=valid_candidates,
                node_map=node_map,
                skill_map=skill_map,
            )
            planner_decisions.append(decision)
            runtime_state["planner_history"].append(decision.model_dump())

            yield self._event("planner", {
                **decision.model_dump(),
                "iteration": iteration,
                "raw_decision": raw_decision.model_dump(),
                "candidate_transitions": candidate_views,
                "message": "Planner Skill已结合KG路径约束、规则门控和当前事实选择下一Skill。",
            })
            yield self._event("guardrail", {
                "iteration": iteration,
                "accepted": not decision.guardrail_fallback,
                "guardrail_fallback": decision.guardrail_fallback,
                "selected_node_id": decision.next_node_id,
                "selected_skill_id": decision.next_skill_id,
                "message": (
                    "Runtime Guardrail校验通过：Planner选择满足KG与规则约束。"
                    if not decision.guardrail_fallback
                    else "Runtime Guardrail拒绝原始选择并回退到KG合法路径。"
                ),
            })

            # 3) 执行选中的 Skill。Step 序号只是本次运行的动态执行序号，不是固定业务流程编号。
            node = node_map[decision.next_node_id]
            skill = skill_map[decision.next_skill_id]
            running_step = AgentStep(
                stage=str(iteration),
                node_id=node["id"],
                skill_id=skill["id"],
                title=skill["name"],
                detail=f"动态规划选择：{decision.rationale}",
                status="info",
                data={
                    "planner_decision": decision.model_dump(),
                    "node": node,
                    "skill": skill,
                },
            )
            yield self._event("step", running_step.model_dump())
            yield self._event("skill_call", {
                "iteration": iteration,
                "status": "running",
                "node": node,
                "skill": skill,
                "message": f"执行 {skill['name']}；所需数据只在当前路径真正需要时获取。",
            })

            evidence_complete_before = self.rule_engine.is_evidence_complete(kg_response, runtime_state)
            skill_result = self.skills.execute(
                skill["id"],
                intent=intent,
                runtime_state=runtime_state,
                kg_response=kg_response,
                ontology_context=ontology_context,
                evidence_complete=evidence_complete_before,
                node_id=node["id"],
            )

            fact_updates = skill_result.get("fact_updates", {})
            if fact_updates:
                runtime_state["facts"].update(fact_updates)
                # 证据链同步沉淀到AgentState，避免最终审计结果只依赖LLM返回。
                if isinstance(fact_updates.get("evidence"), list):
                    runtime_state["evidence_chain"] = self._merge_evidence_chain(
                        runtime_state.get("evidence_chain", []),
                        fact_updates.get("evidence", []),
                    )

            runtime_state["current_node_id"] = node["id"]
            runtime_state["executed_skills"].append(skill["id"])
            runtime_state["execution_history"].append({
                "iteration": iteration,
                "node_id": node["id"],
                "skill_id": skill["id"],
                "skill_name": skill["name"],
                "result_kind": skill_result.get("kind"),
            })

            if skill_result.get("gateway_response"):
                event_name = "evidence" if skill_result.get("kind") == "evidence" else "fact"
                yield self._event(event_name, skill_result["gateway_response"])

            # 4) 数据返回后，确定性规则引擎计算新的路径门控信号。
            new_rule_results = self.rule_engine.evaluate_rules_by_ids(
                node.get("evaluateRulesAfter", []),
                kg_response,
                runtime_state,
            )
            if new_rule_results:
                self._upsert_rule_results(runtime_state, new_rule_results)
                yield self._event("rule_results", [r.model_dump() for r in new_rule_results])
                for rr in new_rule_results:
                    reasoning_event = {
                        "stage": "事理 · 规则",
                        "statement": (
                            f"{rr.name}：实际值 {rr.actual_value:.4f} {rr.operator} 阈值 {rr.threshold:.4f}，"
                            f"triggered={rr.triggered}；该结果会改变下一轮Planner的可行路径。"
                        ),
                        "rule": rr.model_dump(),
                        "source": "RuleEngine",
                    }
                    self._append_audit_reasoning(runtime_state, reasoning_event)
                    yield self._event("reasoning", reasoning_event)

            for reasoning_event in skill_result.get("reasoning_events", []):
                normalized_reasoning = {**reasoning_event}
                normalized_reasoning.setdefault("source", skill["id"])
                self._append_audit_reasoning(runtime_state, normalized_reasoning)
                yield self._event("reasoning", normalized_reasoning)

            yield self._event("state_update", {
                "iteration": iteration,
                "runtime": self._runtime_snapshot(runtime_state),
                "data_signals": self._data_signals(runtime_state),
                "rule_results": runtime_state["rule_results"],
                "message": "Skill执行结果已写回运行状态；最新事实与规则结果将作为下一轮Planner输入。",
            })

            done_step = AgentStep(
                stage=str(iteration),
                node_id=node["id"],
                skill_id=skill["id"],
                title=skill["name"],
                detail=skill_result.get("message", "Skill执行完成。"),
                status="warning" if skill_result.get("kind") == "human_in_loop" else "done",
                data={
                    "planner_decision": decision.model_dump(),
                    "node": node,
                    "skill": skill,
                    "result_kind": skill_result.get("kind"),
                    "gateway_response": skill_result.get("gateway_response"),
                    "manual_request": skill_result.get("manual_request"),
                },
            )
            steps.append(done_step)
            yield self._event("skill_call", {
                "iteration": iteration,
                "status": "done",
                "node": node,
                "skill": skill,
                "result_kind": skill_result.get("kind"),
                "message": skill_result.get("message", "Skill执行完成。"),
            })
            yield self._event("step", done_step.model_dump())

            if skill_result.get("kind") == "final":
                final_report = self._enrich_final_report(
                    skill_result["final_report"],
                    runtime_state=runtime_state,
                )
                runtime_state["facts"]["finalReport"] = final_report
                action = final_report.get("action")
                if action:
                    yield self._event("reasoning", {
                        "stage": "行动",
                        "statement": self._display_text(action),
                        "raw": action,
                    })
                break
        else:
            raise RuntimeError(f"Agent超过最大动态规划轮次{self.MAX_ITERATIONS}，可能存在Workflow环路。")

        response = AgentAnalysisResponse(
            trace_id=trace_id,
            intent=intent,
            ontology=ontology_context,
            kg_response=kg_response,
            runtime_state=runtime_state,
            rule_results=[RuleResult.model_validate(x) for x in runtime_state["rule_results"]],
            planner_decisions=planner_decisions,
            agent_steps=steps,
            final_report=final_report,
            llm_provider=settings.llm_provider,
        )
        yield self._event("complete", response.model_dump(mode="json"))


    @staticmethod
    def _append_audit_reasoning(runtime_state: dict[str, Any], item: dict[str, Any]) -> None:
        """把可展示的审计依据写入Runtime State，并按stage+statement去重。"""
        if not isinstance(item, dict):
            return
        statement = str(item.get("statement") or item.get("description") or "").strip()
        if not statement:
            return
        normalized = {**item, "statement": statement}
        items = runtime_state.setdefault("audit_reasoning", [])
        key = (str(normalized.get("stage", "")), statement)
        if any((str(x.get("stage", "")), str(x.get("statement", ""))) == key for x in items if isinstance(x, dict)):
            return
        items.append(normalized)

    @staticmethod
    def _merge_evidence_chain(existing: list[Any], incoming: list[Any]) -> list[dict[str, Any]]:
        """合并证据并按evidenceId/reference/name去重，保留完整Mock/真实接口字段。"""
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in [*(existing or []), *(incoming or [])]:
            if not isinstance(raw, dict):
                continue
            key = str(
                raw.get("evidenceId")
                or raw.get("id")
                or raw.get("reference")
                or raw.get("name")
                or raw
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(dict(raw))
        return merged

    def _enrich_final_report(
        self,
        report: dict[str, Any] | None,
        *,
        runtime_state: dict[str, Any],
    ) -> dict[str, Any]:
        """
        最终审计结果不能依赖LLM是否严格返回全部字段。
        将LLM输出与Runtime已经验证过的Fact/Reasoning/Evidence进行合并，
        保证complete事件始终包含可追溯数据。
        """
        result = dict(report or {})
        facts = runtime_state.get("facts", {})

        # 1) reasoning：兼容百炼可能返回空数组、camelCase或缺字段。
        llm_reasoning = result.get("reasoning")
        if not isinstance(llm_reasoning, list):
            llm_reasoning = result.get("reasoning_chain") or result.get("reasoningChain") or []
        runtime_reasoning = runtime_state.get("audit_reasoning", [])
        merged_reasoning: list[dict[str, Any]] = []
        seen_reason: set[tuple[str, str]] = set()
        for raw in [*(runtime_reasoning or []), *(llm_reasoning or [])]:
            if isinstance(raw, str):
                item = {"stage": "Reasoning", "statement": raw}
            elif isinstance(raw, dict):
                item = dict(raw)
                item["statement"] = str(item.get("statement") or item.get("description") or "").strip()
            else:
                continue
            if not item.get("statement"):
                continue
            key = (str(item.get("stage", "")), item["statement"])
            if key in seen_reason:
                continue
            seen_reason.add(key)
            merged_reasoning.append(item)
        result["reasoning"] = merged_reasoning

        # 2) evidence_chain：LLM为空时使用Runtime事实；LLM有值时合并而不是覆盖。
        llm_evidence = result.get("evidence_chain")
        if not isinstance(llm_evidence, list):
            llm_evidence = result.get("evidenceChain") or []
        runtime_evidence = runtime_state.get("evidence_chain", [])
        fact_evidence = facts.get("evidence", []) if isinstance(facts.get("evidence", []), list) else []
        result["evidence_chain"] = self._merge_evidence_chain(
            self._merge_evidence_chain(runtime_evidence, fact_evidence),
            llm_evidence,
        )

        # 3) fact：若模型未返回，则从Runtime事实稳定构造。
        if not isinstance(result.get("fact"), dict) or not result.get("fact"):
            item = facts.get("reportItem") or {}
            contributors = facts.get("contributors") or []
            top = contributors[0] if contributors else {}
            result["fact"] = {
                "currentAmount": item.get("currentAmount"),
                "previousAmount": item.get("previousAmount"),
                "changeRate": item.get("changeRate"),
                "majorContributor": top.get("entityCode"),
                "majorContributorChangeRate": top.get("changeRate"),
            }

        result.setdefault("audit_meta", {})
        result["audit_meta"].update({
            "reasoning_source": "Runtime State + LLM",
            "evidence_source": "Fact Gateway / RAG / ERP + LLM",
            "reasoning_count": len(result["reasoning"]),
            "evidence_count": len(result["evidence_chain"]),
        })
        return result

    def _candidate_transitions(
        self,
        *,
        current_node_id: str | None,
        kg_response: dict[str, Any],
        runtime_state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        workflow = kg_response["data"]["workflowDefinition"]
        if current_node_id is None:
            return [{
                "id": "ENTRY",
                "from": None,
                "to": workflow["entryNodeId"],
                "condition": {"type": "always"},
                "conditionSatisfied": True,
                "businessMeaning": "进入KG定义的分析方法入口节点。",
            }]

        outgoing = [x for x in workflow["transitions"] if x["from"] == current_node_id]
        return [
            {
                **t,
                "conditionSatisfied": self.rule_engine.transition_condition_satisfied(
                    t, kg_response, runtime_state
                ),
            }
            for t in outgoing
        ]

    def _candidate_audit_view(
        self,
        transition: dict[str, Any],
        node_map: dict[str, Any],
        skill_map: dict[str, Any],
        kg_response: dict[str, Any],
        runtime_state: dict[str, Any],
    ) -> dict[str, Any]:
        node = node_map[transition["to"]]
        skill = skill_map[node["skillId"]]
        condition = transition.get("condition") or {"type": "always"}
        explain = self._condition_explain(condition, kg_response, runtime_state)
        return {
            **transition,
            "targetNode": node,
            "targetSkill": skill,
            "conditionExplain": explain,
            "signalSource": self._condition_signal_source(condition),
        }

    def _condition_explain(
        self,
        condition: dict[str, Any],
        kg_response: dict[str, Any],
        runtime_state: dict[str, Any],
    ) -> str:
        kind = condition.get("type", "always")
        if kind == "always":
            return "KG定义为无条件可达路径。"
        if kind == "rule_triggered":
            rule_id = condition.get("ruleId")
            expected = condition.get("expected")
            rr = next((x for x in runtime_state.get("rule_results", []) if x.get("rule_id") == rule_id), None)
            rule = next((x for x in kg_response["data"].get("rules", []) if x.get("id") == rule_id), None)
            rule_name = (rule or {}).get("name", rule_id)
            if not rr:
                return f"等待规则 {rule_name} 产生结果；期望 triggered={expected}。"
            return (
                f"{rule_name}：actual={rr['actual_value']:.4f} {rr['operator']} threshold={rr['threshold']:.4f}，"
                f"实际 triggered={rr['triggered']}；该路径期望={expected}。"
            )
        if kind == "evidence_complete":
            expected = condition.get("expected")
            evidence = runtime_state.get("facts", {}).get("evidence", [])
            matched = sum(1 for x in evidence if x.get("matched"))
            required = len(kg_response["data"].get("evidenceRequirements", []))
            complete = self.rule_engine.is_evidence_complete(kg_response, runtime_state)
            return f"证据完整性={complete}，已匹配 {matched}/{required} 类必需证据；该路径期望={expected}。"
        return f"条件类型={kind}。"

    @staticmethod
    def _condition_signal_source(condition: dict[str, Any]) -> str:
        kind = condition.get("type", "always")
        if kind == "rule_triggered":
            return "KG规则 + 关系库事实"
        if kind == "evidence_complete":
            return "KG证据要求 + RAG/ERP事实"
        return "KG执行图"

    @staticmethod
    def _guardrail_planner_decision(
        *,
        decision: PlannerDecision,
        valid_candidates: list[dict[str, Any]],
        node_map: dict[str, Any],
        skill_map: dict[str, Any],
    ) -> PlannerDecision:
        valid_by_node = {x["to"]: x for x in valid_candidates}
        selected = valid_by_node.get(decision.next_node_id)
        if selected:
            expected_skill = node_map[decision.next_node_id]["skillId"]
            if decision.next_skill_id == expected_skill:
                return decision

        fallback = valid_candidates[0]
        node = node_map[fallback["to"]]
        skill = skill_map[node["skillId"]]
        return PlannerDecision(
            next_skill_id=skill["id"],
            next_node_id=node["id"],
            rationale=(
                f"Runtime Guardrail拒绝了Planner的非法/不满足条件选择，按KG合法transition回退到{skill['name']}。"
            ),
            decision_basis=[fallback.get("businessMeaning", "KG合法后继路径")],
            confidence=1.0,
            provider=decision.provider,
            guardrail_fallback=True,
        )

    @staticmethod
    def _runtime_snapshot(runtime_state: dict[str, Any]) -> dict[str, Any]:
        facts = runtime_state.get("facts", {})
        return {
            "current_node_id": runtime_state.get("current_node_id"),
            "executed_skills": list(runtime_state.get("executed_skills", [])),
            "available_fact_keys": sorted(facts.keys()),
            "rule_results": list(runtime_state.get("rule_results", [])),
            "execution_count": len(runtime_state.get("execution_history", [])),
        }

    @staticmethod
    def _data_signals(runtime_state: dict[str, Any]) -> dict[str, Any]:
        facts = runtime_state.get("facts", {})
        item = facts.get("reportItem") or {}
        contributors = facts.get("contributors") or []
        evidence = facts.get("evidence") or []
        return {
            "report_item": {
                "code": item.get("code"),
                "currentAmount": item.get("currentAmount"),
                "previousAmount": item.get("previousAmount"),
                "changeRate": item.get("changeRate"),
            } if item else None,
            "top_contributor": contributors[0] if contributors else None,
            "business_events": facts.get("businessEvents", []),
            "evidence_summary": {
                "total": len(evidence),
                "matched": sum(1 for x in evidence if x.get("matched")),
                "items": evidence,
            } if evidence else None,
        }

    @staticmethod
    def _upsert_rule_results(runtime_state: dict[str, Any], results: list[RuleResult]) -> None:
        by_id = {x["rule_id"]: x for x in runtime_state.get("rule_results", [])}
        for result in results:
            by_id[result.rule_id] = result.model_dump()
        runtime_state["rule_results"] = list(by_id.values())

    def _extract_intent(self, request: AnalysisRequest) -> AnalysisIntent:
        text = request.query.upper()
        entity = request.entity or self._first(r"\b\d{4}G\b", text) or "0021G"
        report_item = request.report_item or self._first(r"\bDCF\d{4}\b", text) or "DCF0103"
        period = request.period or self._first(r"\b20\d{2}P\d{2}\b", text) or "2026P06"
        return AnalysisIntent(
            entity=entity,
            report_item=report_item,
            period=period,
            scenario=request.scenario,
        )

    @staticmethod
    def _first(pattern: str, text: str):
        match = re.search(pattern, text)
        return match.group(0) if match else None

    @staticmethod
    def _display_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (str, int, float, bool)):
            return str(value)
        if isinstance(value, list):
            return "；".join(
                x for x in (FinancialReportAnomalyAgent._display_text(v) for v in value) if x
            )
        if isinstance(value, dict):
            title = value.get("title") or value.get("name") or value.get("action")
            detail = value.get("description") or value.get("statement") or value.get("detail") or value.get("content")
            if title and detail and str(title) != str(detail):
                return f"{title}：{detail}"
            if detail:
                return str(detail)
            if title:
                return str(title)
            return "；".join(f"{k}={FinancialReportAnomalyAgent._display_text(v)}" for k, v in value.items())
        return str(value)

    @staticmethod
    def _event(event: str, data: Any) -> dict[str, Any]:
        return {"event": event, "data": data}
