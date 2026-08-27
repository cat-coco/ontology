# API Examples v2

## 健康检查

```bash
curl http://127.0.0.1:8000/api/health
```

## 查看KG动态执行图

```bash
curl http://127.0.0.1:8000/api/kg/workflow
```

## 同步分析：证据完整

```bash
curl -X POST http://127.0.0.1:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"query":"分析0021G 2026P06 DCF0103异常波动","scenario":"government_subsidy_with_evidence"}'
```

## 同步分析：低波动提前结束

```bash
curl -X POST http://127.0.0.1:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"query":"分析0021G 2026P06 DCF0103异常波动","scenario":"low_fluctuation"}'
```

## SSE

```bash
curl -N -X POST http://127.0.0.1:8000/api/analyze/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"query":"分析0021G 2026P06 DCF0103异常波动","scenario":"high_fluctuation_no_evidence"}'
```
