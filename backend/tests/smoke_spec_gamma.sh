#!/bin/bash
# Phase γ end-to-end smoke (manual; needs running backend + TOKEN).
set -eu
TOKEN="${TOKEN:?Must export TOKEN with bearer token.}"
HOST="${HOST:-http://localhost:8000}"

echo "[Step 1] Create empty spec..."
SPEC_ID=$(curl -sS -X POST "$HOST/api/spec" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}' | jq -r '.id')

echo "[Step 2] Create conversation linked to spec..."
CONV_ID=$(curl -sS -X POST "$HOST/api/conversations" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"agent_type\":\"requirements\",\"spec_id\":\"$SPEC_ID\"}" | jq -r '.id')

echo "[Step 3] Upload a complete spec doc..."
cat > /tmp/spec_demo.md <<MD
# 预算管理系统

## 角色
- 财务负责人 (finance_lead): 全部数据
- 销售总监 (sales_director): 本部门数据

## 数据对象
### 季度预测 (t_quarter_forecast)
- 预测编号 (forecast_no): 单据号 必填
- 金额 (amount): 数字 必填
- 状态 (status): 下拉单选 → forecast_status

## 字典
- 预测状态 (forecast_status): 草稿/已确认/已审批

## 权限
- t_quarter_forecast: finance_lead 全操作 ALL；sales_director 编辑 DEPT
MD

curl -sS -N -X POST "$HOST/api/chat/send-with-file" \
  -H "Authorization: Bearer $TOKEN" \
  -F "conversation_id=$CONV_ID" \
  -F "message=请基于附件创建" \
  -F "file=@/tmp/spec_demo.md" | tee /tmp/spec_gamma_out.txt

echo "[Step 4] Verify spec was populated..."
SPEC_JSON=$(curl -sS "$HOST/api/spec/$SPEC_ID" -H "Authorization: Bearer $TOKEN")
PHASE=$(echo "$SPEC_JSON" | jq -r '.phase')
ROLE_CT=$(echo "$SPEC_JSON" | jq -r '.roles | length')
OBJ_CT=$(echo "$SPEC_JSON" | jq -r '.objects | length')
DICT_CT=$(echo "$SPEC_JSON" | jq -r '.dicts | length')
echo "  -> phase=$PHASE roles=$ROLE_CT objects=$OBJ_CT dicts=$DICT_CT"

[ "$PHASE" = "ready" ] || [ "$PHASE" = "drafting" ] || { echo "❌ phase invalid"; exit 1; }
[ "$ROLE_CT" -ge 2 ] || { echo "❌ expected ≥2 roles"; exit 1; }
[ "$OBJ_CT" -ge 1 ] || { echo "❌ expected ≥1 object"; exit 1; }
echo "✅ Phase γ smoke PASS"
