from abc import ABC, abstractmethod
from datetime import datetime, timezone
import uuid

from app.models import AnalysisIntent


class FactDataGateway(ABC):
    @abstractmethod
    def query_report_item_summary(self, intent: AnalysisIntent) -> dict:
        raise NotImplementedError

    @abstractmethod
    def query_detail_facts(self, intent: AnalysisIntent) -> dict:
        raise NotImplementedError

    @abstractmethod
    def query_business_evidence(self, intent: AnalysisIntent) -> dict:
        raise NotImplementedError


class MockFactDataGateway(FactDataGateway):
    """
    Mock关系库/EFM/数据工坊/ERP/文档接口。

    为了演示“数据驱动动态路径”，提供4个场景：
    - government_subsidy_with_evidence：35%整体波动 + 769.23%主要贡献 + 证据完整
    - low_fluctuation：5%整体波动，规则不触发，直接生成结论
    - high_overall_low_detail：35%整体波动，但最大明细仅25%，不进入证据链
    - high_fluctuation_no_evidence：高波动且主要贡献显著，但缺少文件证据，进入人工补证
    """

    def _envelope(self, operation: str, request_payload: dict, data: dict) -> dict:
        return {
            "code": "0",
            "message": "success(mock)",
            "traceId": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "request": request_payload,
            "data": data,
        }

    def query_report_item_summary(self, intent: AnalysisIntent) -> dict:
        request_payload = {
            "entityCode": intent.entity,
            "reportItemCode": intent.report_item,
            "period": intent.period,
            "comparePeriod": "2026P05",
            "scenario": intent.scenario,
        }

        if intent.scenario == "low_fluctuation":
            current = 77_777_777.77
            previous = 74_074_074.07
            change_rate = 0.05
        else:
            current = 100_000_000.00
            previous = 74_074_074.07
            change_rate = 0.35

        data = {
            "reportItem": {
                "code": intent.report_item,
                "name": "收到的政府补助",
                "currency": "CNY",
                "currentAmount": current,
                "previousAmount": previous,
                "changeAmount": current - previous,
                "changeRate": change_rate,
                "source": "EFM",
            }
        }
        return self._envelope("query_report_item_summary", request_payload, data)

    def query_detail_facts(self, intent: AnalysisIntent) -> dict:
        request_payload = {
            "entityCode": intent.entity,
            "reportItemCode": intent.report_item,
            "period": intent.period,
            "dimensions": ["entity", "profitCenter", "businessType"],
            "scenario": intent.scenario,
        }

        if intent.scenario == "high_overall_low_detail":
            contributors = [
                {
                    "entityCode": "2821G",
                    "entityName": "新能源子公司2821G",
                    "currentAmount": 50_000_000.00,
                    "previousAmount": 40_000_000.00,
                    "changeAmount": 10_000_000.00,
                    "changeRate": 0.25,
                    "contributionRank": 1,
                },
                {
                    "entityCode": "5481G",
                    "entityName": "其他子公司5481G",
                    "currentAmount": 50_000_000.00,
                    "previousAmount": 40_000_000.00,
                    "changeAmount": 10_000_000.00,
                    "changeRate": 0.25,
                    "contributionRank": 2,
                },
            ]
        else:
            contributors = [
                {
                    "entityCode": "2821G",
                    "entityName": "新能源子公司2821G",
                    "currentAmount": 90_000_000.00,
                    "previousAmount": 10_352_941.18,
                    "changeAmount": 79_647_058.82,
                    "changeRate": 7.6923,
                    "contributionRank": 1,
                },
                {
                    "entityCode": "5481G",
                    "entityName": "其他子公司5481G",
                    "currentAmount": 10_000_000.00,
                    "previousAmount": 8_000_000.00,
                    "changeAmount": 2_000_000.00,
                    "changeRate": 0.25,
                    "contributionRank": 2,
                },
            ]

        data = {
            "contributors": contributors,
            "detailRecords": [
                {
                    "detailId": "DTL-001",
                    "entityCode": "2821G",
                    "profitCenter": "PC-NE-01",
                    "businessType": "新能源项目补贴",
                    "amount": 80_000_000.00,
                    "source": "数据工坊",
                },
                {
                    "detailId": "DTL-002",
                    "entityCode": "2821G",
                    "profitCenter": "PC-NE-01",
                    "businessType": "其他政府补助",
                    "amount": 10_000_000.00,
                    "source": "数据工坊",
                },
            ],
        }
        return self._envelope("query_detail_facts", request_payload, data)

    def query_business_evidence(self, intent: AnalysisIntent) -> dict:
        request_payload = {
            "entityCode": "2821G",
            "reportItemCode": intent.report_item,
            "period": intent.period,
            "eventTypes": ["GovernmentSubsidyReceived"],
            "evidenceTypes": ["DocumentEvidence", "DataEvidence"],
            "scenario": intent.scenario,
        }

        doc_matched = intent.scenario != "high_fluctuation_no_evidence"
        data = {
            "businessEvents": [
                {
                    "eventId": "EVENT_NEW_ENERGY_SUBSIDY_2026P06",
                    "eventType": "GovernmentSubsidyReceived",
                    "name": "新能源建设项目补贴到账",
                    "entityCode": "2821G",
                    "period": intent.period,
                    "amount": 80_000_000.00,
                }
            ],
            "evidence": [
                {
                    "evidenceId": "EVD_SUBSIDY_APPROVAL",
                    "type": "DocumentEvidence",
                    "name": "新能源建设项目补贴批复文件",
                    "matched": doc_matched,
                    "reference": "DOC://subsidy/2026/2821G/approval" if doc_matched else None,
                    "reason": None if doc_matched else "Mock场景：文件中心未返回对应批复文件",
                },
                {
                    "evidenceId": "EVD_JOURNAL_ENTRY",
                    "type": "DataEvidence",
                    "name": "政府补助到账会计分录",
                    "matched": True,
                    "reference": "ERP_GL:JRN_2821G_GOV_001",
                },
            ],
        }
        return self._envelope("query_business_evidence", request_payload, data)

    # 兼容旧接口，方便外部调用/调试，但动态Agent不会一次性消费全部事实。
    def query_financial_facts(self, intent: AnalysisIntent) -> dict:
        base = self.query_report_item_summary(intent)
        detail = self.query_detail_facts(intent)
        evidence = self.query_business_evidence(intent)
        merged = {}
        merged.update(base["data"])
        merged.update(detail["data"])
        merged.update(evidence["data"])
        return self._envelope(
            "query_financial_facts_compat",
            {"entityCode": intent.entity, "reportItemCode": intent.report_item, "period": intent.period},
            merged,
        )
