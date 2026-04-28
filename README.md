# Macro Lingo

거시경제 학습용 시각화 대시보드. ECOS(한국은행) + FRED(미 연준) + 한국 섹터 ETF 데이터를 받아 '황금 계란 배달부' 메타포로 표현합니다.

- **실시간 매크로 기상도**: USD/KRW, 한국 기준금리, 미 10Y, VIX, WTI 등
- **섹터 단위 가상 포트폴리오**: 종목 거래 X, 슬라이더로 비중 조절
- **토크 기반 무게중심**: τ = 비중 × 변동성 — 기울어진 만큼 시스템 부하
- **Dual-Lens**: 현재 vs 과거(리먼/IMF/COVID 등) 시대 비교

## 구조

```
macro-lingo/
├── index.html              # 대시보드 (정적)
├── fetcher.py              # ECOS/FRED/yfinance → snapshot.json
├── data/snapshot.json      # 가공된 매크로 지표 (키 정보 X)
├── requirements.txt
└── .github/workflows/snapshot.yml   # 15분마다 자동 갱신 + Pages 배포
```

## 로컬에서 실행

```bash
# 1) 의존성
pip install -r requirements.txt

# 2) 키 제공 — 환경변수 또는 config.json
export ECOS_API_KEY=...
export FRED_API_KEY=...

# 3) 데이터 수집
python fetcher.py

# 4) 정적 서버로 열기 (file:// 로는 fetch가 안 됨)
python -m http.server 8000
# → http://localhost:8000
```

## GitHub 배포 (1회 설정)

1. **빈 repo 생성** (private/public 어느 쪽이든 OK)
2. **Settings → Secrets and variables → Actions** 에서 추가:
   - `ECOS_API_KEY` (한국은행 ECOS)
   - `FRED_API_KEY` (FRED)
3. **Settings → Pages → Source: GitHub Actions** 로 설정
4. 로컬에서 push:
   ```bash
   git remote add origin git@github.com:USER/REPO.git
   git push -u origin main
   ```
5. Actions 탭에서 워크플로우 한 번 수동 실행 (`Refresh Macro Snapshot` → Run workflow)

이후 15분마다 snapshot이 자동 갱신되고 Pages가 재배포됩니다.

## 데이터 출처

| 지표 | 출처 |
|------|------|
| USD/KRW, KOSPI, 한국 금리 | ECOS (한국은행 OpenAPI) |
| 미 10Y, VIX, Fed, WTI, DXY | FRED (St. Louis Fed) |
| 섹터 ETF 변동성/등락률 | yfinance (Yahoo Finance) |

## 한계

- **GitHub Actions의 `*/15 * * * *` 크론은 보장이 아닙니다** (best-effort). 실제로 5~30분 지연 가능
- **장 마감 시간엔 등락률이 0% 또는 직전 거래일 값**으로 멈춤
- **yfinance는 비공식 API** — Yahoo가 차단하면 fallback 변동성으로 동작
