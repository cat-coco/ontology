# Architecture v2.1 — Knowledge + Data Driven Dynamic Agent

```text
              Ontology / Knowledge Graph
       ┌──────────────┼────────────────┐
       │              │                │
  Semantics        Rules         Workflow + Skills
       │              │                │
       └──────────────┼────────────────┘
                      ↓
               LLM Planner Skill
                      │
       candidate paths│ + current facts
                      ↓
               Runtime Guardrail
                      ↓
                 Execute Skill
                      ↓
         Mock API / SQL / ERP / RAG
                      ↓
                 New Fact Data
                      ↓
             Deterministic Rules
                      ↓
             update runtime state
                      └──────────────→ next Planner round
```

The important distinction is that the Orchestrator does **not** encode a fixed business sequence. It only implements a reusable runtime loop.

## Responsibilities

- **Ontology**: what Report, ReportItem, Rule, Event, Evidence, AnalysisMethod and Skill mean.
- **KG**: which Rules apply, which Skills exist, and which conditional transitions are allowed.
- **Planner Skill**: expert planning policy in natural-language/structured form.
- **Fact Gateway**: returns current business facts only when a selected Skill requests them.
- **Rule Engine**: computes deterministic threshold/evidence conditions.
- **LLM Planner**: chooses the next Skill among KG-permitted candidates.
- **Guardrail**: refuses a Planner decision that violates KG or current rule gates.
- **Skill Registry**: maps semantic Skill IDs to executable APIs/tools.

## Frontend visualization

v2.1 makes each round visible as:

```text
Knowledge signals
+ Data signals
→ Candidate path gates
→ LLM Planner running
→ Planner decision
→ Runtime Guardrail
→ Skill execution
→ New fact / rule state
→ next round
```

The UI intentionally shows structured decision inputs and outcomes rather than hidden model chain-of-thought.
