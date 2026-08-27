from typing import Any, Literal
from pydantic import BaseModel, Field


class AnalysisRequest(BaseModel):
    query: str = Field(..., examples=["请帮我分析0021G公司2026P06期间DCF0103的异常波动"])
    entity: str | None = None
    report_item: str | None = None
    period: str | None = None
    scenario: str = Field(
        default="government_subsidy_with_evidence",
        description="Demo数据场景：government_subsidy_with_evidence / low_fluctuation / high_overall_low_detail / high_fluctuation_no_evidence",
    )


class AnalysisIntent(BaseModel):
    entity: str = "0021G"
    report_item: str = "DCF0103"
    period: str = "2026P06"
    task_type: str = "fluctuation_reasonableness_analysis"
    scenario: str = "government_subsidy_with_evidence"


class RuleResult(BaseModel):
    rule_id: str
    name: str
    metric: str
    actual_value: float
    operator: str
    threshold: float
    triggered: bool
    trigger_action: str


class PlannerDecision(BaseModel):
    next_skill_id: str
    next_node_id: str
    rationale: str
    decision_basis: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    provider: str = "mock"
    guardrail_fallback: bool = False


class AgentStep(BaseModel):
    stage: str
    node_id: str | None = None
    skill_id: str | None = None
    title: str
    detail: str
    status: Literal["done", "info", "warning"] = "done"
    data: dict[str, Any] = Field(default_factory=dict)


class AgentAnalysisResponse(BaseModel):
    trace_id: str
    intent: AnalysisIntent
    ontology: dict[str, Any]
    kg_response: dict[str, Any]
    runtime_state: dict[str, Any]
    rule_results: list[RuleResult]
    planner_decisions: list[PlannerDecision]
    agent_steps: list[AgentStep]
    final_report: dict[str, Any]
    llm_provider: str
