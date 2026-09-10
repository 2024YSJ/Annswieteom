# A-8. 추론 서버를 DGX Spark로 이관

근거: 명세서 2-1절, 13-3절, 17절, 19절
선행 조건: [05_cloudflare_tunnel.md](05_cloudflare_tunnel.md) 1~7번(개발용 PC에서 검증된 절차와 거기서 겪은 두 가지 함정)을 읽어둘 것
브랜치: `feature/dgx-spark-migration`
시점: 2026-09-10 ~ 기능 동결(9/16) 전까지 — 이게 마지막 인프라 작업이다

> **개념부터**: 바뀌는 건 "Ollama가 도는 컴퓨터" 하나다. 백엔드가 보는 주소(`https://llm.annswieteom.com`)는 그대로 두고, 그 주소가 가리키는 터널만 새 기계의 터널로 갈아끼운다. 그래서 Render 환경변수의 주소도, 프론트엔드도 건드릴 필요가 없다. 대신 새 기계는 Windows가 아니라 **Linux(DGX OS, ARM64)**라, 자동 실행 등록이 `cloudflared.exe service install` + 레지스트리가 아니라 `systemd`다.

---

## 0. 시작 전에 반드시 읽을 것 — 롤백 경로가 없다

**폴백 프로바이더가 없다.** 2026-09-09에 Gemini를 제거했으므로 이 서버가 닿지 않으면 인터뷰·문서 생성·취업정보 검색이 전부 `503 llm_unavailable`로 멈추고 화면에 "AI 서버가 수리 중이예요."가 뜬다. 그리고 이번 이관에서는 **RTX 4090 PC를 그대로 내리기 때문에 하드웨어로 되돌아갈 길이 없다.**

그래서 롤백은 "다른 기계로 DNS를 되돌리는 것"이 아니라 **"같은 Spark 위에서 더 작은 모델로 내려앉는 것"**이다. 이게 성립하려면 작은 모델이 미리 받아져 있어야 한다.

- [ ] 2번에서 `qwen2.5:14b`를 **함께** pull한다 (롤백 전용)
- [ ] 롤백 절차 — 데모 중 압박 상황에서 찾아 헤매지 않도록 여기 그대로 적어둔다:
      Render 환경변수 `LOCAL_LLM_MODEL_NAME`을 `qwen2.5:14b`로 바꾸고 서비스 재시작. 그게 전부다(코드 변경도 재배포도 없다).
- [ ] 4090을 내리기 **전에** `ollama list`와 `ollama show --modelfile qwen2.5:14b`의 출력을 devlog에 적어둔다. 기계를 지운 뒤에는 얻을 수 없는 정보다.

---

## 1. Spark 사전 확인

- [ ] `uname -m` → `aarch64` (x86 바이너리는 안 돌아간다 — cloudflared도 arm64 빌드를 받아야 한다)
- [ ] `nvidia-smi` → GB10이 보이고 드라이버가 올라와 있다
- [ ] `cat /etc/os-release`로 DGX OS 버전 기록
- [ ] 유선 네트워크로 연결돼 있다
- [ ] 절전/서스펜드가 꺼져 있다 — `sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target`
- [ ] 사람이 로그인하지 않아도 서비스가 뜬다 (5·6번에서 실제 재부팅으로 확인)

## 2. Ollama와 모델

Ollama는 이미 설치돼 있다. **설치 방식을 먼저 확인한다.** NVIDIA 포럼에는 snap 사전설치로 적혀 있지만 **우리 기계는 snap이 아니었다** — `sudo snap set ollama host=...`가 "스냅 ollama 을(를) 찾을 수 없습니다"로 실패했다(2026-09-10 실측). 어느 쪽이든 **공식 `install.sh`로 갈아엎지 말 것**: GB10(SM121)용 CUDA 설정을 잃을 수 있다.

- [ ] 설치 방식 확인:
  ```bash
  command -v ollama && ollama --version
  systemctl list-unit-files | grep -i ollama
  snap list ollama 2>/dev/null
  docker ps --format '{{.Names}}\t{{.Image}}' 2>/dev/null | grep -i ollama
  ```
