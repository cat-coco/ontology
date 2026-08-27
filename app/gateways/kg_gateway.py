from abc import ABC, abstractmethod
from datetime import datetime, timezone
import uuid

from app.models import AnalysisIntent


class KnowledgeGraphGateway(ABC):
    @abstractmethod
    def query_analysis_knowledge(self, intent: AnalysisIntent) -> dict:
        raise NotImplementedError


class MockKnowledgeGraphGateway(KnowledgeGraphGateway):
    """
    Mock图数据库接口。

    关键点：KG不再只返回“Skill列表”，而是返回：
    1) 领域对象与关系；
    2) 规则；
    3) 分析方法；
    4) Skill元数据；
    5) WorkflowDefinition（节点 + 条件边）；
    6) 证据要求。

    未来替换为GraphDB/Neo4j/Jena时，只要保持response schema，Agent Runtime无需重写。
    """

    def query_analysis_knowledge(self, intent: AnalysisIntent) -> dict:
        request_payload = {
            "operation": "query_dynamic_anomaly_analysis_context",
            "filters": {
                "entityCode": intent.entity,
                "reportItemCode": intent.report_item,
                "period": intent.period,
                "taskType": intent.task_type,
            },
            "include": [
                "rules",
                "analysisMethod",
                "skills",
                "workflowDefinition",
                "evidenceRequirements",
                "relations",
            ],
        }

        skills = [
            {
                "id": "SKILL_FETCH_EFM",
                "name": "EFM表单取数Skill",
                "description": "获取报表项本期/上期金额及整体波动率。",
                "tool": "mock_efm_api",
                "produces": ["reportItem"],
            },
            {
                "id": "SKILL_FETCH_DETAIL",
                "name": "数据工坊明细获取与计算Skill",
                "description": "获取贡献实体、业务类型和明细记录。",
                "tool": "mock_detail_api",
                "requires": ["reportItem"],
                "produces": ["contributors", "detailRecords"],
            },
            {
                "id": "SKILL_RETRIEVE_EVIDENCE",
                "name": "业务事件与证据检索Skill",
                "description": "检索业务事件、批复文件、ERP分录等证据。",
                "tool": "mock_document_and_erp_api",
                "requires": ["contributors"],
                "produces": ["businessEvents", "evidence"],
            },
            {
                "id": "SKILL_REQUEST_MANUAL_EVIDENCE",
                "name": "人工补证协同Skill",
                "description": "当KG要求的关键证据不完整时，形成待人工补充的证据清单。",
                "tool": "local_human_in_loop",
                "requires": ["evidence"],
                "produces": ["manualEvidenceRequest"],
            },
            {
                "id": "SKILL_GENERATE_CONCLUSION",
                "name": "可审计结论生成Skill",
                "description": "基于已执行路径、事实、规则和证据生成最终结论与行动。",
                "tool": "llm",
                "produces": ["finalReport"],
            },
        ]

        workflow = {
            "id": "WORKFLOW_GOV_SUBSIDY_DYNAMIC_ANALYSIS",
            "name": "政府补助异常波动动态执行图",
            "entryNodeId": "NODE_FETCH_BASE_FACT",
            "terminalNodeIds": ["NODE_GENERATE_CONCLUSION"],
            "nodes": [
                {
                    "id": "NODE_FETCH_BASE_FACT",
                    "skillId": "SKILL_FETCH_EFM",
                    "name": "获取整体报表事实",
                    "evaluateRulesAfter": ["RULE_DCF0103_OVERALL_20"],
                },
                {
                    "id": "NODE_FETCH_DETAIL",
                    "skillId": "SKILL_FETCH_DETAIL",
                    "name": "下钻贡献实体与明细",
                    "evaluateRulesAfter": ["RULE_DCF0103_DETAIL_50"],
                },
                {
                    "id": "NODE_RETRIEVE_EVIDENCE",
                    "skillId": "SKILL_RETRIEVE_EVIDENCE",
                    "name": "验证业务事件与证据链",
                    "evaluateRulesAfter": [],
                },
                {
                    "id": "NODE_REQUEST_MANUAL_EVIDENCE",
                    "skillId": "SKILL_REQUEST_MANUAL_EVIDENCE",
                    "name": "证据不足时请求人工补证",
                    "evaluateRulesAfter": [],
                },
                {
                    "id": "NODE_GENERATE_CONCLUSION",
                    "skillId": "SKILL_GENERATE_CONCLUSION",
                    "name": "生成可审计结论",
                    "evaluateRulesAfter": [],
                },
            ],
            "transitions": [
                {
                    "id": "T01",
                    "from": "NODE_FETCH_BASE_FACT",
                    "to": "NODE_FETCH_DETAIL",
                    "condition": {"type": "rule_triggered", "ruleId": "RULE_DCF0103_OVERALL_20", "expected": True},
                    "businessMeaning": "整体波动达到异常阈值，需要继续下钻。",
                },
                {
                    "id": "T02",
                    "from": "NODE_FETCH_BASE_FACT",
                    "to": "NODE_GENERATE_CONCLUSION",
                    "condition": {"type": "rule_triggered", "ruleId": "RULE_DCF0103_OVERALL_20", "expected": False},
                    "businessMeaning": "整体波动未达到阈值，可提前结束深度分析。",
                },
                {
                    "id": "T03",
                    "from": "NODE_FETCH_DETAIL",
                    "to": "NODE_RETRIEVE_EVIDENCE",
                    "condition": {"type": "rule_triggered", "ruleId": "RULE_DCF0103_DETAIL_50", "expected": True},
                    "businessMeaning": "存在显著贡献实体/明细，需要验证真实业务原因。",
                },
                {
                    "id": "T04",
                    "from": "NODE_FETCH_DETAIL",
                    "to": "NODE_GENERATE_CONCLUSION",
                    "condition": {"type": "rule_triggered", "ruleId": "RULE_DCF0103_DETAIL_50", "expected": False},
                    "businessMeaning": "未发现超过阈值的主要贡献项，可直接综合已有事实形成结论。",
                },
                {
                    "id": "T05",
                    "from": "NODE_RETRIEVE_EVIDENCE",
                    "to": "NODE_GENERATE_CONCLUSION",
                    "condition": {"type": "evidence_complete", "expected": True},
                    "businessMeaning": "关键证据完整，可以形成合理性结论。",
                },
                {
                    "id": "T06",
                    "from": "NODE_RETRIEVE_EVIDENCE",
                    "to": "NODE_REQUEST_MANUAL_EVIDENCE",
                    "condition": {"type": "evidence_complete", "expected": False},
                    "businessMeaning": "关键证据缺失，需要进入人工补证。",
                },
                {
                    "id": "T07",
                    "from": "NODE_REQUEST_MANUAL_EVIDENCE",
                    "to": "NODE_GENERATE_CONCLUSION",
                    "condition": {"type": "always"},
                    "businessMeaning": "记录证据缺口后形成暂定结论和待办行动。",
                },
            ],
        }

        return {
            "code": "0",
            "message": "success(mock)",
            "traceId": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request": request_payload,
            "data": {
                "nodes": [
                    {"id": "Entity_0021G", "type": "FinancialEntity", "properties": {"code": intent.entity, "name": "集团分析实体0021G"}},
                    {"id": "CashFlowStatement", "type": "Report", "properties": {"code": "CFS", "name": "现金流量表"}},
                    {"id": "ReportItem_DCF0103", "type": "ReportItem", "properties": {"code": intent.report_item, "name": "收到的政府补助"}},
                    {"id": "Method_GovSubsidyFluctuation", "type": "AnalysisMethod", "properties": {"name": "政府补助波动合理性分析方法"}},
                    {"id": workflow["id"], "type": "WorkflowDefinition", "properties": {"name": workflow["name"]}},
                ],
                "relations": [
                    {"from": "CashFlowStatement", "predicate": "containsReportItem", "to": "ReportItem_DCF0103"},
                    {"from": "Rule_DCF0103_Overall20", "predicate": "appliesToReportItem", "to": "ReportItem_DCF0103"},
                    {"from": "Method_GovSubsidyFluctuation", "predicate": "hasWorkflow", "to": workflow["id"]},
                    {"from": workflow["id"], "predicate": "hasNode", "to": "NODE_FETCH_BASE_FACT"},
                    {"from": "NODE_FETCH_BASE_FACT", "predicate": "executesSkill", "to": "SKILL_FETCH_EFM"},
                ],
                "rules": [
                    {
                        "id": "RULE_DCF0103_OVERALL_20",
                        "name": "DCF0103整体波动阈值规则",
                        "metric": "changeRate",
                        "operator": ">=",
                        "threshold": 0.20,
                        "triggerAction": "OPEN_DETAIL_ANALYSIS",
                    },
                    {
                        "id": "RULE_DCF0103_DETAIL_50",
                        "name": "DCF0103明细异常识别规则",
                        "metric": "majorContributorChangeRate",
                        "operator": ">",
                        "threshold": 0.50,
                        "triggerAction": "RETRIEVE_BUSINESS_EVIDENCE",
                    },
                ],
                "analysisMethod": {
                    "id": "METHOD_GOV_SUBSIDY_FLUCTUATION",
                    "name": "政府补助波动合理性分析方法",
                    "principle": "先识别整体异常，再按贡献度下钻；只有在显著明细存在时才检索业务事件和证据；证据不足时必须进入人工补证。",
                    "drilldownDimensions": ["公司", "利润中心", "业务类型"],
                    "workflowId": workflow["id"],
                },
                "skills": skills,
                "workflowDefinition": workflow,
                "evidenceRequirements": [
                    {"type": "DocumentEvidence", "name": "政府补助/项目批复文件", "required": True},
                    {"type": "DataEvidence", "name": "到账会计分录", "required": True},
                ],
                "plannerSkill": {
                    "id": "SKILL_FINANCIAL_ANOMALY_DYNAMIC_PLANNER",
                    "name": "财报异常分析动态规划Skill",
                    "resource": "app/resources/skills/financial_anomaly_dynamic_planner.yaml",
                },
            },
        }
