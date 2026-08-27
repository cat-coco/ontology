from __future__ import annotations

from typing import Any, Callable

from app.gateways.fact_gateway import FactDataGateway
from app.gateways.llm_gateway import LlmGateway
from app.models import AnalysisIntent


class SkillRegistry:
    """把KG里的Skill ID映射到真实可执行能力；后续可替换成API/SQL/RAG/远程Skill。"""

    def __init__(self, fact_gateway: FactDataGateway, llm: LlmGateway):
        self.fact_gateway = fact_gateway
        self.llm = llm
        self._handlers: dict[str, Callable[..., dict[str, Any]]] = {
            "SKILL_FETCH_EFM": self._fetch_efm,
            "SKILL_FETCH_DETAIL": self._fetch_detail,
            "SKILL_RETRIEVE_EVIDENCE": self._retrieve_evidence,
            "SKILL_REQUEST_MANUAL_EVIDENCE": self._request_manual_evidence,
            "SKILL_GENERATE_CONCLUSION": self._generate_conclusion,
        }

    def execute(
        self,
        skill_id: str,
        *,
        intent: AnalysisIntent,
        runtime_state: dict[str, Any],
        kg_response: dict[str, Any],
        ontology_context: dict[str, Any],
        evidence_complete: bool,
        node_id: str,
    ) -> dict[str, Any]:
        if skill_id not in self._handlers:
            raise KeyError(f"未注册Skill: {skill_id}")
        return self._handlers[skill_id](
            intent=intent,
            runtime_state=runtime_state,
            kg_response=kg_response,
            ontology_context=ontology_context,
            evidence_complete=evidence_complete,
            node_id=node_id,
        )

    def _fetch_efm(self, **kwargs) -> dict[str, Any]:
        intent = kwargs["intent"]
        response = self.fact_gateway.query_report_item_summary(intent)
        item = response["data"]["reportItem"]
        return {
            "kind": "fact",
            "message": "已从EFM Mock接口获取报表项本期/上期事实。",
            "gateway_response": response,
            "fact_updates": response["data"],
            "reasoning_events": [
                {
                    "stage": "事实",
                    "statement": (
                        f"{item['code']}本期{item['currentAmount']:,.0f}，上期{item['previousAmount']:,.0f}，"
                        f"整体波动率{item['changeRate']*100:.1f}%。"
                    ),
                }
            ],
        }

    def _fetch_detail(self, **kwargs) -> dict[str, Any]:
        intent = kwargs["intent"]
        response = self.fact_gateway.query_detail_facts(intent)
        contributors = response["data"].get("contributors", [])
        top = contributors[0] if contributors else None
        reasoning_events = []
        if top:
            reasoning_events.append({
                "stage": "事实 · 明细",
                "statement": f"主要贡献实体{top['entityCode']}，明细波动率{top['changeRate']*100:.2f}%。",
            })
        return {
            "kind": "fact",
            "message": "已从数据工坊Mock接口获取贡献实体和明细数据。",
            "gateway_response": response,
            "fact_updates": response["data"],
            "reasoning_events": reasoning_events,
        }

    def _retrieve_evidence(self, **kwargs) -> dict[str, Any]:
        intent = kwargs["intent"]
        response = self.fact_gateway.query_business_evidence(intent)
        events = response["data"].get("businessEvents", [])
        evidence = response["data"].get("evidence", [])
        matched = [x for x in evidence if x.get("matched")]
        missing = [x for x in evidence if not x.get("matched")]
        reasoning_events = []
        if events:
            reasoning_events.append({
                "stage": "事理 · 原因",
                "statement": "识别业务事件：" + "、".join(x.get("name", "业务事件") for x in events),
            })
        reasoning_events.append({
            "stage": "事理 · 证据",
            "statement": f"证据匹配{len(matched)}/{len(evidence)}；" + (
                "关键证据完整。" if not missing else "缺失：" + "、".join(x.get("name", "证据") for x in missing)
            ),
        })
        return {
            "kind": "evidence",
            "message": "已查询业务事件、文件证据和ERP分录。",
            "gateway_response": response,
            "fact_updates": response["data"],
            "reasoning_events": reasoning_events,
        }

    def _request_manual_evidence(self, **kwargs) -> dict[str, Any]:
        runtime_state = kwargs["runtime_state"]
        kg_response = kwargs["kg_response"]
        evidence = runtime_state.get("facts", {}).get("evidence", [])
        matched_types = {x.get("type") for x in evidence if x.get("matched")}
        missing = [
            req for req in kg_response["data"].get("evidenceRequirements", [])
            if req.get("required") and req.get("type") not in matched_types
        ]
        request = {
            "status": "WAITING_HUMAN_EVIDENCE",
            "missingEvidence": missing,
            "instruction": "请业务人员补充缺失证据后重新执行或继续确认。",
        }
        return {
            "kind": "human_in_loop",
            "message": f"证据不完整，生成{len(missing)}项人工补证请求。",
            "fact_updates": {"manualEvidenceRequest": request},
            "manual_request": request,
            "reasoning_events": [
                {
                    "stage": "行动 · 人工补证",
                    "statement": "KG要求的证据不完整，已生成人工补证任务：" + "、".join(x.get("name", "证据") for x in missing),
                }
            ],
        }

    def _generate_conclusion(self, **kwargs) -> dict[str, Any]:
        runtime_state = kwargs["runtime_state"]
        # 结论Skill本身也属于实际执行路径。为了让LLM产出的审计字段包含当前Skill，
        # 构造一个只用于结论生成的状态快照；原始runtime_state仍由Orchestrator在执行成功后更新。
        state_for_report = {**runtime_state}
        state_for_report["executed_skills"] = [*runtime_state.get("executed_skills", []), "SKILL_GENERATE_CONCLUSION"]
        state_for_report["execution_history"] = [
            *runtime_state.get("execution_history", []),
            {
                "node_id": kwargs["node_id"],
                "skill_id": "SKILL_GENERATE_CONCLUSION",
                "skill_name": "可审计结论生成Skill",
                "result_kind": "final",
            },
        ]
        context = {
            "intent": kwargs["intent"].model_dump(),
            "ontology": kwargs["ontology_context"],
            "analysis_method": kwargs["kg_response"]["data"]["analysisMethod"],
            "workflow": kwargs["kg_response"]["data"]["workflowDefinition"],
            "evidence_requirements": kwargs["kg_response"]["data"].get("evidenceRequirements", []),
            "runtime_state": state_for_report,
            "evidence_complete": kwargs["evidence_complete"],
        }
        report = self.llm.reason(context)
        return {
            "kind": "final",
            "message": "已基于实际执行路径生成最终可审计结论。",
            "final_report": report,
            "fact_updates": {"finalReport": report},
        }
