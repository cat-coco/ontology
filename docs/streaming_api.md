# v2.1 Streaming API

Endpoint:

```http
POST /api/analyze/stream
Content-Type: application/json
Accept: text/event-stream
```

## Why v2.1 feels different from v2

v2 already used SSE, but a browser may receive several SSE messages in a single `ReadableStream.read()` chunk. If JavaScript synchronously loops through all messages and updates the DOM before returning control to the browser, the browser paints them together. The user then sees `STEP 1 ~ STEP 5` appear almost at once.

v2.1 fixes this on both sides:

1. Backend uses an **async SSE generator**. Each Agent event is obtained in a worker thread, yielded immediately, and the event loop is explicitly released.
2. Frontend uses an **event queue**. Even when several SSE messages arrive in one network chunk, they are processed one by one with `requestAnimationFrame()` between events, so the browser visibly paints each state.

Config:

```env
STREAM_DEMO_DELAY_MS=160
UI_EVENT_DELAY_MS=180
```

`STREAM_DEMO_DELAY_MS` is only an intentional pacing delay for `LLM_PROVIDER=mock`.
`UI_EVENT_DELAY_MS` is frontend presentation pacing and prevents coalesced network chunks from producing one visual update.

## Planner lifecycle events

A Planner round now emits the following high-level lifecycle:

```text
planner_round
  current knowledge + current data

planner_candidates
  KG candidate transitions
  + Rule/Evidence gate status
  + allowed / blocked paths

planner_call
  LLM Planner Skill is running

planner
  selected next Skill
  + decision basis

 guardrail
  Runtime checks that LLM selection is legal

step / skill_call
  selected Skill actually runs

fact / evidence / rule_results
  new data and deterministic rules return

state_update
  new facts and rule results are written back
  and become the next Planner round input
```

This makes the dynamic loop visible without exposing private chain-of-thought. The UI shows structured planner inputs, candidates, decision basis and guardrail result, not hidden reasoning tokens.