- [ ] `curl -s http://localhost:11434/`가 이미 "Ollama is running"이면 **바인딩은 건드리지 않는다.** cloudflared는 같은 기계에서 `localhost:11434`로 붙으므로 `127.0.0.1` 바인딩이어도 통한다 — `0.0.0.0`은 터널이 안 될 때 꺼내는 카드다(9절 트러블슈팅).
- [ ] 바꿔야 할 때만, 설치 방식에 맞춰:
  - **systemd**: `EDITOR=nano sudo -E systemctl edit ollama` → `[Service]` 아래 `Environment="OLLAMA_HOST=0.0.0.0:11434"` → `sudo systemctl daemon-reload && sudo systemctl restart ollama` → `systemctl show ollama -p Environment`로 확인
  - **snap**: `sudo snap set ollama host="0.0.0.0:11434"` → `sudo snap restart ollama` (snap 설치본은 유닛 파일이 없어 `systemctl edit`이 먹지 않는다)
- [ ] 모델 받기 — **두 개가 아니라 세 개다**:
  ```bash
  ollama pull qwen2.5:32b     # 추론
  ollama pull bge-m3          # 임베딩 (아래 경고 참고)
  ollama pull qwen2.5:14b     # 0번의 롤백용
  ollama list
  ```
- [ ] **`bge-m3`를 빼먹으면 조용히 망한다.** 이 모델 이름은 환경변수가 아니라 코드에 하드코딩돼 있고(`backend/app/services/embedding/local_ollama_embedding.py`), 그 출력 차원 1024는 DB의 `VECTOR(1024)` 컬럼 타입이다. 없으면 기록물 임베딩과 피드 맞춤 정렬이 **예외를 던지지 않고** 실패한다 — "정렬이 좀 이상하다" 정도로만 보인다. 실제로 한 번 당했다(`docs/devlog/Step2/05_local_dev_split_and_the_interview_loop_bugs.md`).
- [ ] 추론 모델과 `bge-m3`가 서로를 밀어내지 않게 동시 상주 한도를 2 이상으로 둘 수 있으면 둔다(systemd면 `OLLAMA_MAX_LOADED_MODELS=2`). 안 되면 넘어간다 — 백엔드가 요청마다 `keep_alive`를 실어 보내므로 모델이 상주한다.
- [ ] `OLLAMA_NUM_PARALLEL`은 **건드리지 않는다.** 1보다 크게 두면 `docs/architecture.md`의 "로컬 Ollama는 요청을 직렬 처리한다"는 전제와 취업정보 검색의 전체 시간 예산이 무효가 되고, 둘 다 재측정해야 한다.

## 3. GPU가 실제로 쓰이는지 확인 (가장 조용한 실패)

CPU로 폴백해 도는 것은 에러 없이 그냥 10배 느려지는 형태로 나타난다.

- [ ] 4번의 추론 호출을 돌리는 **동안** 다른 터미널에서 `nvidia-smi`(또는 `tegrastats`)로 GPU 사용률이 실제로 올라가는지 본다
- [ ] 안 올라가면 여기서 멈추고 런타임을 먼저 고친다. 터널을 뚫는 건 그다음이다.

## 4. 계약 검증 — 터널 뚫기 전에, localhost에서

"Ollama is running"은 데몬이 답한다는 증거일 뿐 **데모가 돌아간다는 증거가 아니다.** 백엔드가 실제로 의존하는 4가지를 확인한다. 저장소 루트의 [`infra/cloudflare/verify_tunnel.sh`](../../../infra/cloudflare/verify_tunnel.sh)가 이 4개를 자동화해 둔 것이니 그걸 써도 된다.

- [ ] `GET /` 에 `Ollama is running`
- [ ] `GET /api/tags` 에 `qwen2.5:32b`**와 `bge-m3`가 둘 다** 보인다
- [ ] `POST /api/chat`을 **백엔드와 똑같은 페이로드 형태**로 보내 성공하고, **첫 바이트까지 걸린 시간과 총 시간을 잰다**:
  ```bash
  time curl -sN http://localhost:11434/api/chat -d '{
    "model":"qwen2.5:32b",
    "messages":[{"role":"system","content":"Output JSON only."},{"role":"user","content":"안녕"}],
    "stream":true,"format":"json","keep_alive":-1,
    "options":{"temperature":0.0,"num_ctx":8192}}'
  ```
