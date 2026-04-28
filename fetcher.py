"""
fetcher.py — Macro-Lingo 실데이터 수집기

ECOS(한국은행) + FRED(미 연준)에서 매크로 지표를 받아
data/snapshot.json 으로 저장합니다.

실행:
    python fetcher.py

자동화:
    crontab -e
    */15 * * * * cd /path/to/proj && python fetcher.py >> fetcher.log 2>&1

API 키는 config.json 에서만 읽고, 출력물(snapshot.json)에는 절대 포함되지 않습니다.
"""
import json
import os
import datetime
from pathlib import Path
import requests

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
SNAPSHOT = DATA_DIR / "snapshot.json"

# 키 로딩: 환경변수 우선 (GitHub Actions/Secrets), 없으면 로컬 config.json
def _load_keys() -> dict:
    keys = {
        "ecos_api_key": os.getenv("ECOS_API_KEY", ""),
        "fred_api_key": os.getenv("FRED_API_KEY", ""),
    }
    cfg_path = ROOT / "config.json"
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        for k in keys:
            if not keys[k]:
                keys[k] = cfg.get(k, "")
    missing = [k for k, v in keys.items() if not v]
    if missing:
        raise RuntimeError(
            f"누락된 키: {missing}. "
            "환경변수(ECOS_API_KEY, FRED_API_KEY) 또는 config.json 으로 제공하세요."
        )
    return keys

CONFIG = _load_keys()

# ── ECOS (한국은행) ─────────────────────────────────────
# (stat_code, item_code, periodicity)  D=일별, M=월별
ECOS_SERIES = {
    "fx_usd_krw":   ("731Y001", "0000001",   "D"),  # 원/달러 환율 (일별)
    "kr_base_rate": ("722Y001", "0101000",   "M"),  # 한국은행 기준금리 (월별)
    "kr_3y_bond":   ("817Y002", "010190000", "D"),  # 국고채 3년 (일별)
    "kospi":        ("802Y001", "0001000",   "D"),  # KOSPI 지수 (일별)
}

def fetch_ecos(key: str) -> dict:
    out = {}
    now = datetime.datetime.now()
    ranges = {
        "D": (now - datetime.timedelta(days=14), now, "%Y%m%d"),
        "M": (now - datetime.timedelta(days=120), now, "%Y%m"),
    }
    for name, (stat, item, period) in ECOS_SERIES.items():
        try:
            ago, today, fmt = ranges[period]
            url = (
                f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr"
                f"/1/10/{stat}/{period}/{ago.strftime(fmt)}/{today.strftime(fmt)}/{item}"
            )
            r = requests.get(url, timeout=10)
            rows = r.json().get("StatisticSearch", {}).get("row", [])
            if rows:
                last = rows[-1]
                out[name] = {
                    "value": float(last["DATA_VALUE"]),
                    "date": last.get("TIME", ""),
                    "unit": last.get("UNIT_NAME", ""),
                    "source": "ECOS",
                }
                print(f"  ✓ ECOS {name}: {out[name]['value']} ({last.get('TIME','')})")
            else:
                print(f"  ⚠ ECOS [{name}] 빈 응답")
        except Exception as e:
            print(f"  ⚠ ECOS [{name}] 실패: {e}")
    return out

# ── FRED (미 연준) ─────────────────────────────────────
FRED_SERIES = {
    "us_10y":      "DGS10",
    "vix":         "VIXCLS",
    "us_fed_rate": "FEDFUNDS",
    "wti_oil":     "DCOILWTICO",
    "dxy":         "DTWEXBGS",
}

def fetch_fred(key: str) -> dict:
    out = {}
    ago = (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    for name, sid in FRED_SERIES.items():
        try:
            r = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id": sid,
                    "api_key": key,
                    "file_type": "json",
                    "limit": "1",
                    "sort_order": "desc",
                    "observation_start": ago,
                },
                timeout=10,
            )
            obs = r.json().get("observations", [])
            if obs and obs[0].get("value") not in (".", "", None):
                out[name] = {
                    "value": float(obs[0]["value"]),
                    "date": obs[0].get("date", ""),
                    "source": "FRED",
                }
                print(f"  ✓ FRED {name}: {out[name]['value']} ({obs[0].get('date','')})")
        except Exception as e:
            print(f"  ⚠ FRED [{name}] 실패: {e}")
    return out

# ── 섹터 ETF (yfinance로 30일 변동성 + 당일 등락률) ──
SECTOR_ETFS = {
    "defense":  "449450.KS",  # TIGER 우주방산
    "tech":     "091160.KS",  # KODEX 반도체
    "energy":   "117460.KS",  # KODEX 에너지화학
    "finance":  "091170.KS",  # KODEX 은행
    "bio":      "244580.KS",  # KODEX 바이오
    "consumer": "102780.KS",  # KODEX KRX300 (대표 소비/내수)
}
# yfinance 실패 시 fallback (시각화가 0으로 죽지 않게)
SECTOR_VOL_FALLBACK = {
    "finance": 2.4, "consumer": 3.1, "defense": 3.5,
    "bio": 2.9, "tech": 4.0, "energy": 2.7,
}

def fetch_sectors() -> dict:
    out = {}
    try:
        import yfinance as yf
        import warnings
        warnings.filterwarnings('ignore')
    except ImportError:
        print("  ⚠ yfinance 없음 — fallback 사용")
        return {k: {"volatility_30d": v, "change_pct": 0.0, "source": "fallback"}
                for k, v in SECTOR_VOL_FALLBACK.items()}

    for sector, ticker in SECTOR_ETFS.items():
        try:
            d = yf.download(ticker, period="60d", progress=False, auto_adjust=True)
            if d.empty:
                raise RuntimeError("빈 응답")
            close = d["Close"].squeeze()
            ret = close.pct_change().dropna()
            vol_30d = float(ret.tail(30).std() * 100)
            change_today = float((close.iloc[-1] / close.iloc[-2] - 1) * 100)
            out[sector] = {
                "volatility_30d": round(vol_30d, 2),
                "change_pct": round(change_today, 2),
                "ticker": ticker,
                "source": "yfinance",
            }
            print(f"  ✓ {sector:9s} ({ticker}): vol30d={vol_30d:.2f}%  today={change_today:+.2f}%")
        except Exception as e:
            print(f"  ⚠ {sector} ({ticker}) 실패: {e} — fallback")
            out[sector] = {
                "volatility_30d": SECTOR_VOL_FALLBACK[sector],
                "change_pct": 0.0,
                "ticker": ticker,
                "source": "fallback",
            }
    return out

def main():
    print("📊 매크로 데이터 수집 시작...")
    print("─" * 50)

    print("[1/3] ECOS (한국은행)")
    ecos = fetch_ecos(CONFIG["ecos_api_key"])

    print("[2/3] FRED (미 연준)")
    fred = fetch_fred(CONFIG["fred_api_key"])

    print("[3/3] 섹터 ETF (yfinance)")
    sectors = fetch_sectors()

    snapshot = {
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S KST"),
        "macro": {**ecos, **fred},
        "sectors": sectors,
    }

    SNAPSHOT.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("─" * 50)
    print(f"✅ 저장 완료: {SNAPSHOT.relative_to(ROOT)}")
    print(f"   매크로 지표 {len(snapshot['macro'])}개, 섹터 {len(snapshot['sectors'])}개")

if __name__ == "__main__":
    main()
