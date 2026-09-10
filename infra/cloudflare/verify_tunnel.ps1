# Cloudflare Tunnel + Ollama 계약 검증 스크립트 (Windows 운영자용)
#
# 사용법:
#   .\infra\cloudflare\verify_tunnel.ps1 -TunnelUrl https://llm.annswieteom.com `
#       -AccessClientId $env:LLM_ACCESS_CLIENT_ID -AccessClientSecret $env:LLM_ACCESS_CLIENT_SECRET
#
# 외부 기기에서 실행할 것 — 추론 서버 안에서는 localhost로 직접 연결돼
# 터널이 실제로 외부에 노출됐는지 확인할 수 없다.
#
# 추론 서버는 Linux(DGX Spark)지만 이 스크립트는 그대로 남긴다: 운영자가 실제로
# 쓰는 기계가 Windows 노트북이고, "외부에서 확인한다"는 게 이 파일의 존재 이유다.
# 서버 자기 자신에서 돌릴 때는 verify_tunnel.sh 를 쓴다.
#
# "Ollama is running"만 확인하는 건 데몬이 답한다는 증거일 뿐 데모가 돌아간다는
# 증거가 아니다. 백엔드가 실제로 의존하는 4가지를 검사한다.

param(
    [Parameter(Mandatory=$true)]
    [string]$TunnelUrl,

    [string]$AccessClientId = "",
    [string]$AccessClientSecret = "",

    # 운영 기본값. 다른 모델을 검증할 때만 넘긴다.
    [string]$Model = "qwen2.5:72b"
)

$url = $TunnelUrl.TrimEnd("/")
$embedModel = "bge-m3"   # 하드코딩이 맞다 — 코드도 하드코딩이고 1024차원이 DB 컬럼 타입이다
$expectedDim = 1024
$failed = 0

$headers = @{}
if ($AccessClientId -and $AccessClientSecret) {
    $headers["CF-Access-Client-Id"] = $AccessClientId
    $headers["CF-Access-Client-Secret"] = $AccessClientSecret
    Write-Host "Using Cloudflare Access service token."
} else {
    Write-Host "No Access token supplied. Against the tunnel, expect 403 - that means Access is on."
}

Write-Host "Checking $url"
Write-Host ""

