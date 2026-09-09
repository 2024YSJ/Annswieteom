# 안 쉬었음 (Annswieteom)

구직 공백기를 STAR 구조 경력 서술로 변환해주는 웹 애플리케이션.

## 로컬 실행

**백엔드**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # 값 채운 뒤 저장
alembic upgrade head
uvicorn app.main:app --reload --port 8000
# → http://localhost:8000/docs
```

**프론트엔드**

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
# → http://localhost:3000
```

## 에셋 출처

아이콘 에셋은 전부 로고 원본 하나에서 생성한다. 크기·여백·배경을 손으로 맞추지 말고
스크립트를 다시 돌릴 것 (Pillow 필요, 텍스트는 Noto Sans KR):

```bash
cd frontend && python logo/generate_icons.py
```

| 생성물 | 쓰임 |
|---|---|
| `frontend/app/icon.png` | 브라우저 탭 파비콘 (512×512, 흰 원 배경) |
| `frontend/app/apple-icon.png` | iOS 홈 화면 아이콘 (180×180, 불투명 흰 배경) |
| `frontend/app/opengraph-image.png` | 링크 공유 카드 (1200×630) |

원본 로고는 Flaticon 무료 라이선스라 **제작자 표기가 필수**다. 표기는
`frontend/components/SiteFooter.tsx`가 담당한다 — 랜딩·로그인·회원가입에서는 페이지
하단 푸터로, 푸터를 렌더하지 않는 세션 대화 화면에서는 사이드바 맨 아래로 나간다
(이유는 SiteFooter의 주석 참고). 아이콘을 교체하더라도 이 표기를 같이 지우기 전에
라이선스를 먼저 확인할 것.

- 원본 파일: `frontend/logo/free-icon-no-bed-13322151.png` (투명 배경 512×512)
- <a href="https://www.flaticon.com/kr/free-icons/-" title="침대가 없다 아이콘">침대가 없다 아이콘 제작자: juicy_fish - Flaticon</a>
