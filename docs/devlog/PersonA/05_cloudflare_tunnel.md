# A-5. Cloudflare Tunnel 설정 devlog

체크리스트: `docs/checklists/person_A_infra_ai/05_cloudflare_tunnel.md`
날짜: 2026-09-02
후속: 2026-09-10에 추론 서버를 DGX Spark로 교체하면서 이 문서의 "실제 서버 PC에서 재진행" 과제는 4090이 아니라 Spark 기준으로 다시 쓰였다 → [08_dgx_spark_migration.md](08_dgx_spark_migration.md). 여기서 찾아낸 두 함정(403 Host 헤더, 서비스는 Running인데 터널은 죽음)은 Linux에서도 그대로 유효하고 그쪽 문서가 이어받았다.

---

## 프로젝트 명칭 철자 통일

`annswieoteum`(오탈자) / `Annswieteom` / `annswieteum` 등 파일마다 철자가 갈려 있던 것을 `annswieteom`으로 통일했다. `docs/specs/annswieoteum_detailed_spec.md` → `docs/specs/annswieteom_detailed_spec.md`로 파일명도 변경하고 이를 참조하던 링크(CLAUDE.md, 체크리스트 README 2곳)를 함께 수정했다. 터널 이름도 향후 `annswieteom-llm`으로 통일해서 생성한다.

## 도메인(`annswieteom.com`) 미등록 확인

Cloudflare 대시보드에는 `annswieteom.com` 존이 "네임서버 전파 대기 중"으로 떠 있었지만, RDAP(Verisign)·Google DNS-over-HTTPS 두 경로 모두 `NXDOMAIN`/`404`로 응답해 실제로는 등록되지 않은 도메인으로 확인됨(Cloudflare는 미등록 도메인도 존으로 추가하는 걸 막지 않는다). 철자 변형(`annswieoteum.com`, `annswieteum.com`)도 함께 확인했으나 전부 미등록 — 단순 오탈자 문제가 아니라 등록 기관 쪽 결제/등록 자체가 완료되지 않았을 가능성이 높다. 등록 기관 계정 확인은 사람이 직접 해야 하는 일이라 팀에 확인 요청함.

## Quick Tunnel 검증 중 403 Forbidden 재현 및 해결

cloudflared를 `winget install --id Cloudflare.cloudflared`로 설치하고 Quick Tunnel(`cloudflared tunnel --url http://localhost:11434`)을 처음 그대로 실행했더니, 로컬(`curl http://localhost:11434`)은 200인데 발급된 `https://*.trycloudflare.com` 주소로 외부에서 접근하면 **403 Forbidden**이 발생했다.

원인: Ollama가 DNS 리바인딩 방지를 위해 요청의 `Host` 헤더를 검사하는데, cloudflared가 터널 도메인(`*.trycloudflare.com`)을 그대로 오리진에 전달하기 때문에 Ollama가 낯선 Host로 판단해 거부한다. `curl -H "Host: <터널도메인>" http://localhost:11434/`로 로컬에서 재현 확인.

해결: `cloudflared`의 `--http-host-header` 플래그로 Host 헤더를 `localhost:11434`로 강제 치환.

```
cloudflared.exe tunnel --url http://localhost:11434 --http-host-header localhost:11434
```

적용 후 외부에서 정상적으로 "Ollama is running" 응답 확인됨. 고정 주소(named tunnel) 설정 시에도 `config.yml`의 `ingress[].originRequest.httpHostHeader`에 동일하게 반영해야 하므로 `infra/cloudflare/config.yml.example`에 미리 추가해뒀다. 이 이슈는 체크리스트 7번(트러블슈팅) 항목에 있던 "`OLLAMA_HOST=0.0.0.0` 재시작"만으로는 해결되지 않는 별개의 원인이라 체크리스트에 별도 항목으로 추가했다.

## 도메인 등록 완료 후 고정 터널 구성 (2026-09-02, 같은 날 이어서 진행)