function Show-Hints {
    Write-Host ""
    Write-Host "Checklist:"
    Write-Host "  1. 403 인데 토큰을 넣었다면 -> cloudflared ingress에 originRequest.httpHostHeader: localhost:11434 가 빠졌다"
    Write-Host "     (Ollama가 DNS 리바인딩 방지로 낯선 Host 헤더를 거부한다. 이 프로젝트에서 두 번 겪었다)"
    Write-Host "  2. 1033 / 530 -> 터널에 커넥터가 안 붙었다. 서버에서:"
    Write-Host "       systemctl status cloudflared"
    Write-Host "       journalctl -u cloudflared -n 50 --no-pager   # active 표시만으로는 증거가 안 된다"
    Write-Host "  3. Ollama가 안 뜬 것 같다 -> 서버에서 snap services ollama / sudo snap restart ollama"
    Write-Host "  4. 127.0.0.1에만 바인딩됐다 -> sudo snap set ollama host=`"0.0.0.0:11434`" 후 재시작"
    Write-Host "  5. DNS가 옛 터널을 가리킨다 -> cloudflared tunnel route dns annswieteom-llm-spark llm.annswieteom.com --overwrite-dns"
    Write-Host "     (DNS는 '터널 ID'를 가리켜야 한다 - 계정 ID/커넥터 ID와 생김새가 비슷하다)"
}

# --- 1. 데몬이 답하는지 -------------------------------------------------------
Write-Host "[1/4] GET / -> 'Ollama is running'"
try {
    $response = Invoke-RestMethod -Uri "$url/" -Method Get -Headers $headers -TimeoutSec 15
    if ("$response" -match "Ollama is running") {
        Write-Host "      OK"
    } else {
        Write-Host "      WARN 응답은 왔지만 Ollama처럼 보이지 않는다: $response"
        $failed = 1
    }
} catch {
    Write-Host "      FAIL $url 에 닿지 못했다"
    Write-Host "      Error: $_"
    Show-Hints
    exit 1
}

# --- 2. 모델 두 개가 다 있는지 ------------------------------------------------
Write-Host "[2/4] GET /api/tags -> $Model AND $embedModel"
try {
    $tags = Invoke-RestMethod -Uri "$url/api/tags" -Method Get -Headers $headers -TimeoutSec 15
    $names = @($tags.models | ForEach-Object { $_.name })
    foreach ($m in @($Model, $embedModel)) {
        if ($names -match [regex]::Escape($m)) {
            Write-Host "      OK   $m"
        } else {
            Write-Host "      FAIL $m 이 없다 -> ollama pull $m"
            if ($m -eq $embedModel) {
                Write-Host "           (임베딩 모델이다. 없으면 기록물·피드 임베딩이 예외 없이 조용히 전멸한다)"
            }
            $failed = 1
        }
    }
} catch {
    Write-Host "      FAIL /api/tags 조회 실패: $_"
    $failed = 1
}

# --- 3. 백엔드와 같은 페이로드로 생성 + 시간 측정 ------------------------------
Write-Host "[3/4] POST /api/chat (백엔드와 동일한 페이로드, 총 시간 측정)"
$chatBody = @{
    model      = $Model
    messages   = @(
        @{ role = "system"; content = "Output JSON only." },
        @{ role = "user";   content = '{"ping":true} 를 그대로 반환해줘' }
    )
    stream     = $false   # PowerShell에서 스트림 조각을 세는 건 의미가 없다. 총 시간만 본다.
    format     = "json"
    keep_alive = -1
    options    = @{ temperature = 0.0; num_ctx = 8192 }
} | ConvertTo-Json -Depth 6

$sw = [System.Diagnostics.Stopwatch]::StartNew()
try {
    $chatHeaders = $headers.Clone()
    $chatHeaders["Content-Type"] = "application/json"
    Invoke-RestMethod -Uri "$url/api/chat" -Method Post -Headers $chatHeaders `
        -Body $chatBody -TimeoutSec 300 | Out-Null
    $sw.Stop()
    $secs = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    Write-Host "      OK   총 ${secs}s"
    Write-Host "           이 호출은 stream=false 다. 100s를 넘으면 Cloudflare 프록시 read timeout(524)에"
    Write-Host "           걸리는 크기라는 뜻이고, 백엔드가 stream=true 를 쓰는 이유가 바로 그것이다."
    Write-Host "           240s를 넘으면 백엔드의 생성 타임아웃에도 걸린다."
} catch {
    $sw.Stop()
    $secs = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    Write-Host "      FAIL ${secs}s 후 실패: $_"
    $failed = 1
}

# --- 4. 임베딩 차원 -----------------------------------------------------------
Write-Host "[4/4] POST /api/embed -> 벡터 길이 $expectedDim"
try {
    $embedHeaders = $headers.Clone()
    $embedHeaders["Content-Type"] = "application/json"
    $embedBody = @{ model = $embedModel; input = @("테스트") } | ConvertTo-Json
    $emb = Invoke-RestMethod -Uri "$url/api/embed" -Method Post -Headers $embedHeaders `
        -Body $embedBody -TimeoutSec 120
    $dim = @($emb.embeddings[0]).Count
    if ($dim -eq $expectedDim) {
        Write-Host "      OK   $dim"
    } else {
        Write-Host "      FAIL 길이 $dim (기대: $expectedDim)"
        Write-Host "           1024가 아니면 컷오버를 중단한다. VECTOR(1024) 컬럼에 넣을 수 없어서"
        Write-Host "           사용자가 기록물을 올리는 순간 요청 도중에 EmbeddingDimensionMismatchError가 터진다."
        $failed = 1
    }
} catch {
    Write-Host "      FAIL /api/embed 실패: $_"
    $failed = 1
}

Write-Host ""
if ($failed -eq 0) {
    Write-Host "[OK] All 4 contract checks passed. Tunnel is working and the backend's contract holds."
} else {
    Write-Host "[FAIL] Contract checks failed."
    Show-Hints
}
exit $failed
