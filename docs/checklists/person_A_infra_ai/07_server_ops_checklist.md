# A-7. 서버 운영 체크리스트 (일상 점검 + 데모 대비)

근거: 명세서 19절, 17절
선행 조건: [05_cloudflare_tunnel.md](05_cloudflare_tunnel.md), [08_dgx_spark_migration.md](08_dgx_spark_migration.md) 완료
브랜치: 없음 — 운영 점검 체크리스트로, 코드 변경이 아니다
시점: 2주차부터 상시

이 문서는 코드를 몰라도 그대로 따라 하면 되는 운영 체크리스트다. 지금까지 만든 서버(DGX Spark의 Ollama + Cloudflare Tunnel)가 계속 잘 떠 있는지 확인하는 절차만 모아뒀다.

> **먼저 알아둘 것**: 추론 서버는 2026-09-10부터 **DGX Spark(Linux, DGX OS)**다. 그래서 아래 명령들은 Windows의 "서비스" 창이 아니라 `systemctl`·`journalctl`을 쓴다. 그리고 **폴백이 없다** — 이 서버가 죽으면 AI 기능 전체가 멈춘다(맨 아래 "기억할 것" 참고).

## 처음 설정할 때 (1회)

- [ ] Ollama가 떠 있고 `ollama list`에 **`qwen2.5:32b`와 `bge-m3`가 둘 다** 보인다 (`bge-m3`가 빠지면 임베딩이 조용히 전멸한다 — 08번 2절)
- [ ] Spark 안에서 `curl -s http://localhost:11434/`에 "Ollama is running"이 온다
- [ ] cloudflared가 `sudo cloudflared service install` + `sudo systemctl enable --now cloudflared`로 자동 실행 등록돼 있다
- [ ] **Spark가 아닌 다른 기기**(휴대폰 등)에서 터널 주소로 접속했을 때 응답이 온다 — Cloudflare Access를 켰으므로 토큰 없이는 **403이 정답**이다(1033/530이면 터널이 죽은 것)
- [ ] Spark에서 절전/서스펜드를 껐다 — `sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target`
- [ ] 터널 주소와 Access 토큰이 백엔드 `.env` / Render 환경변수에 반영돼 있다 (`LOCAL_LLM_BASE_URL`, `LLM_ACCESS_CLIENT_ID`, `LLM_ACCESS_CLIENT_SECRET`)
- [ ] [08_dgx_spark_migration.md](08_dgx_spark_migration.md) 4절의 **계약 검증 4항목**이 통과한다 (이게 "Ollama is running"보다 훨씬 중요하다)

## 매일 개발 시작 전 (습관처럼)

- [ ] Spark가 켜져 있고 인터넷에 연결돼 있다
- [ ] `curl -s http://localhost:11434/` 정상 응답 확인
- [ ] `ollama ps`로 `qwen2.5:32b`가 **상주 중**인지 확인 — 내려가 있으면 첫 요청이 재적재를 기다린다(72b는 적재만 15.5초였다, 실측)
- [ ] `GET /api/v1/health/llm`이 `llm_reachable`·`embedding_reachable` 둘 다 true (배포된 백엔드에서 확인 — Render → Cloudflare → Spark 경로를 한 번에 검사한다)
- [ ] (선택) 팀 채팅방에 "서버 켜짐" 정도만 짧게 공유

## 데모·투표 기간 시작 전날 (9/15~9/16 저녁, 매우 중요)

- [ ] Spark 전원·네트워크 케이블 연결 확인, 절전 설정 재확인
- [ ] Ollama, cloudflared 둘 다 **실제로 한 번 재부팅해서** 사람 손 없이 자동으로 켜지는지 테스트
- [ ] 재부팅 뒤 `ollama ps`로 운영 모델이 다시 웜업됐는지 확인 (웜업 훅이 도는지 확인하는 것)
- [ ] 08번 4절 계약 검증 4항목 재실행 — 특히 **임베딩 벡터 길이 1024**
- [ ] **터널을 일부러 잠깐 끊어, 웹앱이 폴백 없이도 *깨지지 않고* 끝나는지 확인** (B와 함께 — [00_shared/03_deployment.md](../00_shared/03_deployment.md) 4번 항목과 동일):
      AI 경로는 `503 llm_unavailable` + 화면에 "AI 서버가 수리 중이예요."가 떠야 하고, 500이나 무한 로딩이 되면 안 된다. 로그인·피드·아카이브 같은 **비-AI 경로는 그대로 동작해야** 한다. 그리고 터널을 되살리면 재배포 없이 회복돼야 한다.
