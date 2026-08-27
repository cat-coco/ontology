from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from app.config import settings
from app.agent.prompts import PLANNER_SYSTEM_PROMPT, ANALYST_SYSTEM_PROMPT
from app.models import PlannerDecision


class LlmGateway(ABC):
    @abstractmethod
    def plan_next(self, context: dict[str, Any]) -> PlannerDecision:
        raise NotImplementedError

    @abstractmethod
    def reason(self, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class MockLlmGateway(LlmGateway):
    """离线演示：使用同一Planner输出协议，模拟LLM严格遵循Planner Skill。"""

    def plan_next(self, context: dict[str, Any]) -> PlannerDecision:
        candidates = context["candidate_transitions"]
        valid = [x for x in candidates if x.get("conditionSatisfied")]
        if not valid:
            raise RuntimeError("Planner没有可执行的合法transition")

        chosen = valid[0]
        basis = []
        cond = chosen.get("condition") or {"type": "always"}
        if cond.get("type") == "rule_triggered":
            rid = cond.get("ruleId")
            rr = next((x for x in context["runtime_state"].get("rule_results", []) if x.get("rule_id") == rid), None)
            if rr:
                basis.append(
                    f"规则{rr['name']}：actual={rr['actual_value']:.4f} {rr['operator']} threshold={rr['threshold']:.4f}，triggered={rr['triggered']}"
                )
        elif cond.get("type") == "evidence_complete":
            evidence = context["runtime_state"].get("evidence", [])
            matched = sum(1 for x in evidence if x.get("matched"))
            basis.append(f"证据完整性判断：当前匹配{matched}/{len(evidence)}项证据")
        else:
            basis.append("KG工作流定义该路径为无条件后继")

        if chosen.get("businessMeaning"):
            basis.append(chosen["businessMeaning"])

        return PlannerDecision(
            next_skill_id=chosen["targetSkill"]["id"],
            next_node_id=chosen["targetNode"]["id"],
            rationale=f"根据KG执行图和当前运行状态，选择：{chosen['targetSkill']['name']}。",
            decision_basis=basis,
            confidence=0.99,
            provider="mock-llm-planner",
        )

    def reason(self, context: dict[str, Any]) -> dict[str, Any]:
        state = context["runtime_state"]
        facts = state.get("facts", {})
        main = facts.get("reportItem", {})
        contributors = facts.get("contributors", [])
        top = contributors[0] if contributors else None
        evidence = facts.get("evidence", [])
        rule_results = state.get("rule_results", [])
        executed = state.get("executed_skills", [])
        evidence_complete = bool(context.get("evidence_complete"))

        overall = next((x for x in rule_results if x.get("rule_id") == "RULE_DCF0103_OVERALL_20"), None)
        detail = next((x for x in rule_results if x.get("rule_id") == "RULE_DCF0103_DETAIL_50"), None)

        reasoning = []
        if main:
            reasoning.append({
                "stage": "事实",
                "statement": f"{main.get('code')}本期{main.get('currentAmount', 0):,.0f}，上期{main.get('previousAmount', 0):,.0f}，整体波动率{main.get('changeRate', 0)*100:.1f}%。",
            })
        if overall:
            reasoning.append({
                "stage": "事理-规则",
                "statement": f"整体波动规则triggered={overall['triggered']}，Runtime据此决定是否进入明细下钻。",
            })
        if detail:
            reasoning.append({
                "stage": "事理-明细",
                "statement": f"主要贡献明细规则triggered={detail['triggered']}，Runtime据此决定是否进入业务事件与证据验证。",
            })

        if not overall or not overall.get("triggered"):
            conclusion = "本期波动未达到知识图谱定义的异常分析阈值，Agent动态提前结束深度下钻，未发现需要进一步处置的显著异常。"
            actions = [
                {"title": "持续监控", "description": "按既定阈值持续监控后续期间波动。"},
            ]
        elif detail and not detail.get("triggered"):
            conclusion = "整体波动达到分析阈值，但明细层未识别出超过阈值的主要贡献实体，当前未形成需要进一步证据追溯的集中异常。"
            actions = [
                {"title": "保留分析记录", "description": "保留整体及明细分析结果，后续期间继续观察。"},
            ]
        elif evidence_complete:
            events = facts.get("businessEvents", [])
            event_name = events[0].get("name") if events else "已识别业务事件"
            reasoning.extend([
                {"stage": "事理-原因", "statement": f"主要波动与业务事件“{event_name}”方向及金额关系一致。"},
                {"stage": "证据", "statement": "KG要求的关键证据均已匹配，业务事件、文件证据与会计分录相互印证。"},
            ])
            conclusion = "本次DCF0103异常波动具有明确业务事件和完整证据链支撑，判断为合理波动。"
            actions = [
                {"title": "无需异常修复", "description": "当前无需修改报表数据或重新入账。"},
                {"title": "证据归档", "description": "归档补贴批复与到账会计分录，保留审计链路。"},
                {"title": "持续监控", "description": "后续期间继续监控该报表项波动。"},
            ]
        else:
            missing = [x.get("name") for x in evidence if not x.get("matched")]
            reasoning.extend([
                {"stage": "事理-原因", "statement": "已识别可能解释波动的业务事件，但证据链尚未满足KG定义的完整性要求。"},
                {"stage": "证据缺口", "statement": "缺失证据：" + ("、".join(missing) if missing else "关键证明材料")},
            ])
            conclusion = "当前存在可解释的业务事件线索，但关键证据不足，暂不能确认该异常波动为合理，需人工补证后再确认。"
            actions = [
                {"title": "人工补证", "description": "补充缺失的政府补助/项目批复等关键材料。"},
                {"title": "暂缓确认", "description": "证据补齐前保持待确认状态，不自动判定为合理波动。"},
            ]

        fact_obj = {
            "currentAmount": main.get("currentAmount"),
            "previousAmount": main.get("previousAmount"),
            "changeRate": main.get("changeRate"),
            "majorContributor": top.get("entityCode") if top else None,
            "majorContributorChangeRate": top.get("changeRate") if top else None,
        }

        return {
            "summary": conclusion,
            "fact": fact_obj,
            "reasoning": reasoning,
            "evidence_chain": evidence,
            "conclusion": conclusion,
            "action": actions,
            "used_skills": executed,
            "executed_path": [x.get("node_id") for x in state.get("execution_history", [])],
            "mode": "mock-llm",
        }


class BailianLlmGateway(LlmGateway):
    """阿里云百炼 OpenAI Compatible Chat Completions。"""

    def __init__(self):
        if not settings.bailian_api_key:
            raise RuntimeError("LLM_PROVIDER=bailian 时必须配置 BAILIAN_API_KEY")
        from openai import OpenAI

        self.client = OpenAI(
            api_key=settings.bailian_api_key,
            base_url=settings.bailian_base_url,
        )

    def _json_completion(self, system_prompt: str, user_payload: dict[str, Any], temperature: float = 0.0) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=settings.bailian_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"raw": content}

    def plan_next(self, context: dict[str, Any]) -> PlannerDecision:
        result = self._json_completion(
            PLANNER_SYSTEM_PROMPT,
            {"instruction": "读取Planner Skill和候选路径，选择下一Skill，仅输出约定JSON。", **context},
            temperature=0.0,
        )
        return PlannerDecision(
            next_skill_id=str(result.get("next_skill_id", "")),
            next_node_id=str(result.get("next_node_id", "")),
            rationale=str(result.get("rationale", "模型未提供规划理由")),
            decision_basis=[str(x) for x in result.get("decision_basis", [])],
            confidence=float(result.get("confidence", 0.8)),
            provider=f"bailian:{settings.bailian_model}",
        )

    def reason(self, context: dict[str, Any]) -> dict[str, Any]:
        result = self._json_completion(
            ANALYST_SYSTEM_PROMPT,
            {"instruction": "基于实际执行路径生成事实-事理-行动可审计结论。", **context},
            temperature=0.1,
        )
        result["model"] = settings.bailian_model
        result["mode"] = "bailian"
        return result


def create_llm_gateway() -> LlmGateway:
    if settings.llm_provider == "bailian":
        return BailianLlmGateway()
    return MockLlmGateway()
