# A-5. Cloudflare Tunnel 설정 — 서버 운영 처음이어도 괜찮다

근거: 명세서 13-3절, 2-1절
선행 조건: [02_llm_adapter_layer.md](02_llm_adapter_layer.md)에서 로컬 LLM 연동이 어느 정도 동작 확인됨
브랜치: 별도 브랜치 없이 진행해도 무방(또는 `chore/cloudflare-tunnel`) — 대부분 PC 설정·`.env` 값 교체이고 저장소에 반영될 코드가 거의 없다
시점: 2주차 (급하지 않다 — 이 작업이 며칠 걸려도 서비스는 Gemini로 계속 동작한다)

> **개념부터**: "터널"은 당신의 PC 안에서만 열려 있는 `http://localhost:11434`(Ollama)를, 인터넷 어디서나 접속 가능한 `https://무언가` 주소로 바꿔주는 통로다. 클라우드에 있는 백엔드가 이 주소로 Ollama를 호출한다. 이 통로로는 Ollama 응답만 오갈 뿐 PC의 다른 부분에는 전혀 접근할 수 없다 (2-1절).

## 1. 준비

- [x] Windows용 `cloudflared.exe` 설치 — `winget install --id Cloudflare.cloudflared -e` (다운로드 페이지에서 받아도 무방)

## 2. 임시 방편으로 먼저 감 잡기 (선택, 권장)

- [x] 도메인이 없다면 로그인 없이 즉석 임시 주소를 받는 Quick Tunnel부터 시도: PowerShell에서
  ```
  cloudflared.exe tunnel --url http://localhost:11434 --http-host-header localhost:11434
  ```
  **`--http-host-header localhost:11434`가 필수다.** 이게 없으면 cloudflared가 터널 도메인(`*.trycloudflare.com`)을 그대로 Host 헤더로 넘기는데, Ollama가 DNS 리바인딩 방지를 위해 Host 헤더를 검사하다가 낯선 값이면 `403 Forbidden`으로 거부한다. 로컬(`localhost`)에서는 200이 오는데 터널을 거치면 403만 뜨는 현상의 원인이 이것이다.
- [x] 화면에 나온 `https://....trycloudflare.com` 주소를 브라우저로 열어 Ollama 응답("Ollama is running")이 오는지 확인
- [ ] **주의**: 이 주소는 실행할 때마다 바뀌므로 개발 중 임시 테스트용으로만 쓰고, 데모 당일에는 아래 고정 주소 방식을 쓴다

## 3. 고정 주소 설정 (데모용, 정식 절차)

- [ ] 로그인: `cloudflared.exe tunnel login` (브라우저에서 Cloudflare 계정 인증 — 계정 없으면 무료로 생성)
- [ ] 터널 생성: `cloudflared.exe tunnel create annswieteom-llm` → 출력된 터널 ID와 `.json` 인증 파일 경로를 기록해둔다
- [ ] `%USERPROFILE%\.cloudflared\config.yml` 파일 생성/작성:
  ```yaml
  tunnel: annswieteom-llm
  credentials-file: C:\Users\<사용자명>\.cloudflared\<터널ID>.json
  ingress:
    - hostname: <서브도메인>.<보유 도메인 또는 Cloudflare 제공 도메인>
      service: http://localhost:11434
      originRequest:
        httpHostHeader: localhost:11434   # 2번의 403 문제와 동일한 이유로 필수
    - service: http_status:404
  ```
- [ ] 도메인이 없다면 Cloudflare 무료 Zero Trust 대시보드 안내를 따라 도메인 연결 (또는 팀 상의 후 2번 Quick Tunnel로 당분간 대체) — **현재 `annswieteom.com` 도메인이 등록 기관에 실제로 등록되지 않은 상태로 확인됨(2026-09-02), 등록 확인 전까지는 Quick Tunnel로 대체**
- [ ] 실행: `cloudflared.exe tunnel run annswieteom-llm`

## 4. 외부 접속 확인 (중요 — PC 안에서 확인하는 것과 다르다)

- [ ] **다른 기기**(휴대폰을 Wi-Fi가 아닌 데이터로 연결)에서 설정한 `https://<주소>`로 접속해 Ollama 응답 확인 — PC 안에서 `localhost`로만 확인하면 진짜 외부 노출 여부를 알 수 없다

## 5. 자동 실행 등록 (재부팅 대비)

- [ ] 관리자 권한 PowerShell(PowerShell 아이콘 우클릭 → "관리자 권한으로 실행")에서: `cloudflared.exe service install`
- [ ] PC를 실제로 재부팅해서 터널이 자동으로 다시 켜지는지 확인

## 6. 백엔드 연동

- [ ] 발급된 주소를 `backend/.env`의 `LOCAL_LLM_BASE_URL`에 반영
- [ ] B에게 이 주소를 공유해 배포 환경(Railway) 환경변수에도 반영하도록 요청

## 7. Ollama 바인딩 주소 확인 (17절 트러블슈팅)

- [ ] 터널을 통한 접속이 실패하면 `OLLAMA_HOST=0.0.0.0` 환경변수를 설정하고 Ollama를 재시작 (기본 설정으로 보통 문제없지만 안 될 경우의 대응)
- [x] **터널을 통한 접속이 403 Forbidden으로 실패하면** (바인딩 문제가 아니라 Host 헤더 문제) — 2번/3번에서처럼 cloudflared에 `--http-host-header localhost:11434` 또는 `originRequest.httpHostHeader: localhost:11434`를 설정했는지 확인. 2026-09-02에 실제로 재현·해결됨

## 검증 기준

- [ ] 다른 기기에서 터널 고정 주소로 접속했을 때 Ollama 응답이 온다
- [ ] PC를 재부팅해도 Ollama, cloudflared 둘 다 사람이 손대지 않아도 자동으로 다시 켜진다
- [ ] 이후 [07_server_ops_checklist.md](07_server_ops_checklist.md)의 "처음 설정할 때" 항목을 모두 체크할 수 있다