- [ ] **롤백 경로 확인**: 4090을 내렸으므로 되돌아갈 기계가 없다. `ollama list`에 `qwen2.5:14b`가 있는지 확인하고, 롤백은 Render 환경변수 `LOCAL_LLM_MODEL_NAME`을 `qwen2.5:14b`로 바꿔 재시작하는 것 한 줄임을 팀이 알고 있는지 확인
- [ ] 데모 당일 Spark 근처에 있을 수 없는 시간대가 있다면 미리 팀에 공유

## 문제가 생겼을 때 (17절 트러블슈팅)

- [ ] **Ollama가 응답하지 않음**: 설치 방식에 맞게 상태 확인 — systemd면 `systemctl status ollama` / `sudo systemctl restart ollama`, snap이면 `snap services ollama` / `sudo snap restart ollama`. `ollama list`로 모델이 실제로 받아져 있는지도 확인
- [ ] **터널을 통한 접속이 403 Forbidden**: 인증 문제가 아니라면 `originRequest.httpHostHeader: localhost:11434`가 config에 있는지 확인 — Ollama가 낯선 `Host` 헤더를 거부하는 것이고, 이 프로젝트에서 두 번 겪었다. (Access 토큰 없이 보낸 요청이라면 403이 정상이다)
- [ ] **재부팅했더니 서버가 죽은 것 같다**: `curl localhost:11434`가 안 되면 Ollama가 꺼진 것 → `sudo systemctl restart ollama`(또는 `sudo snap restart ollama`). 외부 접속이 안 되면 터널이 꺼진 것 → `sudo systemctl restart cloudflared` 후 `journalctl -u cloudflared -n 50 --no-pager`로 커넥션이 실제로 등록되는지 확인
- [ ] **`systemctl is-active`는 `active`인데 외부에서 안 열린다**: 이 프로젝트에서 실제로 겪은 형태다. **"상태 표시"와 "실제 동작"은 다른 이야기다** — `journalctl`에 터널 커넥션 4개가 뜨는지, 그리고 외부에서 fresh curl로 응답이 오는지 **둘 다** 확인한다
- [ ] **터널 주소가 옛 터널을 가리킨다(에러 1033)**: DNS는 **터널 ID**를 가리켜야 한다(계정 ID·커넥터 ID와 헷갈리기 쉽다). `cloudflared tunnel route dns annswieteom-llm-spark llm.annswieteom.com --overwrite-dns`로 다시 지정
- [ ] **Cloudflare Tunnel 주소가 백엔드에서 안 열림**: Ollama가 `127.0.0.1`에만 바인딩된 경우다. systemd면 `sudo systemctl edit ollama`에 `Environment="OLLAMA_HOST=0.0.0.0:11434"`를 넣고 `daemon-reload` + 재시작, snap이면 `sudo snap set ollama host="0.0.0.0:11434"` 후 재시작
- [ ] **응답이 오지만 너무 느려 타임아웃 난다**: `nvidia-smi`로 GPU가 실제로 쓰이는지 확인(CPU 폴백이 가장 조용한 실패다). GPU가 정상인데도 느리면 대역폭 한계이므로 위의 롤백(14b)을 검토
- [ ] **확인할 때 캐시되는 도구를 쓰지 않는다**: 응답을 캐싱하는 fetch 도구 때문에 죽은 터널이 살아 있는 것처럼 보여 한 세션을 날린 적이 있다. 항상 fresh `curl`

## 기억할 것

**폴백이 없다.** 2026-09-09에 Gemini를 제거했으므로 이 서버가 죽으면 인터뷰·문서 생성·취업정보 검색이 전부 `503`으로 멈추고 화면에 "AI 서버가 수리 중이예요."가 뜬다. 웹앱 본체(로그인·세션 목록·피드)는 살아 있지만 서비스의 핵심 기능은 정지한다.

그래서 이 문서의 점검은 "해두면 좋은 것"이 아니라 **데모 당일 필수 항목**이다. 대신 확인 절차 자체는 단순하다 — 위 항목을 위에서부터 하나씩, 시간을 넉넉히 두고 짚으면 된다.
