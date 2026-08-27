# 财报异常分析 Knowledge + Data Driven Agent Demo v2.1

## v2.2 审计结果聚合修复

- Runtime 将每条可展示 reasoning 事件同步沉淀到 `runtime_state.audit_reasoning`。
- 证据检索结果同步沉淀到 `runtime_state.evidence_chain`。
- 最终 `complete` 事件会把 Runtime 审计数据与 LLM 输出合并，百炼即使返回空 `reasoning` / `evidence_chain` 也能稳定展示。
- 前端修复 JavaScript 空数组为 truthy 导致 `evidence_chain=[]` 无法 fallback 的问题。


这是一个可本地运行的完整演示工程，用 **RDF/TTL 本体 + Mock知识图谱 + Mock关系库/ERP/RAG事实接口 + 确定性规则引擎 + LLM Planner Skill + 阿里百炼/Qwen** 完成财报异常分析。

v2.1重点解决两件事：

1. **真正可感知的流式体验**：修复“后端是SSE，但前端STEP 1~5看起来一次性出现”的问题；
2. **把动态Planner过程变成前端主舞台**：每轮明确展示“知识输入 → 数据输入 → KG候选路径 → 规则门控 → LLM选择 → Guardrail → Skill执行 → 状态写回”。

---

## 1. 核心理念

```text
领域知识定义：可以怎么分析
实时数据决定：当前发生了什么
确定性规则判断：哪些路径此刻成立
LLM Planner选择：下一步执行哪个Skill
Runtime Guardrail保证：不能跳出KG定义的合法路径
```

因此不是固定：

```text
Step1 → Step2 → Step3 → Step4 → Step5
```

而是每轮重新规划：

```text
KG + 当前Facts + Rule Results
          ↓
    LLM Planner Skill
          ↓
   下一Skill / 下一节点
          ↓
      Skill执行
          ↓
     新Facts返回
          ↓
     Rule Engine
          ↓
     下一轮Planner
```

---

## 2. 为什么v2会“看起来还是一次性出现”

v2后端已经逐条 `yield` SSE，但浏览器可能把多条SSE消息合并在一次：

```javascript
reader.read()
```

中返回。

原前端收到一个chunk后，会在同一个同步 `while` 循环内连续执行多次DOM更新：

```text
handle(event1)
handle(event2)
handle(event3)
...
```

浏览器直到JavaScript把这一批消息处理完，才有机会paint，所以人眼看到的是“STEP 1~STEP 5一起出现”。

v2.1做了双层修复。

### 后端

`/api/analyze/stream` 改成 async SSE generator：

```text
Agent next event
→ yield SSE
→ 让出async event loop
→ next event
```

Mock模式还可以通过：

```env
STREAM_DEMO_DELAY_MS=160
```

控制演示节奏。

### 前端

增加独立 Event Queue：

```text
network chunk
  ↓
parse SSE messages
  ↓
eventQueue
  ↓
逐条 handle
  ↓
requestAnimationFrame
  ↓
浏览器paint
  ↓
下一事件
```

即使浏览器一次收到10条SSE，也会逐条可视化。

前端节奏：

```env
UI_EVENT_DELAY_MS=180
```

---

## 3. v2.1前端动态Planner展示

每轮Planner都会依次出现：

```text
① Planner Round Start
   当前节点 / 已执行Skill

② Domain Knowledge
   AnalysisMethod
   Planner Skill
   KG Rules
   Workflow

③ Runtime Data
   本期/上期金额
   波动率
   贡献实体
   Evidence

④ Candidate Paths
   路径A：可走
   路径B：被阻断
   并展示为什么：
   actual >= threshold ?
   evidence_complete ?

⑤ LLM Planner Running
   Qwen / Mock Planner正在选择

⑥ Planner Decision
   选中的下一Skill
   decision_basis
   confidence

⑦ Runtime Guardrail
   PASS / FALLBACK

⑧ Skill Execution
   真正调用Mock EFM / Detail / ERP-RAG / LLM

⑨ State Update
   新事实 + 规则结果写回
   下一轮重新规划
```

这里不会暴露模型私有Chain-of-Thought，只展示**结构化Planner输入、候选路径、决策依据和Guardrail结果**。

---

## 4. 内置4个动态数据场景

### A. 高波动 + 证据完整

```text
SKILL_FETCH_EFM
→ 35% >= 20% : true
→ SKILL_FETCH_DETAIL
→ 769.23% > 50% : true
→ SKILL_RETRIEVE_EVIDENCE
→ evidence_complete = true
→ SKILL_GENERATE_CONCLUSION
```

### B. 低波动：动态提前结束

```text
SKILL_FETCH_EFM
→ 5% >= 20% : false
→ SKILL_GENERATE_CONCLUSION
```

此时前端会非常直观地显示：

```text
“继续下钻明细”路径      被阻断
“直接生成结论”路径      可走
```

### C. 整体高波动，但明细不显著

```text
SKILL_FETCH_EFM
→ overall = true
→ SKILL_FETCH_DETAIL
→ detail = false
→ SKILL_GENERATE_CONCLUSION
```

不会执行证据检索。

### D. 高波动 + 证据不足

