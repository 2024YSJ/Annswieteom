# Cloudflare Tunnel + Ollama 동작 확인 스크립트
# 사용법: .\infra\cloudflare\verify_tunnel.ps1 -TunnelUrl https://llm.example.com
#
# 외부 기기에서 실행할 것 — 같은 PC 안에서는 localhost로 직접 연결돼
# 터널이 실제로 외부에 노출됐는지 확인할 수 없다.

param(
    [Parameter(Mandatory=$true)]
    [string]$TunnelUrl
)

$url = $TunnelUrl.TrimEnd("/")

Write-Host "Checking Ollama via tunnel: $url"

try {
    $response = Invoke-RestMethod -Uri "$url/" -Method Get -TimeoutSec 10
    Write-Host "Response: $response"
    if ($response -match "Ollama is running") {
        Write-Host "[OK] Tunnel is working. Ollama is reachable from outside."
    } else {
        Write-Host "[WARN] Got a response but it doesn't look like Ollama."
    }
} catch {
    Write-Host "[FAIL] Cannot reach $url"
    Write-Host "Error: $_"
    Write-Host ""
    Write-Host "Checklist:"
    Write-Host "  1. Is cloudflared running? (check Services or Task Manager)"
    Write-Host "  2. Is Ollama running? (ollama ps)"
    Write-Host "  3. Is OLLAMA_HOST=0.0.0.0 set? (needed if cloudflared can't reach localhost)"
    Write-Host "  4. Is the tunnel name in config.yml correct?"
}