- [ ] `POST /api/embed`의 벡터 길이가 **정확히 1024**다:
  ```bash
  curl -s http://localhost:11434/api/embed -d '{"model":"bge-m3","input":["테스트"]}' \
    | python3 -c "import json,sys;print(len(json.load(sys.stdin)['embeddings'][0]))"
  ```
  1024가 아니면 **여기서 중단한다.** 넘어가면 사용자가 기록물을 올리는 순간 요청 도중에 `EmbeddingDimensionMismatchError`가 터진다.
- [ ] 가장 큰 프롬프트로 한 번 더 재본다 — 취업정보 후보 40건을 넣는 `select_relevant_job_info_results`가 이 프로젝트에서 제일 긴 프롬프트다. 여기서 나온 시간이 데모 go/no-go와 `num_ctx` 조정 여부를 동시에 결정한다.
- [ ] 위 측정값(첫 바이트 초 / 총 초 / 대략의 tok/s)을 `docs/devlog/PersonA/08_dgx_spark_migration.md`에 적는다.

  **2026-09-10 실측 기준값** (같은 기계, 같은 페이로드). 대역폭(273GB/s)이 decode 벽이라 속도가 모델 크기에 거의 반비례한다:

  | 모델 | decode | 문단 3개 문서(844토큰) | 콜드 적재 |
  |---|---|---|---|
  | `qwen2.5:72b` | 3.0 tok/s | **4분 42초** — 카테고리 하나가 타임아웃 240초를 넘겼다 | 15.5초 |
  | `qwen2.5:32b` | 약 13 tok/s | **1분 3초**(웜) / 1분 30초(콜드 포함) — 타임아웃 240초 안에 넉넉히 들어온다 | (기입) |

  재본 값이 위 표보다 **한 자리** 낮으면 모델 문제가 아니라 3번(GPU 미사용)이다.

## 5. cloudflared 설치와 터널 (ARM64 Linux)

- [ ] arm64 패키지로 설치:
  ```bash
  curl -fsSL -o /tmp/cloudflared.deb \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
  sudo dpkg -i /tmp/cloudflared.deb && cloudflared --version
  ```
- [ ] `cloudflared tunnel login` — 기존과 **같은 Cloudflare 계정**으로. **`tunnel create`보다 먼저 해야 한다** — 안 하면 `Cannot determine default origin certificate path. No file cert.pem`으로 실패한다(2026-09-10에 실제로 겪음).
  - SSH 접속이면 브라우저가 안 뜨고 URL만 출력된다. 그 URL을 **노트북 브라우저에 복사해** 열고 `annswieteom.com` 존을 승인한다.
  - **`sudo`를 붙이지 않는다.** `sudo`로 login하면 `cert.pem`이 `/root/.cloudflared/`에 생겨서, `sudo` 없이 실행한 `tunnel create`가 다시 못 찾는다. login과 create는 같은 사용자로 하고, `sudo`가 필요한 건 뒤의 `service install`뿐이다.
  - `ls -l ~/.cloudflared/cert.pem`으로 생성 확인
- [ ] `cloudflared tunnel create annswieteom-llm-spark` — 기존 터널(`annswieteom-llm`, `annswieteom-llm-main`)과 이름을 일부러 다르게 둔다. 터널 ID와 자격증명 `.json` 경로를 기록.
- [ ] 자격증명을 시스템 위치로 옮긴다 (서비스가 사용자 홈에 의존하지 않게):
  ```bash
  sudo mkdir -p /etc/cloudflared
  sudo cp ~/.cloudflared/<TUNNEL_ID>.json /etc/cloudflared/
  ```
- [ ] `/etc/cloudflared/config.yml` 작성 — 템플릿은 [`infra/cloudflare/config.linux.yml.example`](../../../infra/cloudflare/config.linux.yml.example). **`originRequest.httpHostHeader`를 처음부터 넣는다** (05번 2·3번에서 두 번 겪은 403의 원인이다):
  ```yaml
  tunnel: annswieteom-llm-spark
  credentials-file: /etc/cloudflared/<TUNNEL_ID>.json
  ingress:
    - hostname: llm.annswieteom.com
      service: http://localhost:11434
      originRequest:
        httpHostHeader: localhost:11434
    - service: http_status:404
  ```
