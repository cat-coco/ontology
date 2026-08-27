# Mock接口契约

## KG

`MockKnowledgeGraphGateway.query_analysis_knowledge(intent)` 返回：

- `rules`
- `analysisMethod`
- `skills`
- `workflowDefinition.nodes`
- `workflowDefinition.transitions`
- `evidenceRequirements`
- `plannerSkill`

真实图数据库只需保持这一响应Schema即可替换Mock实现。

## 事实数据

动态Agent按需调用，不一次性把全部数据灌给模型：

- `query_report_item_summary`：EFM报表项事实
- `query_detail_facts`：数据工坊贡献实体/明细
- `query_business_evidence`：业务事件、文件、ERP分录

这使“是否继续取更深的数据”本身成为Agent动态规划的一部分。
