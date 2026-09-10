# A-5. Cloudflare Tunnel 설정 — 서버 운영 처음이어도 괜찮다

근거: 명세서 13-3절, 2-1절
선행 조건: [02_llm_adapter_layer.md](02_llm_adapter_layer.md)에서 로컬 LLM 연동이 어느 정도 동작 확인됨
브랜치: 별도 브랜치 없이 진행해도 무방(또는 `chore/cloudflare-tunnel`) — 대부분 PC 설정·`.env` 값 교체이고 저장소에 반영될 코드가 거의 없다
시점: 2주차 (급하지 않다 — 이 작업이 며칠 걸려도 서비스는 Gemini로 계속 동작한다)

> **개념부터**: "터널"은 당신의 PC 안에서만 열려 있는 `http://localhost:11434`(Ollama)를, 인터넷 어디서나 접속 가능한 `https://무언가` 주소로 바꿔주는 통로다. 클라우드에 있는 백엔드가 이 주소로 Ollama를 호출한다. 이 통로로는 Ollama 응답만 오갈 뿐 PC의 다른 부분에는 전혀 접근할 수 없다 (2-1절).

> ⚠️ **2026-09-02 작업 관련 중요 정정**: 아래 1~5·7번의 `[x]` 항목들은 전부 **실제 서버 PC(RTX 4090)가 아니라 별도의 개발용 PC/노트북**에서 진행·검증된 것이다. 그 개발용 PC의 Ollama에는 `qwen2.5:14b`/`bge-m3`가 아니라 `phi3.5`, `llama3.2:3b`, `qwen2.5:3b-instruct` 같은 가벼운 모델만 있었다. 즉 지금 살아있는 `https://llm.annswieteom.com` 터널은 **진짜 서버가 아니라 개발용 PC를 가리키고 있다.** 아래 절차 자체와 겪은 문제(403, 서비스 위장 문제)는 실제 서버 PC에서도 동일하게 적용되므로 그대로 재사용하면 되지만, **실제 서버 PC에서 별도로 한 번 더 진행해야 한다** — 8번 섹션에 정리해둔 순서를 따를 것.

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

- [x] 로그인: `cloudflared.exe tunnel login` (브라우저에서 Cloudflare 계정 인증 — 계정 없으면 무료로 생성)
- [x] 터널 생성: `cloudflared.exe tunnel create annswieteom-llm` → 터널 ID `d86a0ab3-4497-4d9b-80b9-ac4d2f1fc9ec`, 인증 파일 `C:\Users\sjyoo\.cloudflared\d86a0ab3-4497-4d9b-80b9-ac4d2f1fc9ec.json`
- [x] `%USERPROFILE%\.cloudflared\config.yml` 파일 생성/작성:
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
- [x] 도메인 등록 완료 확인(2026-09-02, RDAP·DNS 재확인) → `annswieteom.com`을 Cloudflare Registrar로 구매, 네임서버 자동 연결됨. `cloudflared tunnel route dns annswieteom-llm llm.annswieteom.com`으로 CNAME 자동 생성
- [x] 실행: `cloudflared.exe tunnel run annswieteom-llm` → 이후 5번에서 서비스로 전환

## 4. 외부 접속 확인 (중요 — PC 안에서 확인하는 것과 다르다)

- [x] `https://llm.annswieteom.com` 외부(Cloudflare 엣지 경유) 요청에서 "Ollama is running" 응답 확인(2026-09-02)
- [x] 휴대폰(데이터망)으로 실기기 접속 확인 완료(2026-09-02)

## 5. 자동 실행 등록 (재부팅 대비)

- [x] 관리자 권한으로 `cloudflared.exe service install` 실행 → Windows 서비스 `cloudflared` 등록됨
- [x] **중요한 함정**: `service install`(인자 없이)이 등록하는 서비스의 실행 명령은 그냥 `cloudflared.exe`뿐이다. 이 상태로 서비스를 시작하면 실제로는 터널을 켜지 않고 `use 'cloudflared tunnel run' to start tunnel ...` 힌트만 출력하고 즉시 종료된다 — Windows 서비스 관리자는 이를 "비정상 종료"로 판단해 재시작을 반복하다 결국 `Stopped`로 멈춘다. **서비스 상태가 `Running`으로 보여도 실제 터널 연결이 없을 수 있으니 반드시 외부 접속으로 확인해야 한다** (겉보기 `Running` 상태만 믿지 말 것 — 2026-09-02에 실제로 이 상태에서 외부 접속 시 오류 1033 재현됨).
  해결: 레지스트리에서 서비스 실행 명령을 명시적으로 지정
  ```powershell
  Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\cloudflared' -Name ImagePath `
    -Value '"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --config "C:\Users\<사용자명>\.cloudflared\config.yml" --logfile "C:\Users\<사용자명>\.cloudflared\service.log" run annswieteom-llm'
  Restart-Service cloudflared
  ```
  (`sc.exe config cloudflared binPath= ...`로 시도하면 PowerShell의 네이티브 인자 따옴표 처리 때문에 값이 깨질 수 있다 — 레지스트리를 직접 쓰는 쪽이 더 안전했다.) 수정 후 `service.log`에 4개의 tunnel connection이 등록되는 것과 외부에서 실제 200 응답이 오는 것까지 확인 완료.
- [x] PC를 실제로 재부팅해서 터널이 자동으로 다시 켜지는지 확인 — 완료(2026-09-02), 자동 기동 정상 확인

## 6. 백엔드 연동

- [ ] `LOCAL_LLM_BASE_URL=https://llm.annswieteom.com`을 `backend/.env`에 반영 — **`backend/.env`가 아직 생성되지 않음**(B의 백엔드 스캐폴딩 대기 중). 파일이 생기면 이 값으로 채울 것. ⚠️ 지금 이 주소는 8번에서 실제 서버 PC 작업이 끝나기 전까지는 개발용 PC를 가리킨다 — B에게 전달하기 전에 8번을 먼저 완료할 것
- [ ] B에게 `https://llm.annswieteom.com` 주소를 공유해 배포 환경(Render) 환경변수에도 반영하도록 요청 — **아직 전달 안 함**

