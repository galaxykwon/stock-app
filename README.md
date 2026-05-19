# 매매동향 앱 — GitHub + Vercel 배포 가이드

## 📁 파일 구조 (심플)

```
stock-vercel/          ← 이 폴더 전체를 GitHub에 올립니다
├── api/
│   └── index.py       ← FastAPI 서버 + HTML 프론트 통합
├── requirements.txt   ← Python 패키지 목록
├── vercel.json        ← Vercel 배포 설정
└── .gitignore
```

---

## Step 1 — GitHub 레포 만들기

1. https://github.com 로그인
2. 우측 상단 **"+"** → **"New repository"**
3. Repository name: `stock-app` (원하는 이름)
4. **Private** 선택 (앱키 노출 방지)
5. **Create repository** 클릭

---

## Step 2 — 코드를 GitHub에 올리기

`stock-vercel` 폴더 위치에서 cmd 실행:

```cmd
cd /d H:\stock-vercel

git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/[내아이디]/stock-app.git
git push -u origin main
```

> `[내아이디]` 부분을 본인 GitHub 아이디로 변경

---

## Step 3 — Vercel 연결

1. https://vercel.com 접속 → **GitHub으로 로그인**
2. **"Add New Project"** 클릭
3. GitHub에서 `stock-app` 레포 선택 → **Import**
4. Framework Preset: **Other** 선택
5. **"Environment Variables"** 섹션에서 앱키 추가:

   | Name | Value |
   |------|-------|
   | `KIS_APP_KEY` | 발급받은 앱키 36자리 |
   | `KIS_APP_SECRET` | 발급받은 앱시크릿 180자리 |

6. **Deploy** 클릭

---

## Step 4 — 배포 완료

Vercel이 자동으로 빌드 후 URL 제공:
```
https://stock-app-[랜덤].vercel.app
```

이 URL로 어디서든 모바일/PC로 접속 가능합니다.

---

## 코드 수정 후 재배포

코드 수정 → GitHub push → Vercel 자동 재배포 (수동 작업 불필요)

```cmd
cd /d H:\stock-vercel
git add .
git commit -m "수정 내용"
git push
```

---

## ⚠️ 주의사항

- `.env` 파일은 `.gitignore`에 포함되어 GitHub에 올라가지 않음
- 앱키는 반드시 **Vercel 환경변수**에서만 관리
- Vercel 무료 플랜: 월 100GB 대역폭, 충분함
- Vercel Serverless 특성상 **인메모리 캐시가 요청마다 초기화**될 수 있음
  → 토큰 재발급이 자주 일어날 수 있으나 KIS API 제한 내 정상 동작
