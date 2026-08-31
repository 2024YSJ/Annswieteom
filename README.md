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
