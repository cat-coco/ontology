from dotenv import load_dotenv
load_dotenv()

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock").lower()
    bailian_api_key: str = os.getenv("BAILIAN_API_KEY", "")
    bailian_base_url: str = os.getenv(
        "BAILIAN_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    bailian_model: str = os.getenv("BAILIAN_MODEL", "qwen3.7-plus")
    app_host: str = os.getenv("APP_HOST", "127.0.0.1")
    app_port: int = int(os.getenv("APP_PORT", "8000"))

    # 后端 SSE 每条事件之间的演示节奏。Mock 模式建议 120~300ms。
    # 百炼模式也会在每个事件后 await 0，保证事件尽快 flush。
    stream_demo_delay_ms: int = int(os.getenv("STREAM_DEMO_DELAY_MS", "160"))

    # 前端事件队列的最小展示间隔。即使浏览器一次收到多个 SSE chunk，
    # 也会逐条渲染并给浏览器一次 paint 机会，避免“Step1-Step5瞬间一起出现”。
    ui_event_delay_ms: int = int(os.getenv("UI_EVENT_DELAY_MS", "180"))


settings = Settings()