- [ ] DNS를 새 터널로 덮어쓴다 — `llm.annswieteom.com`은 지금 옛 터널을 가리키므로 `--overwrite-dns`가 필요하다:
  ```bash
  cloudflared tunnel route dns annswieteom-llm-spark llm.annswieteom.com --overwrite-dns
  ```
- [ ] DNS는 **터널 ID**를 가리켜야 한다. Cloudflare 화면에는 계정 ID / 터널 ID / 커넥터 ID 세 개의 비슷하게 생긴 문자열이 있고, 이걸 헷갈려 1033 에러로 두 번 헤맨 적이 있다(`docs/devlog/Step2/01_from_engine_to_the_real_world.md`).

## 6. systemd 등록 (재부팅 대비)

Linux의 `service install`은 config를 읽어 인자가 제대로 들어간 유닛을 만들어준다 — Windows에서 겪은 "레지스트리 ImagePath에 인자가 없어 서비스가 즉시 종료" 함정은 여기선 없다. 하지만 **"상태 표시"와 "실제 동작"이 다르다는 교훈 자체는 그대로 적용된다.**

- [ ] 등록·기동:
  ```bash
  sudo cloudflared --config /etc/cloudflared/config.yml service install
  sudo systemctl enable --now cloudflared
  ```
- [ ] `journalctl -u cloudflared -n 50 --no-pager`에 **터널 커넥션 4개가 실제로 등록**되는지 확인
- [ ] `systemctl is-active`가 `active`인 것만으로 판단하지 않는다 — 위 로그 확인과 8번의 외부 요청을 **둘 다** 통과해야 켜진 것이다

## 7. Cloudflare Access 서비스 토큰

지금까지 `llm.annswieteom.com`은 **인증이 전혀 없는 공개 Ollama API**였다. 주소를 아는 사람은 누구나 우리 GPU로 추론을 돌리거나 `/api/pull`·`/api/delete`로 모델을 건드릴 수 있었다. 이관하면서 막는다.

- [ ] Zero Trust → Access → **Service Auth** → Create Service Token → Client ID / Client Secret 발급 (**Secret은 한 번만 보인다**)
- [ ] Zero Trust → Access → Applications → Add → **Self-hosted**, 도메인 `llm.annswieteom.com`
- [ ] Policy의 Action을 **Service Auth**로 설정 — `Allow`로 두면 브라우저는 IdP 로그인 화면으로 가고, 백엔드 같은 비브라우저 클라이언트는 302로 떨어진다
- [ ] 백엔드에 값을 넣는다: `backend/.env`와 Render 환경변수의 `LLM_ACCESS_CLIENT_ID`, `LLM_ACCESS_CLIENT_SECRET`
- [ ] 이 토큰을 **채팅창·커밋·devlog에 붙여넣지 않는다.** 이 프로젝트는 터널 토큰과 DB 비밀번호를 대화 기록에 노출해 재발급한 사고가 이미 있었다.

## 8. 외부 검증 (Spark 안에서 확인하는 것과 다르다)

- [ ] **Spark가 아닌 기기에서** 인증 없이 요청 → **403이 오면 정상이다**(Access가 켜졌다는 증거):
  ```bash
  curl -si https://llm.annswieteom.com/api/tags | head -1
  ```
- [ ] 토큰을 붙여 요청 → 200:
  ```bash
  curl -si -H "CF-Access-Client-Id: $ID" -H "CF-Access-Client-Secret: $SECRET" \
       https://llm.annswieteom.com/api/tags | head -1
  ```
