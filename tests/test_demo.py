from pathlib import Path

from app.agent.orchestrator import FinancialReportAnomalyAgent
from app.models import AnalysisRequest


def run_scenario(scenario: str):
    agent = FinancialReportAnomalyAgent()
    return agent.analyze(
        AnalysisRequest(
            query="分析0021G 2026P06 DCF0103异常波动",
            scenario=scenario,
        )
    )


def test_default_dynamic_path_with_evidence():
    out = run_scenario("government_subsidy_with_evidence")
    assert out.intent.entity == "0021G"
    assert out.ontology["found"] is True
    assert out.runtime_state["executed_skills"] == [
        "SKILL_FETCH_EFM",
        "SKILL_FETCH_DETAIL",
        "SKILL_RETRIEVE_EVIDENCE",
        "SKILL_GENERATE_CONCLUSION",
    ]
    assert len(out.planner_decisions) == 4
    assert all(x.triggered for x in out.rule_results)
    assert "合理波动" in out.final_report["conclusion"]


def test_low_fluctuation_exits_early():
    out = run_scenario("low_fluctuation")
    assert out.runtime_state["executed_skills"] == [
        "SKILL_FETCH_EFM",
        "SKILL_GENERATE_CONCLUSION",
    ]
    assert len(out.rule_results) == 1
    assert out.rule_results[0].triggered is False
    assert "提前结束" in out.final_report["conclusion"]


def test_high_overall_low_detail_skips_evidence():
    out = run_scenario("high_overall_low_detail")
    assert out.runtime_state["executed_skills"] == [
        "SKILL_FETCH_EFM",
        "SKILL_FETCH_DETAIL",
        "SKILL_GENERATE_CONCLUSION",
    ]
    by_id = {x.rule_id: x for x in out.rule_results}
    assert by_id["RULE_DCF0103_OVERALL_20"].triggered is True
    assert by_id["RULE_DCF0103_DETAIL_50"].triggered is False
    assert "SKILL_RETRIEVE_EVIDENCE" not in out.runtime_state["executed_skills"]


def test_missing_evidence_enters_human_in_loop():
    out = run_scenario("high_fluctuation_no_evidence")
    assert out.runtime_state["executed_skills"] == [
        "SKILL_FETCH_EFM",
        "SKILL_FETCH_DETAIL",
        "SKILL_RETRIEVE_EVIDENCE",
        "SKILL_REQUEST_MANUAL_EVIDENCE",
        "SKILL_GENERATE_CONCLUSION",
    ]
    assert "人工补证" in str(out.final_report["action"])
    assert "暂不能确认" in out.final_report["conclusion"]


def test_stream_exposes_full_planner_lifecycle():
    agent = FinancialReportAnomalyAgent()
    events = list(agent.stream_events(AnalysisRequest(
        query="分析0021G 2026P06 DCF0103异常波动",
        scenario="low_fluctuation",
    )))
    names = [x["event"] for x in events]
    assert names[0] == "started"
    assert "knowledge" in names
    assert names.count("planner_round") == 2
    assert names.count("planner_candidates") == 2
    assert names.count("planner_call") == 2
    assert names.count("planner") == 2
    assert names.count("guardrail") == 2
    assert names.count("state_update") == 2
    assert names.count("step") == 4  # 每个Skill先RUNNING，再DONE
    assert names[-1] == "complete"

    # 第一次Planner Round必须先展示候选路径与LLM调用状态，再输出决策。
    i_round = names.index("planner_round")
    i_candidates = names.index("planner_candidates")
    i_call = names.index("planner_call")
    i_decision = names.index("planner")
    i_guard = names.index("guardrail")
    assert i_round < i_candidates < i_call < i_decision < i_guard


def test_candidate_events_show_allowed_and_blocked_paths_after_rule_result():
    agent = FinancialReportAnomalyAgent()
    events = list(agent.stream_events(AnalysisRequest(
        query="分析0021G 2026P06 DCF0103异常波动",
        scenario="low_fluctuation",
    )))
    candidate_events = [x["data"] for x in events if x["event"] == "planner_candidates"]
    assert len(candidate_events) == 2
    second = candidate_events[1]["candidates"]
    assert len(second) == 2
    allowed = [x for x in second if x["conditionSatisfied"]]
    blocked = [x for x in second if not x["conditionSatisfied"]]
    assert len(allowed) == 1
    assert len(blocked) == 1
    assert "关系库事实" in allowed[0]["signalSource"]
    assert "actual=" in allowed[0]["conditionExplain"]


def test_frontend_uses_event_queue_and_paint_pacing():
    html = Path("app/static/index.html").read_text(encoding="utf-8")
    assert "/api/analyze/stream" in html
    assert "eventQueue" in html
    assert "requestAnimationFrame" in html
    assert "processQueue" in html
    assert "planner_candidates" in html
    assert "Runtime Guardrail" in html
    assert '<link rel="icon" href="data:,">' in html


def test_planner_skill_and_dynamic_workflow_are_resources():
    planner = Path("app/resources/skills/financial_anomaly_dynamic_planner.yaml").read_text(encoding="utf-8")
    ttl = Path("app/resources/financial_report_anomaly_ontology.ttl").read_text(encoding="utf-8")
    assert "candidate_transitions" in planner
    assert "WorkflowDefinition" in ttl
    assert "hasWorkflow" in ttl


def test_complete_contains_runtime_audit_reasoning_and_evidence_chain():
    out = run_scenario("government_subsidy_with_evidence")
    assert len(out.runtime_state.get("audit_reasoning", [])) >= 5
    assert len(out.runtime_state.get("evidence_chain", [])) == 2
    assert len(out.final_report.get("reasoning", [])) >= 5
    assert len(out.final_report.get("evidence_chain", [])) == 2
    assert out.final_report["audit_meta"]["reasoning_count"] >= 5
    assert out.final_report["audit_meta"]["evidence_count"] == 2


def test_frontend_empty_array_fallback_uses_runtime_audit_state():
    html = Path("app/static/index.html").read_text(encoding="utf-8")
    assert "reportEvidence.length?reportEvidence" in html
    assert "state.audit_reasoning" in html
    assert "state.evidence_chain" in html
