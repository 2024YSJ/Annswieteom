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

## 남은 작업

- 도메인 등록 기관 확인 후 실제 소유 도메인 확정 → Cloudflare 네임서버(`art.ns.cloudflare.com`, `athena.ns.cloudflare.com`)로 위임
- `cloudflared tunnel login` → `tunnel create annswieteom-llm` → 고정 `config.yml` 작성 (3번)
- 외부 기기(휴대폰 데이터망)로 고정 주소 접속 확인 (4번)
- `cloudflared.exe service install`로 재부팅 자동 실행 등록 + 실제 재부팅 테스트 (5번)
- 발급 주소를 `backend/.env`의 `LOCAL_LLM_BASE_URL`에 반영, B에게 공유해 Railway 환경변수에도 반영 요청 (6번)
