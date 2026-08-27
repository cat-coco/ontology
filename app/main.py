import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.agent.orchestrator import FinancialReportAnomalyAgent
from app.config import settings
from app.models import AnalysisRequest

load_dotenv()
app = FastAPI(title="财报异常分析 Knowledge Driven Agent Demo", version="2.1.0")
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def index():
    return FileResponse(static_dir / "index.html")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": "2.1.0",
        "llmProvider": settings.llm_provider,
        "model": settings.bailian_model if settings.llm_provider == "bailian" else "mock",
        "streaming": True,
        "dynamicPlanner": True,
        "streamDemoDelayMs": settings.stream_demo_delay_ms,
        "uiEventDelayMs": settings.ui_event_delay_ms,
    }


@app.get("/api/ontology/core")
def ontology_core():
    agent = FinancialReportAnomalyAgent()
    return {"semantics": agent.ontology.core_semantics(), "triples": len(agent.ontology.graph)}


@app.get("/api/kg/workflow")
def kg_workflow():
    agent = FinancialReportAnomalyAgent()
    intent = agent._extract_intent(AnalysisRequest(query="分析0021G 2026P06 DCF0103异常波动"))
    return agent.kg.query_analysis_knowledge(intent)["data"]["workflowDefinition"]


@app.post("/api/analyze")
def analyze(request: AnalysisRequest):
    agent = FinancialReportAnomalyAgent()
    return agent.analyze(request)


@app.post("/api/analyze/stream")
async def analyze_stream(request: AnalysisRequest):
    """
    真正逐事件 flush 的 SSE 接口。

    v2 的症状之一是：虽然生成器逐条 yield，但浏览器/网络可能把多条事件合并到一次 read()，
    前端又在同一个同步 while 中连续改 DOM，视觉上就像一次性出现。

    v2.1 做两层保证：
    1) 后端使用 async generator，并把同步 Agent next() 放在线程中执行；每条事件 yield 后让出事件循环。
    2) 前端再用 Event Queue + requestAnimationFrame 逐条渲染，避免 TCP chunk 合并影响视觉体验。
    """
    agent = FinancialReportAnomalyAgent()
    iterator = iter(agent.stream_events(request))

    def next_event():
        return next(iterator, None)

    async def event_stream():
        try:
            while True:
                message = await asyncio.to_thread(next_event)
                if message is None:
                    break
                payload = json.dumps(
                    message["data"], ensure_ascii=False, separators=(",", ":"), default=str
                )
                yield f"event: {message['event']}\ndata: {payload}\n\n"

                # Mock 模式保留可见演示节奏；真实 LLM 不人为等待，但显式让出事件循环以 flush。
                if settings.llm_provider == "mock" and settings.stream_demo_delay_ms > 0:
                    await asyncio.sleep(settings.stream_demo_delay_ms / 1000.0)
                else:
                    await asyncio.sleep(0)
        except Exception as exc:
            payload = json.dumps({"message": str(exc)}, ensure_ascii=False, separators=(",", ":"))
            yield f"event: error\ndata: {payload}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        },
    )