`annswieteom.com`을 Cloudflare Registrar로 구매 완료. RDAP·DNS로 재확인한 결과 등록일 2026-09-02, 네임서버가 이미 `art.ns.cloudflare.com`/`athena.ns.cloudflare.com`로 연결되어 있어 별도 위임 작업 없이 바로 진행 가능했다(Registrar 자체가 Cloudflare라서).

진행 순서:
1. `cloudflared tunnel login` — 브라우저 OAuth, `cert.pem` 발급
2. `cloudflared tunnel create annswieteom-llm` — 터널 ID `d86a0ab3-4497-4d9b-80b9-ac4d2f1fc9ec`
3. `%USERPROFILE%\.cloudflared\config.yml` 작성 (`llm.annswieteom.com` → `http://localhost:11434`, `originRequest.httpHostHeader: localhost:11434` 포함)
4. `cloudflared tunnel route dns annswieteom-llm llm.annswieteom.com` — CNAME 자동 생성 (수동으로 Cloudflare 대시보드에서 DNS 레코드를 만들 필요 없음)
5. `cloudflared tunnel run annswieteom-llm`으로 기동 → 외부에서 `https://llm.annswieteom.com` 요청 시 "Ollama is running" 정상 확인
6. `cloudflared.exe service install`(관리자 권한)로 Windows 서비스 등록 → 수동 실행 프로세스는 종료하고 서비스 단독으로도 정상 응답하는 것 확인

## Windows 서비스가 "Running"인데 실제로는 터널이 죽어있던 문제 (2026-09-02, 도메인 등록 후 재점검 중 발견)

도메인 등록 후 다시 확인하던 중 `https://llm.annswieteom.com`에서 **530 / error code 1033**(Argo Tunnel 연결 없음)이 재현됐다. `Get-Service cloudflared`는 `Running`으로 나왔는데도 실패한 것이 핵심 단서.

**진단 과정**:
1. WebFetch 도구로 재확인했을 때는 "Ollama is running"이 나와 헷갈렸다 — 알고 보니 WebFetch는 동일 URL에 대해 15분 캐시를 쓰기 때문에, 서비스가 이미 맛이 간 뒤에도 예전 성공 응답을 재활용해서 보여준 것이었다. **`curl`로 직접 재요청해야 진짜 현재 상태를 알 수 있다.**
2. `sc.exe qc cloudflared`로 서비스 설정을 보니 `BINARY_PATH_NAME`이 `"C:\Program Files (x86)\cloudflared\cloudflared.exe"` 하나뿐, 인자가 전혀 없었다.
3. 같은 exe를 인자 없이 직접 실행해보니 `use 'cloudflared tunnel run' to start tunnel annswieteom-llm`라는 힌트만 찍고 즉시 종료됨을 확인. 즉 `cloudflared.exe service install`(토큰 없이)이 등록하는 서비스는 실제 터널을 켜는 명령이 아니었다.
4. Windows 이벤트 로그(`Get-EventLog -LogName System`)에 "The Cloudflared agent service terminated unexpectedly... 4 time(s)"가 찍혀 있어 크래시 루프였음을 확인.

**해결**: 서비스의 `ImagePath`를 레지스트리(`HKLM:\SYSTEM\CurrentControlSet\Services\cloudflared`)에서 직접 명시적인 명령으로 교체했다.
```
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --config "C:\Users\sjyoo\.cloudflared\config.yml" --logfile "C:\Users\sjyoo\.cloudflared\service.log" run annswieteom-llm
```
`sc.exe config cloudflared binPath= ...`로 먼저 시도했으나 PowerShell이 네이티브 명령 인자로 문자열을 넘길 때 내부의 큰따옴표가 깨져서 반영이 안 됐다(BINARY_PATH_NAME이 그대로였음) — 레지스트리 `Set-ItemProperty`로 직접 쓰는 방법이 확실했다.