```text
SKILL_FETCH_EFM
→ SKILL_FETCH_DETAIL
→ SKILL_RETRIEVE_EVIDENCE
→ evidence_complete = false
→ SKILL_REQUEST_MANUAL_EVIDENCE
→ SKILL_GENERATE_CONCLUSION
```

---

## 5. 快速运行

建议 Python 3.11+。

```bash
cd financial-report-ontology-agent-demo-v2.1

python -m venv .venv
```

Windows：

```bat
.venv\Scripts\activate
```

macOS / Linux：

```bash
source .venv/bin/activate
```

安装依赖：

```bash
pip install -r requirements.txt
```

复制配置：

Windows：

```bat
copy .env.example .env
```

macOS / Linux：

```bash
cp .env.example .env
```

启动：

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

浏览器打开：

```text
http://127.0.0.1:8000
```

默认：

```env
LLM_PROVIDER=mock
```

无需API Key即可演示完整动态Planner。

---

## 6. 阿里百炼 / Qwen

`.env`：

```env
LLM_PROVIDER=bailian
BAILIAN_API_KEY=你的API_KEY
BAILIAN_BASE_URL=https://你的WorkspaceId.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
BAILIAN_MODEL=qwen3.7-plus
```

新加坡Workspace可配置对应 `ap-southeast-1` 地址。

在百炼模式下：

- 每一轮 `Planner Decision` 都调用百炼；
- 最终 `SKILL_GENERATE_CONCLUSION` 再调用百炼生成结构化结论；
- `planner_call` SSE会先发到浏览器，因此模型调用期间页面明确显示“LLM Planner规划中”。

---

## 7. 关键代码

```text
app/
├── main.py
│   └── async SSE，保证逐事件flush
│
├── agent/
│   ├── orchestrator.py
│   │   └── 通用动态Runtime + Planner生命周期SSE
│   ├── planner_skill.py
│   │   └── 加载KG声明的Planner Skill，调用LLM
│   ├── skill_registry.py
│   │   └── Skill ID → API/SQL/RAG/LLM真实执行器
│   ├── rule_engine.py
│   │   └── 确定性Rule/Evidence Gate
│   └── prompts.py
│
├── gateways/
│   ├── kg_gateway.py
│   │   └── Mock：Rules + Skills + WorkflowDefinition
│   ├── fact_gateway.py
│   │   └── Mock：EFM / 数据工坊 / ERP / 文件证据
│   └── llm_gateway.py
│       └── Mock / Bailian
│
├── resources/
│   ├── financial_report_anomaly_ontology.ttl
│   └── skills/financial_anomaly_dynamic_planner.yaml
│
└── static/index.html
    ├── SSE ReadableStream
    ├── Event Queue
    ├── requestAnimationFrame逐条paint
    └── Planner Control Room动态可视化
```

---

## 8. 新增SSE事件

v2.1把Planner拆成可观测生命周期：

```text
started
knowledge
kg

planner_round
planner_candidates
planner_call
planner
guardrail

step
skill_call
fact / evidence
rule_results
reasoning
state_update
skill_call
step

... 下一轮 Planner ...

complete
```

详见：

```text
docs/streaming_api.md
```

---

## 9. 后续接真实系统时替换哪里

### 图数据库

替换：

```text
app/gateways/kg_gateway.py
```

保持核心Contract：

```text
analysisMethod
rules
skills
workflowDefinition
  nodes
  transitions
    condition
evidenceRequirements
plannerSkill
```

即可。

### 关系数据库 / EFM / 数据工坊

替换：

```text
app/gateways/fact_gateway.py
```

当前已经是按需调用：

```text
query_report_item_summary()
query_detail_facts()
query_business_evidence()
```

不会在分析开始时把所有数据一次性加载给LLM。

### Skill真实实现

替换或扩展：

```text
app/agent/skill_registry.py
```

例如：

```text
SKILL_FETCH_EFM              → EFM API
SKILL_FETCH_DETAIL           → SQL / 数据工坊API
SKILL_RETRIEVE_EVIDENCE      → RAG + ERP API
SKILL_REQUEST_MANUAL_EVIDENCE→ Workflow / 待办平台
SKILL_GENERATE_CONCLUSION    → Qwen
```

---

## 10. 测试

```bash
PYTHONPATH=. pytest -q
```

v2.1测试覆盖：

- 4种数据场景产生不同动态Skill路径；
- Planner完整生命周期事件；
- Candidate Paths同时存在“可走”和“被阻断”；
- Rule Gate解释包含实际值与阈值；
- 前端使用Event Queue + requestAnimationFrame；
- Planner Skill和Ontology Workflow资源可读取。

---

## 11. 建议Demo演示顺序

最容易体现差异的是连续演示两个场景：

### 先选“高波动 + 证据完整”

观察Planner不断展开路径：

```text
事实 → 明细 → 证据 → 结论
```

### 再选“低波动”

第二轮直接看到：

```text
继续下钻     BLOCKED
直接结论     ALLOWED
```

并直接跳到结论Skill。

这样最直观地证明：

> **前端出现的Step不是固定动画，而是领域知识定义候选路径、实时数据触发规则门控、LLM Planner动态选择后真正执行出来的路径。**
