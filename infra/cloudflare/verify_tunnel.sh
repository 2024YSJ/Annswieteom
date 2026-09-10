#!/usr/bin/env sh
# Ollama 계약 검증 스크립트 (Linux / Git Bash)
#
# 사용법:
#   # DGX Spark 자기 자신에서 (터널 뚫기 전 계약 검증 — 08번 체크리스트 4절)
#   ./infra/cloudflare/verify_tunnel.sh -u http://localhost:11434
#
#   # 외부 기기에서 터널을 거쳐 (08번 체크리스트 8절)
#   ./infra/cloudflare/verify_tunnel.sh -u https://llm.annswieteom.com \
#       -i "$LLM_ACCESS_CLIENT_ID" -s "$LLM_ACCESS_CLIENT_SECRET"
#
# "Ollama is running"만 확인하는 건 데몬이 답한다는 증거일 뿐 데모가 돌아간다는
# 증거가 아니다. 이 스크립트는 백엔드가 실제로 의존하는 4가지를 검사한다.
#
# 주의: 응답을 캐싱하는 도구로 확인하지 말 것. 죽은 터널이 살아 있는 것처럼 보여
# 디버깅 한 세션을 통째로 날린 적이 있다(docs/devlog/PersonA/05_cloudflare_tunnel.md).

set -u

URL=""
CLIENT_ID=""
CLIENT_SECRET=""
MODEL="${LOCAL_LLM_MODEL_NAME:-qwen2.5:32b}"
EMBED_MODEL="bge-m3"   # 하드코딩이 맞다 — 코드도 하드코딩이고 1024차원이 DB 컬럼 타입이다
EXPECTED_DIM=1024

while [ $# -gt 0 ]; do
  case "$1" in
    -u) URL="$2"; shift 2 ;;
    -i) CLIENT_ID="$2"; shift 2 ;;
    -s) CLIENT_SECRET="$2"; shift 2 ;;
    -m) MODEL="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$URL" ]; then
  echo "usage: $0 -u <base-url> [-i <access-client-id> -s <access-client-secret>] [-m <model>]" >&2
  exit 2
fi

URL="${URL%/}"
FAILED=0

AUTH=""
if [ -n "$CLIENT_ID" ] && [ -n "$CLIENT_SECRET" ]; then
  AUTH="-H CF-Access-Client-Id:$CLIENT_ID -H CF-Access-Client-Secret:$CLIENT_SECRET"
  echo "Using Cloudflare Access service token."
else
  echo "No Access token supplied. Against the tunnel, expect 403 - that means Access is on."
fi

echo "Checking $URL"
echo

# --- 1. 데몬이 답하는지 -------------------------------------------------------
echo "[1/4] GET / -> \"Ollama is running\""
# shellcheck disable=SC2086
BODY=$(curl -s --max-time 15 $AUTH "$URL/" 2>&1)
case "$BODY" in
  *"Ollama is running"*) echo "      OK" ;;
  *)
    echo "      FAIL: $BODY"
    echo
    echo "      1033 / 530  -> 터널에 커넥터가 안 붙었다. systemctl status cloudflared,"
    echo "                     journalctl -u cloudflared -n 50 --no-pager"
    echo "      403         -> Access 토큰 없이 보냈거나(정상), 또는 cloudflared ingress에"
    echo "                     originRequest.httpHostHeader: localhost:11434 가 빠졌다"
    echo "      연결 거부   -> Ollama가 안 떠 있다. snap services ollama / sudo snap restart ollama"
    echo "                     또는 127.0.0.1에만 바인딩됐다: sudo snap set ollama host=\"0.0.0.0:11434\""
    exit 1
    ;;
esac

# --- 2. 모델 두 개가 다 있는지 ------------------------------------------------
echo "[2/4] GET /api/tags -> $MODEL AND $EMBED_MODEL"
# shellcheck disable=SC2086
TAGS=$(curl -s --max-time 15 $AUTH "$URL/api/tags" 2>&1)
for m in "$MODEL" "$EMBED_MODEL"; do
  case "$TAGS" in
    *"$m"*) echo "      OK   $m" ;;
    *)
      echo "      FAIL $m 이 없다 -> ollama pull $m"
      [ "$m" = "$EMBED_MODEL" ] && echo "           (임베딩 모델이다. 없으면 기록물·피드 임베딩이 예외 없이 조용히 전멸한다)"
      FAILED=1
      ;;
  esac
done

# --- 3. 백엔드와 같은 페이로드로 생성 + 시간 측정 ------------------------------
echo "[3/4] POST /api/chat (백엔드와 동일한 페이로드, 첫 바이트/총 시간 측정)"
CHAT_BODY=$(printf '{"model":"%s","messages":[{"role":"system","content":"Output JSON only."},{"role":"user","content":"{\\"ping\\":true} 를 그대로 반환해줘"}],"stream":true,"format":"json","keep_alive":-1,"options":{"temperature":0.0,"num_ctx":8192}}' "$MODEL")
# shellcheck disable=SC2086
TIMING=$(curl -sN --max-time 300 -o /dev/null -w '%{time_starttransfer} %{time_total} %{http_code}' \
  $AUTH -H 'Content-Type: application/json' -d "$CHAT_BODY" "$URL/api/chat" 2>&1)
set -- $TIMING
TTFB="${1:-?}"; TOTAL="${2:-?}"; CODE="${3:-?}"
if [ "$CODE" = "200" ]; then
  echo "      OK   http=$CODE  첫 바이트 ${TTFB}s  총 ${TOTAL}s"
  echo "           첫 바이트가 100s에 가까우면 Cloudflare 프록시 read timeout(524)에 걸린다."
  echo "           총 시간이 240s를 넘으면 백엔드의 생성 타임아웃에 걸린다."
else
  echo "      FAIL http=$CODE (첫 바이트 ${TTFB}s, 총 ${TOTAL}s)"
  FAILED=1
fi

# --- 4. 임베딩 차원 -----------------------------------------------------------
echo "[4/4] POST /api/embed -> 벡터 길이 $EXPECTED_DIM"
# shellcheck disable=SC2086
EMB=$(curl -s --max-time 120 $AUTH -H 'Content-Type: application/json' \
  -d "{\"model\":\"$EMBED_MODEL\",\"input\":[\"테스트\"]}" "$URL/api/embed" 2>&1)
DIM=$(printf '%s' "$EMB" | python3 -c 'import json,sys
try:
    print(len(json.load(sys.stdin)["embeddings"][0]))
except Exception:
    print("-1")' 2>/dev/null || echo "-1")
if [ "$DIM" = "$EXPECTED_DIM" ]; then
  echo "      OK   $DIM"
else
  echo "      FAIL 길이 $DIM (기대: $EXPECTED_DIM)"
  echo "           1024가 아니면 컷오버를 중단한다. VECTOR(1024) 컬럼에 넣을 수 없어서"
  echo "           사용자가 기록물을 올리는 순간 요청 도중에 EmbeddingDimensionMismatchError가 터진다."
  FAILED=1
fi

echo
if [ "$FAILED" -eq 0 ]; then
  echo "All 4 contract checks passed."
else
  echo "Contract checks FAILED. 위 항목을 고친 뒤 다시 실행한다."
fi
exit "$FAILED"