수정 후 `service.log`에 4개의 tunnel connection이 정상 등록됐고, `curl https://llm.annswieteom.com` → `200 Ollama is running`으로 최종 확인.

**교훈**: 이 프로젝트처럼 "서비스가 Running으로 보이면 끝"이라고 믿으면 안 된다 — 반드시 외부 HTTP 응답까지 확인해야 하고, 확인 도구 자체의 캐시(WebFetch 15분 캐시 등)도 의심해야 한다.

## 마무리 (2026-09-02)

- 실제 PC 재부팅 테스트 완료 — 레지스트리 ImagePath 수정 후에도 Ollama, cloudflared 서비스 모두 사람 개입 없이 자동 기동 확인
- 휴대폰(데이터망)으로 `https://llm.annswieteom.com` 접속 확인 완료 — 서버 사이드 확인이 아닌 실제 외부 기기 확인

~~**A-5(Cloudflare Tunnel) 체크리스트는 6번(백엔드 연동)을 제외하고 전부 완료.**~~ → **정정됨, 아래 참고.**

## 정정: 위 작업은 전부 실제 서버 PC가 아니라 개발용 PC에서 한 것이었다

지금까지의 모든 작업(cloudflared 설치, 터널 생성, config.yml, DNS 라우팅, 서비스 등록·수정, 재부팅·휴대폰 검증)은 **RTX 4090 서버 PC가 아니라 별도의 개발용 PC/노트북**에서 이뤄졌다는 걸 뒤늦게 확인했다. 그 개발용 PC의 Ollama에는 애초에 `qwen2.5:14b`나 `bge-m3`가 없고 `phi3.5`, `llama3.2:3b`, `qwen2.5:3b-instruct` 같은 가벼운 모델만 있었는데, 이게 신호였다 — 진작 이상하다고 여겼어야 했다.

즉 지금 살아있는 `https://llm.annswieteom.com`은 실제 서버가 아니라 개발용 PC의 (프로젝트 사양과 다른) Ollama를 가리키고 있다. 다행히 이 작업 자체가 무의미한 건 아니다: 겪었던 두 버그(403 Host 헤더 문제, 서비스가 겉보기엔 Running인데 실제로는 죽어있던 문제)와 그 해결법은 실제 서버 PC에서도 100% 동일하게 재현될 문제라서, 그대로 재사용하면 이번처럼 헤매지 않고 바로 적용할 수 있다. 체크리스트에 8번 섹션("실제 서버 PC에서 재진행")으로 처음부터 두 문제를 피해가는 순서를 정리해뒀다.

**중요**: 6번(백엔드 연동)에서 B에게 URL을 넘기는 건, 8번(실제 서버 PC 작업)이 끝난 뒤에 해야 한다 — 지금 넘기면 B가 개발용 PC를 가리키는 URL을 받게 된다.

## 남은 작업

- **실제 서버 PC(RTX 4090)에서 터널을 처음부터 다시 구성** — 체크리스트 8번 순서대로. 터널 이름은 `annswieteom-llm-main`으로 개발용과 구분하고, `llm.annswieteom.com` DNS는 `--overwrite-dns`로 이 새 터널로 다시 연결해야 함
- `backend/.env` 자체가 아직 없음(B의 백엔드 스캐폴딩 대기) — 생성되면 `LOCAL_LLM_BASE_URL=https://llm.annswieteom.com` 반영 (실제 서버 PC 작업 완료 후)
- B에게 `https://llm.annswieteom.com` 주소 전달, Railway 배포 환경변수 반영 요청 (실제 서버 PC 작업 완료 후)
- (사소한 뒷정리) 첫 시도 때 `C:\Windows\System32\config\systemprofile\.cloudflared\`에 config/credentials를 복사해뒀는데 지금은 안 쓰인다 — 안전하지만 지워도 무방
- A-6 consistency check는 임베딩 provider만 있으면 되므로 이 정정과 무관하게 이미 별도로 진행함
