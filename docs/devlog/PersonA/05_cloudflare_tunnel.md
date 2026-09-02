# A-5. Cloudflare Tunnel 설정 devlog

체크리스트: `docs/checklists/person_A_infra_ai/05_cloudflare_tunnel.md`
날짜: 2026-09-02

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

## 남은 작업

- **실제 PC 재부팅 테스트** — 서비스 등록은 했지만 재부팅 후에도 자동으로 살아나는지는 아직 검증 안 함. 데모 전 필수
- 휴대폰 데이터망 등 실제 외부 기기로 한 번 더 접속 확인 (지금까지는 서버 사이드 요청으로만 확인)
- `backend/.env` 자체가 아직 없음(B의 백엔드 스캐폴딩 대기) — 생성되면 `LOCAL_LLM_BASE_URL=https://llm.annswieteom.com` 반영
- B에게 `https://llm.annswieteom.com` 주소 전달, Railway 배포 환경변수 반영 요청
