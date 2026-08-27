from pathlib import Path
from rdflib import Graph, Namespace, RDF, RDFS

FRA = Namespace("https://example.com/ontology/financial-report-anomaly#")

class OntologyService:
    """
    本地 RDF/TTL 本体读取层。
    Demo 使用 rdflib；生产环境可替换为 GraphDB/Jena/Fuseki/Neo4j 等。
    """
    def __init__(self, ttl_path: str | None = None):
        path = Path(ttl_path or Path(__file__).parents[1] / "resources" / "financial_report_anomaly_ontology.ttl")
        self.graph = Graph()
        self.graph.parse(path, format="turtle")

    def get_report_item_context(self, report_item_code: str) -> dict:
        # 通过 code 找到实例
        item = None
        for s in self.graph.subjects(FRA.code, None):
            code = self.graph.value(s, FRA.code)
            if code and str(code) == report_item_code:
                item = s
                break
        if item is None:
            return {"report_item": report_item_code, "found": False, "relations": []}

        relations = []
        for p, o in self.graph.predicate_objects(item):
            relations.append({
                "predicate": self._label_or_local(p),
                "predicate_uri": str(p),
                "object": self._label_or_local(o),
                "object_uri": str(o),
            })
        incoming = []
        for s, p in self.graph.subject_predicates(item):
            incoming.append({
                "subject": self._label_or_local(s),
                "subject_uri": str(s),
                "predicate": self._label_or_local(p),
                "predicate_uri": str(p),
            })
        return {
            "found": True,
            "report_item": report_item_code,
            "label": self._label_or_local(item),
            "uri": str(item),
            "relations": relations,
            "incoming_relations": incoming,
            "ontology_triples": len(self.graph),
        }

    def core_semantics(self) -> list[dict]:
        pairs = [
            (FRA.containsReportItem, "Report contains ReportItem"),
            (FRA.sourcedFrom, "ReportItem sourcedFrom FactData"),
            (FRA.appliesToReportItem, "Rule appliesTo ReportItem"),
            (FRA.causesFluctuation, "BusinessEvent causes Fluctuation"),
            (FRA.supportsBusinessEvent, "Evidence supports BusinessEvent"),
            (FRA.implementedBySkill, "AnalysisMethod implementedBy Skill"),
            (FRA.hasWorkflow, "AnalysisMethod has dynamic WorkflowDefinition"),
            (FRA.basedOnEvidence, "Conclusion basedOn Evidence"),
            (FRA.recommendsAction, "Conclusion recommends Action"),
        ]
        return [{"predicate": self._label_or_local(p), "semantic": s, "uri": str(p)} for p, s in pairs]

    def _label_or_local(self, node) -> str:
        label = self.graph.value(node, RDFS.label)
        if label:
            return str(label)
        text = str(node)
        return text.split("#")[-1].split("/")[-1]