- [ ] **반드시 fresh curl로 확인한다.** 응답을 캐싱하는 도구는 쓰지 않는다 — 15분 캐시 때문에 이미 죽은 터널이 살아 있는 것처럼 보여 디버깅 한 세션을 통째로 날린 기록이 있다(`docs/devlog/PersonA/05_cloudflare_tunnel.md`).
- [ ] Windows 노트북에서 [`infra/cloudflare/verify_tunnel.ps1`](../../../infra/cloudflare/verify_tunnel.ps1)을 토큰과 함께 실행 — 운영자가 실제로 쓰는 기계에서 외부 경로가 되는지 확인하는 용도다
- [ ] **Spark를 실제로 재부팅**하고, 사람이 아무것도 하지 않은 상태에서 위 요청이 다시 200이 되는지 확인
- [ ] 휴대폰을 **Wi-Fi가 아닌 데이터망**으로 바꿔 접속 — 진짜 공개 인터넷에 있다는 유일한 증거다. Access를 켠 뒤라 기대값은 200이 아니라 **403**이다(1033이나 530이 아니면 통과)

## 9. 백엔드 연동

- [ ] `LOCAL_LLM_BASE_URL`은 **바뀌지 않는다** — 같은 호스트명을 재사용하는 게 이 방식의 요점이다. Render 재배포도 불필요.
- [ ] Render 환경변수: `LOCAL_LLM_MODEL_NAME=qwen2.5:32b`, `LLM_ACCESS_CLIENT_ID`, `LLM_ACCESS_CLIENT_SECRET`
- [ ] Render에 `GEMINI_API_KEY`나 `LLM_PROVIDER_ORDER`가 **남아 있지 않은지 확인.** 등록하는 항목이 아니라 *삭제됐는지 확인하는* 항목이다 — pydantic-settings가 기본 `extra="forbid"`라 남아 있으면 컨테이너 부팅 자체가 실패한다.
- [ ] 헬스 엔드포인트로 **Render → Cloudflare → Spark 경로 전체**를 한 번에 확인:
  ```bash
  curl -s https://<render-url>/api/v1/health/llm
  ```
  노트북에서 터널로 직접 쏘는 curl은 *다른* 네트워크 경로를 검사한다는 점에 주의.

## 10. 4090 정리 (Spark 검증이 전부 끝난 뒤에만)

- [ ] 0번의 `ollama list` / `ollama show --modelfile` 기록이 devlog에 남아 있는지 먼저 확인
- [ ] cloudflared 중지·제거: `Stop-Service cloudflared` → 서비스 제거
- [ ] 옛 터널 삭제: `cloudflared tunnel delete annswieteom-llm`, `cloudflared tunnel delete annswieteom-llm-main`
- [ ] 그 PC의 `~/.cloudflared/*.json`을 지운다 — **자격증명 파일이다.** 기계를 넘기거나 초기화하기 전에 삭제
- [ ] `infra/cloudflare/config.yml.example`(Windows용)과 문서의 Windows 절 정리는 **9/21 이후에** 한다 — 데모 기간에는 참고 자료로 남겨둔다

---

## 검증 기준

- [ ] 4번의 4가지 계약 검사가 Spark 로컬에서 모두 통과한다 (특히 임베딩 길이 1024)
- [ ] 3번에서 GPU가 실제로 쓰이는 것을 눈으로 확인했다
- [ ] Spark가 아닌 기기에서 토큰 없이는 403, 토큰과 함께는 200이 온다
- [ ] Spark를 재부팅해도 Ollama와 cloudflared가 사람 손 없이 돌아온다
- [ ] `GET /api/v1/health/llm`이 `llm_reachable`·`embedding_reachable` 둘 다 true를 준다
- [ ] 브라우저로 한 세션을 처음부터 끝까지 완주했고, 정상 흐름에서 "AI 서버가 수리 중이예요."가 한 번도 뜨지 않았다
- [ ] `POST /{session_id}/generate`의 실측 시간을 재서 devlog에 적었다
- [ ] 이후 [07_server_ops_checklist.md](07_server_ops_checklist.md)의 "처음 설정할 때" 항목을 모두 체크할 수 있다

> **`pytest`가 전부 초록인 것은 이 이관의 검증이 아니다.** `backend/tests/api/conftest.py`가 LLM·임베딩 프로바이더를 전 API 테스트에서 가짜로 바꿔치기하므로, Spark가 존재하든 안 하든 스위트는 똑같이 통과한다. 실제로 이미지 OCR이 완전히 깨진 상태로 테스트 232개가 전부 통과한 전례가 있다(`docs/devlog/PersonB/24_remove_gemini_no_fallback.md`). 이 문서의 검증 기준은 전부 사람이 직접 확인하는 항목이다.
