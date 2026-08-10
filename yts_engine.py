
from __future__ import annotations

from pathlib import Path
from datetime import datetime, date
from zoneinfo import ZoneInfo
import io
import re
import warnings

import numpy as np
import pandas as pd
import requests
import urllib3

MARKET_TZ = ZoneInfo("Asia/Taipei")
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DAILY_DIR = DATA_DIR / "daily"
CONFIG_DIR = ROOT / "config"
WATCHLIST_FILE = CONFIG_DIR / "watchlist.csv"

TWSE_DAILY_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_DAILY = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

def ensure_dirs():
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def _num(x):
    if x is None:
        return np.nan
    s = str(x).strip().replace(",", "").replace("--", "").replace("---", "")
    if s in {"", "-", "nan", "None"}:
        return np.nan
    try:
        return float(s)
    except Exception:
        return np.nan

def _pick(d, keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None

def _is_common_stock_code(sid):
    return isinstance(sid, str) and sid.isdigit() and len(sid) == 4

def _get_json(url, timeout=30, tpex_fallback=False):
    """
    Normal TLS verification first.
    TPEx public-market-data fallback only: if cloud CA chain fails, retry verify=False.
    No credentials or private data are ever sent to this endpoint.
    """
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except requests.exceptions.SSLError as e:
        if not tpex_fallback:
            raise
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = requests.get(url, timeout=timeout, verify=False)
        r.raise_for_status()
        return r.json(), "TPEx TLS 憑證鏈驗證失敗，已用公開行情唯讀 fallback 取得資料。"

def fetch_twse_today():
    rows, warn = _get_json(TWSE_DAILY_ALL)
    today = datetime.now(MARKET_TZ).date().isoformat()
    out = []
    for d in rows:
        sid = str(_pick(d, ["Code", "證券代號"]) or "").strip()
        if not _is_common_stock_code(sid):
            continue
        out.append({
            "date": today,
            "market": "TWSE",
            "stock_id": sid,
            "name": str(_pick(d, ["Name", "證券名稱"]) or "").strip(),
            "open": _num(_pick(d, ["OpeningPrice", "開盤價"])),
            "high": _num(_pick(d, ["HighestPrice", "最高價"])),
            "low": _num(_pick(d, ["LowestPrice", "最低價"])),
            "close": _num(_pick(d, ["ClosingPrice", "收盤價"])),
            "volume": _num(_pick(d, ["TradeVolume", "成交股數"])),
        })
    return pd.DataFrame(out), warn

def fetch_tpex_today():
    rows, warn = _get_json(TPEX_DAILY, tpex_fallback=True)
    today = datetime.now(MARKET_TZ).date().isoformat()
    out = []
    for d in rows:
        sid = str(_pick(d, [
            "SecuritiesCompanyCode", "Code", "股票代號", "證券代號"
        ]) or "").strip()
        if not _is_common_stock_code(sid):
            continue
        out.append({
            "date": today,
            "market": "TPEX",
            "stock_id": sid,
            "name": str(_pick(d, [
                "CompanyName", "SecuritiesCompanyName", "Name", "股票名稱", "證券名稱"
            ]) or "").strip(),
            "open": _num(_pick(d, ["Open", "OpenPrice", "開盤"])),
            "high": _num(_pick(d, ["High", "HighestPrice", "最高"])),
            "low": _num(_pick(d, ["Low", "LowestPrice", "最低"])),
            "close": _num(_pick(d, ["Close", "ClosePrice", "收盤"])),
            "volume": _num(_pick(d, [
                "TradingShares", "TradeVolume", "成交股數", "成交量"
            ])),
        })
    return pd.DataFrame(out), warn

def collect_today(save_local=False):
    """
    Used by Streamlit one-click scan.
    save_local=False is intentional on Community Cloud because its local FS is ephemeral.
    GitHub Actions uses save_local=True then commits the CSV into the repository.
    """
    ensure_dirs()
    frames, report, warnings_list = [], {}, []
    for market, fn in [("TWSE", fetch_twse_today), ("TPEX", fetch_tpex_today)]:
        try:
            df, warn = fn()
            if not df.empty:
                frames.append(df)
            report[market] = len(df)
            if warn:
                warnings_list.append(warn)
        except Exception as e:
            report[f"{market}_error"] = str(e)
    if not frames:
        return pd.DataFrame(), report, warnings_list

    df = pd.concat(frames, ignore_index=True)
    df = df[df["close"].notna()].copy()
    if save_local and not df.empty:
        d = str(df["date"].iloc[0])
        path = DAILY_DIR / f"{d}.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
        report["saved"] = len(df)
        report["file"] = str(path)
    return df, report, warnings_list

def load_repo_history():
    ensure_dirs()
    files = sorted(DAILY_DIR.glob("*.csv"))
    if not files:
        return pd.DataFrame()
    frames = []
    for f in files:
        try:
            frames.append(pd.read_csv(f, dtype={"stock_id": str}))
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return (
        df.dropna(subset=["date", "stock_id", "close"])
          .sort_values(["stock_id", "date"])
          .drop_duplicates(["stock_id", "date"], keep="last")
          .reset_index(drop=True)
    )

def combine_history_with_live(history, live):
    if live is None or live.empty:
        return history.copy()
    live = live.copy()
    live["date"] = pd.to_datetime(live["date"], errors="coerce").dt.date
    if history is None or history.empty:
        return live
    x = pd.concat([history, live], ignore_index=True)
    return (
        x.sort_values(["stock_id", "date"])
         .drop_duplicates(["stock_id", "date"], keep="last")
         .reset_index(drop=True)
    )

def add_indicators(df):
    if df.empty:
        return df
    x = df.copy().sort_values(["stock_id", "date"])
    g = x.groupby("stock_id", group_keys=False)

    for n in [5, 10, 20, 60]:
        x[f"ma{n}"] = g["close"].transform(
            lambda s, n=n: s.rolling(n, min_periods=n).mean()
        )

    # User-confirmed rule: previous 20 trading days, excluding current day.
    x["avg_volume_prev20"] = g["volume"].transform(
        lambda s: s.shift(1).rolling(20, min_periods=20).mean()
    )
    x["volume_ratio_20"] = x["volume"] / x["avg_volume_prev20"]

    rng = x["high"] - x["low"]
    x["foot_ratio"] = np.where(
        rng > 0, (x["close"] - x["low"]) / rng, np.nan
    )
    x["close_above_ma20"] = x["close"] > x["ma20"]
    x["ma20_above_ma60"] = x["ma20"] > x["ma60"]

    counts = g["close"].transform("count")
    x["history_days"] = counts
    return x

def latest_snapshot(df):
    if df.empty:
        return df
    x = add_indicators(df)
    return (
        x.sort_values(["stock_id", "date"])
         .groupby("stock_id", as_index=False)
         .tail(1)
         .reset_index(drop=True)
    )

def load_watchlist():
    ensure_dirs()
    if not WATCHLIST_FILE.exists():
        return pd.DataFrame(columns=[
            "stock_id","name","neckline","support","pressure",
            "breakout_volume","chip_score","note"
        ])
    w = pd.read_csv(WATCHLIST_FILE, dtype={"stock_id": str})
    for c in ["neckline","support","pressure","breakout_volume","chip_score"]:
        if c in w:
            w[c] = pd.to_numeric(w[c], errors="coerce")
    return w

def objective_candidates(df):
    """
    Objective only:
      1) close > MA20
      2) today's volume >= previous-20-day average * 1.5
    Does NOT claim a neckline breakout.
    """
    s = latest_snapshot(df)
    if s.empty:
        return s
    ok = (
        (s["history_days"] >= 21) &
        (s["close_above_ma20"] == True) &
        (s["volume_ratio_20"] >= 1.5)
    )
    out = s[ok].copy()
    out["trend_grade"] = np.where(
        out["ma20_above_ma60"] == True,
        "強多頭：Close > MA20 > MA60",
        "多頭：Close > MA20"
    )
    out["stage"] = "帶量候選；需人工確認整理/頸線，第一根不追"
    return out

def watchlist_analysis(df, tolerance=0.015):
    w = load_watchlist()
    if w.empty or df.empty:
        return pd.DataFrame()
    x = add_indicators(df)
    rows = []
    for _, r in w.iterrows():
        sid = str(r["stock_id"])
        h = x[x["stock_id"] == sid].sort_values("date")
        if h.empty:
            continue
        z = h.iloc[-1]
        rec = dict(r)
        rec.update({
            "date": z["date"], "close": z["close"], "high": z["high"], "low": z["low"],
            "ma20": z["ma20"], "ma60": z["ma60"],
            "volume": z["volume"], "volume_ratio_20": z["volume_ratio_20"],
            "foot_ratio": z["foot_ratio"], "history_days": z["history_days"],
        })
        ref = r.get("support", np.nan)
        if pd.isna(ref):
            ref = r.get("neckline", np.nan)

        if pd.isna(ref) or ref <= 0:
            state = "待人工設定支撐"
        else:
            near = (
                abs(z["low"] - ref) / ref <= tolerance
                or (z["low"] <= ref <= z["high"])
            )
            if not near:
                state = "尚未回測"
            elif z["close"] >= ref and z["foot_ratio"] >= 2/3:
                state = "回測＋嚴格收腳確認"
            elif z["close"] >= ref and z["foot_ratio"] >= 0.5:
                state = "回測＋一般收腳確認"
            elif z["close"] >= ref:
                state = "回測到位但收腳不足"
            else:
                state = "回測但收盤未站回支撐"
        rec["retest_state"] = state

        bv = r.get("breakout_volume", np.nan)
        rec["retest_vs_breakout_volume"] = (
            z["volume"] / bv if pd.notna(bv) and bv > 0 else np.nan
        )
        p = r.get("pressure", np.nan)
        rec["pressure_distance_pct"] = (
            (p - z["close"]) / z["close"]
            if pd.notna(p) and p > 0 and z["close"] > 0 else np.nan
        )
        rec["yts_score"] = score_watchlist_row(rec)
        rows.append(rec)
    return pd.DataFrame(rows)

def score_watchlist_row(r):
    score = 0
    close = r.get("close", np.nan)
    ma20 = r.get("ma20", np.nan)
    ma60 = r.get("ma60", np.nan)
    if pd.notna(close) and pd.notna(ma20) and close > ma20:
        score += 20
    if pd.notna(ma20) and pd.notna(ma60) and ma20 > ma60:
        score += 10

    state = r.get("retest_state", "")
    if "回測" in state:
        score += 15
    if "嚴格收腳" in state:
        score += 20
    elif "一般收腳" in state:
        score += 12
    elif "收腳不足" in state:
        score += 4

    rv = r.get("retest_vs_breakout_volume", np.nan)
    if pd.notna(rv):
        if rv <= 0.4:
            score += 15
        elif rv <= 0.6:
            score += 10
        elif rv <= 0.8:
            score += 5

    pdist = r.get("pressure_distance_pct", np.nan)
    if pd.notna(pdist):
        if pdist >= 0.08:
            score += 10
        elif pdist >= 0.05:
            score += 6
        elif pdist < 0.03:
            score -= 8

    try:
        score += int(r.get("chip_score", 0))
    except Exception:
        pass
    return max(0, min(100, score))
