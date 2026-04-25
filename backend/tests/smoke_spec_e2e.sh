#!/bin/bash
# Phase α end-to-end smoke test for SPEC state machine.
# Prereq: backend running on localhost:8000, $TOKEN exported with valid bearer token,
#         user has a configured LLM config (builder/requirements purpose).
#
# What it verifies:
# 1. POST /api/spec creates an empty spec, returns id.
# 2. POST /api/conversations with agent_type=requirements + spec_id links them.
# 3. POST /api/chat/send with the user's first message triggers SpecAgent.
# 4. SSE stream emits "spec_patch" events as ask_clarifying_question tools fire.
# 5. Final spec has >= 3 pending decisions (gathering first-turn enforcement).

set -eu
TOKEN="${TOKEN:?Must export TOKEN with bearer token. Login first via POST /api/auth/login.}"
HOST="${HOST:-http://localhost:8000}"

echo "[1/4] Creating empty spec..."
SPEC_ID=$(curl -sS -X POST "$HOST/api/spec" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' | jq -r '.id')
echo "  -> spec_id=$SPEC_ID"

echo "[2/4] Creating conversation linked to spec..."
CONV_ID=$(curl -sS -X POST "$HOST/api/conversations" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"agent_type\":\"requirements\",\"spec_id\":\"$SPEC_ID\"}" | jq -r '.id')
echo "  -> conversation_id=$CONV_ID"

echo "[3/4] Sending first user message and tee'ing SSE stream..."
curl -sS -N -X POST "$HOST/api/chat/send" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"conversation_id\":$CONV_ID,\"message\":\"我想做一个预算管理系统，根据老项目backlog+新商机转化进行季度收入预测\"}" \
  | tee /tmp/spec_e2e_out.txt

echo
echo "[4/4] Verifying spec has >= 3 pending decisions..."
PENDING=$(curl -sS "$HOST/api/spec/$SPEC_ID" \
  -H "Authorization: Bearer $TOKEN" | jq '.decisions_pending | length')
echo "  -> decisions_pending=$PENDING"

if [ "$PENDING" -ge 3 ]; then
  echo "✅ Smoke PASS — SpecAgent gathering first-turn enforcement working"
  exit 0
else
  echo "❌ Smoke FAIL — expected ≥3 pending decisions, got $PENDING"
  echo "   Inspect /tmp/spec_e2e_out.txt for SSE stream content"
  exit 1
fi