## 7. Ollama 바인딩 주소 확인 (17절 트러블슈팅)

- [ ] 터널을 통한 접속이 실패하면 `OLLAMA_HOST=0.0.0.0` 환경변수를 설정하고 Ollama를 재시작 (기본 설정으로 보통 문제없지만 안 될 경우의 대응)
- [x] **터널을 통한 접속이 403 Forbidden으로 실패하면** (바인딩 문제가 아니라 Host 헤더 문제) — 2번/3번에서처럼 cloudflared에 `--http-host-header localhost:11434` 또는 `originRequest.httpHostHeader: localhost:11434`를 설정했는지 확인. 2026-09-02에 실제로 재현·해결됨

## 8. 실제 서버 PC(RTX 4090)에서 재진행 — 중요

10번 줄의 정정 안내대로, 1~5·7번은 **개발용 PC**에서 검증된 것이고 **실제 서버 PC에서는 아직 아무것도 안 한 상태**다. 여기서는 오늘 겪었던 두 문제(403, 서비스 위장)를 처음부터 피해가도록 순서를 다시 정리해둔다 — 이 순서대로 하면 개발 PC에서처럼 헤맬 일이 없다.

- [ ] 실제 서버 PC에 Ollama 설치 확인, `qwen2.5:14b`(또는 최종 선택한 모델)와 `bge-m3` 둘 다 받아져 있는지 `ollama list`로 확인
- [ ] 서버 PC에 `cloudflared` 설치(`winget install --id Cloudflare.cloudflared -e`)
- [ ] `cloudflared tunnel login` — 개발 PC와 같은 Cloudflare 계정으로 로그인
- [ ] **터널은 개발용과 이름을 다르게 새로 만든다**: `cloudflared tunnel create annswieteom-llm-main` (개발 PC의 `annswieteom-llm`은 그대로 남겨두고 헷갈리지 않게 구분)
- [ ] `config.yml` 작성 — **처음부터 `originRequest.httpHostHeader: localhost:11434`를 포함**(3번의 403 문제를 애초에 겪지 않도록):
  ```yaml
  tunnel: annswieteom-llm-main
  credentials-file: C:\Users\<사용자명>\.cloudflared\<터널ID>.json
  ingress:
    - hostname: llm.annswieteom.com
      service: http://localhost:11434
      originRequest:
        httpHostHeader: localhost:11434
    - service: http_status:404
  ```
- [ ] DNS 연결: `cloudflared tunnel route dns annswieteom-llm-main llm.annswieteom.com --overwrite-dns` — `llm.annswieteom.com`은 지금 개발 PC의 터널을 가리키고 있으므로 `--overwrite-dns` 옵션으로 이 서버 PC의 터널로 덮어써야 한다(플래그 없이 실행하면 이미 레코드가 있다고 에러가 날 수 있다)
- [ ] `cloudflared tunnel run annswieteom-llm-main`으로 실행 후 `https://llm.annswieteom.com`에서 fresh curl(캐시된 도구 응답 말고 실제 재요청)로 200 확인
- [ ] 관리자 권한으로 서비스 등록은 **`service install`에 의존하지 말고 처음부터 레지스트리에 명령을 명시**(5번의 위장 문제를 애초에 겪지 않도록):
  ```powershell
  cloudflared.exe service install
  Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\cloudflared' -Name ImagePath `
    -Value '"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --config "C:\Users\<사용자명>\.cloudflared\config.yml" --logfile "C:\Users\<사용자명>\.cloudflared\service.log" run annswieteom-llm-main'
  Restart-Service cloudflared
  ```
- [ ] `service.log`에 tunnel connection이 실제로 등록됐는지, 그리고 fresh curl로 외부 응답이 오는지 **둘 다** 확인 (`Get-Service`가 `Running`으로 보이는 것만으로는 부족하다)
- [ ] 실제로 재부팅해서 자동 기동 확인
- [ ] 휴대폰 데이터망으로 실기기 접속 확인
- [ ] 여기까지 끝나면 6번(백엔드 연동)의 URL 공유를 진행

## 검증 기준

- [x] (개발용 PC 기준) 다른 기기에서 터널 고정 주소로 접속했을 때 Ollama 응답이 온다 — 2026-09-02, fresh curl 및 휴대폰 실기기 모두 확인
- [x] (개발용 PC 기준) PC를 재부팅해도 Ollama, cloudflared 둘 다 사람이 손대지 않아도 자동으로 다시 켜진다 — 2026-09-02 실제 재부팅으로 확인
- [ ] **(실제 서버 PC 기준) 위 두 항목을 8번 순서대로 서버 PC에서 다시 확인 — 아직 미완료, 진짜 완료 기준은 이것**
- [ ] 이후 [07_server_ops_checklist.md](07_server_ops_checklist.md)의 "처음 설정할 때" 항목을 모두 체크할 수 있다 — 6번(백엔드 연동)과 8번(실서버)이 아직 열려 있어 전체 완료는 아님
