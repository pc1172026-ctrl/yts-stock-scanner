
from __future__ import annotations

from pathlib import Path
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import time

import numpy as np
import pandas as pd
import requests
import urllib3

TZ = ZoneInfo("Asia/Taipei")
ROOT = Path(__file__).resolve().parent
STAGE1_DIR = ROOT / "data" / "stage1"
INST_DIR = STAGE1_DIR / "institutional"
FUND_FILE = STAGE1_DIR / "fundamentals_latest.csv"

# 投信
TWSE_T86 = "https://www.twse.com.tw/fund/T86"
TPEX_TRUST = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_trading"

# 月營收
TWSE_REVENUE = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TPEX_REVENUE = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"

# EPS：改用官方「各產業 EPS 統計資訊」。
# 這個資料集直接提供：年度、季別、公司代號、基本每股盈餘(元)
TWSE_EPS = "https://openapi.twse.com.tw/v1/opendata/t187ap14_L"
TPEX_EPS = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap14_O"


def ensure_stage1_dirs():
    INST_DIR.mkdir(parents=True, exist_ok=True)


def _num(x):
    if x is None:
        return np.nan
    s = str(x).strip().replace(",", "").replace("%", "").replace("－", "-")
    if s in {"", "-", "--", "---", "nan", "None"}:
        return np.nan
    try:
        return float(s)
    except Exception:
        return np.nan


def _get_json(url, params=None, tpex_fallback=False, timeout=45):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.SSLError:
        if not tpex_fallback:
            raise
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = requests.get(url, params=params, timeout=timeout, verify=False)
        r.raise_for_status()
        return r.json()


def _first_value(d, candidates):
    for k in candidates:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _common_code(x):
    s = str(x).strip()
    return s if s.isdigit() and len(s) == 4 and not s.startswith("0") else ""


# =========================================================
# 投信
# =========================================================

def fetch_twse_trust_for_date(d: date):
    js = _get_json(
        TWSE_T86,
        params={
            "response": "json",
            "date": d.strftime("%Y%m%d"),
            "selectType": "ALLBUT0999",
        },
    )

    wanted_code = "證券代號"
    wanted_name = "證券名稱"
    wanted_net = "投信買賣超股數"

    rows = []
    for t in js.get("tables", []):
        fields = t.get("fields", [])
        if wanted_code not in fields or wanted_net not in fields:
            continue

        idx = {f: fields.index(f) for f in fields}

        for r in t.get("data", []):
            sid = _common_code(r[idx[wanted_code]])
            if not sid:
                continue

            rows.append({
                "date": d.isoformat(),
                "market": "TWSE",
                "stock_id": sid,
                "name": str(r[idx[wanted_name]]).strip() if wanted_name in idx else "",
                "trust_net": _num(r[idx[wanted_net]]),
            })

        if rows:
            break

    return pd.DataFrame(rows)


def fetch_tpex_trust_today():
    rows = _get_json(TPEX_TRUST, tpex_fallback=True)
    today = datetime.now(TZ).date().isoformat()
    out = []

    # TPEx OpenAPI 欄位可能是英文名稱；此處只處理已知候選欄位。
    code_candidates = [
        "SecuritiesCompanyCode", "Code", "證券代號", "股票代號", "公司代號"
    ]
    name_candidates = [
        "CompanyName", "SecuritiesCompanyName", "Name", "證券名稱", "股票名稱", "公司名稱"
    ]
    net_candidates = [
        "InvestmentTrustDifference",
        "InvestmentTrustNetBuySell",
        "投信買賣超股數",
        "投信買賣超",
    ]

    for d in rows:
        sid = _common_code(_first_value(d, code_candidates))
        if not sid:
            continue

        net_raw = _first_value(d, net_candidates)

        # 若官方欄位名稱改動，不猜值；直接保留 NaN。
        out.append({
            "date": today,
            "market": "TPEX",
            "stock_id": sid,
            "name": str(_first_value(d, name_candidates) or "").strip(),
            "trust_net": _num(net_raw),
        })

    return pd.DataFrame(out)


def save_institutional_day(df):
    ensure_stage1_dirs()
    if df is None or df.empty:
        return None

    d = str(df["date"].iloc[0])
    p = INST_DIR / f"{d}.csv"

    if p.exists():
        old = pd.read_csv(p, dtype={"stock_id": str})
        x = pd.concat([old, df], ignore_index=True)
        x = x.drop_duplicates(["market", "stock_id", "date"], keep="last")
    else:
        x = df.copy()

    x.to_csv(p, index=False, encoding="utf-8-sig")
    return p


def collect_today_institutional():
    today = datetime.now(TZ).date()
    frames = []
    report = {}

    try:
        tw = fetch_twse_trust_for_date(today)
        if not tw.empty:
            frames.append(tw)
        report["TWSE_trust"] = len(tw)
    except Exception as e:
        report["TWSE_trust_error"] = str(e)

    try:
        tp = fetch_tpex_trust_today()
        if not tp.empty:
            frames.append(tp)
        report["TPEX_trust"] = len(tp)
    except Exception as e:
        report["TPEX_trust_error"] = str(e)

    if not frames:
        return pd.DataFrame(), report

    x = pd.concat(frames, ignore_index=True)
    save_institutional_day(x)
    return x, report


def bootstrap_twse_trust(calendar_days=25):
    ensure_stage1_dirs()
    today = datetime.now(TZ).date()
    start = today - timedelta(days=calendar_days)

    result = {"saved_days": 0, "rows": 0, "errors": []}

    d = start
    while d <= today:
        if d.weekday() < 5:
            try:
                df = fetch_twse_trust_for_date(d)
                if not df.empty:
                    save_institutional_day(df)
                    result["saved_days"] += 1
                    result["rows"] += len(df)
            except Exception as e:
                result["errors"].append(f"{d}: {e}")
            time.sleep(0.12)
        d += timedelta(days=1)

    return result


def load_institutional_history():
    ensure_stage1_dirs()
    files = sorted(INST_DIR.glob("*.csv"))

    if not files:
        return pd.DataFrame(
            columns=["date", "market", "stock_id", "name", "trust_net"]
        )

    frames = []
    for p in files:
        try:
            frames.append(pd.read_csv(p, dtype={"stock_id": str}))
        except Exception:
            pass

    if not frames:
        return pd.DataFrame(
            columns=["date", "market", "stock_id", "name", "trust_net"]
        )

    x = pd.concat(frames, ignore_index=True)
    x["date"] = pd.to_datetime(x["date"], errors="coerce").dt.date
    x["trust_net"] = pd.to_numeric(x["trust_net"], errors="coerce")

    return (
        x.dropna(subset=["date", "market", "stock_id"])
         .sort_values(["market", "stock_id", "date"])
         .drop_duplicates(["market", "stock_id", "date"], keep="last")
    )


def trust_snapshot(lookback=10):
    """
    投信初買暫定：
    今日投信買賣超 > 0，
    且前 N 個「已有投信資料的交易日」皆 <= 0。
    歷史不足 N+1 筆，不自行猜，標記資料不足。
    """
    h = load_institutional_history()

    if h.empty:
        return pd.DataFrame(columns=[
            "market", "stock_id", "trust_net", "trust_first_buy",
            "trust_streak", "trust_history_count", "trust_status"
        ])

    rows = []

    for (market, sid), g in h.groupby(["market", "stock_id"]):
        g = g.sort_values("date").dropna(subset=["trust_net"])
        if g.empty:
            continue

        latest = g.iloc[-1]
        current = latest["trust_net"]
        previous = g.iloc[:-1].tail(lookback)

        enough = len(previous) >= lookback
        first_buy = bool(
            enough
            and current > 0
            and (previous["trust_net"] <= 0).all()
        )

        streak = 0
        if current > 0:
            for v in reversed(g["trust_net"].tolist()):
                if pd.notna(v) and v > 0:
                    streak += 1
                else:
                    break

        if not enough:
            status = "資料不足"
        elif first_buy:
            status = "🔥 投信初買"
        elif current > 0 and streak >= 3:
            status = f"🟢 投信連{streak}買"
        elif current > 0:
            status = "🟢 投信買超"
        elif current < 0:
            status = "🔴 投信賣超"
        else:
            status = "⚪ 投信0"

        rows.append({
            "market": market,
            "stock_id": sid,
            "trust_date": latest["date"],
            "trust_net": current,
            "trust_first_buy": first_buy,
            "trust_streak": streak,
            "trust_history_count": len(g),
            "trust_status": status,
        })

    return pd.DataFrame(rows)


# =========================================================
# 月營收
# =========================================================

def _parse_revenue_rows(rows, market):
    """
    僅採官方資料集明列的精確欄名，不再用模糊搜尋。
    """
    out = []

    for d in rows:
        sid = _common_code(
            _first_value(d, ["公司代號", "證券代號", "股票代號"])
        )
        if not sid:
            continue

        # 官方欄位：
        # 營業收入-去年同月增減(%)
        # 累計營業收入-前期比較增減(%)
        month_yoy = _num(_first_value(d, [
            "營業收入-去年同月增減(%)",
            "營業收入－去年同月增減(%)",
        ]))

        cum_yoy = _num(_first_value(d, [
            "累計營業收入-前期比較增減(%)",
            "累計營業收入－前期比較增減(%)",
        ]))

        out.append({
            "market": market,
            "stock_id": sid,
            "name": str(_first_value(d, ["公司名稱", "證券名稱"]) or "").strip(),
            "revenue_period": str(_first_value(d, ["資料年月"]) or "").strip(),
            "revenue_month_yoy": month_yoy,
            "revenue_cum_yoy": cum_yoy,
        })

    return pd.DataFrame(out)


def fetch_revenue_latest():
    frames = []
    report = {}

    try:
        rows = _get_json(TWSE_REVENUE)
        df = _parse_revenue_rows(rows, "TWSE")
        if not df.empty:
            frames.append(df)
        report["TWSE_revenue"] = len(df)
    except Exception as e:
        report["TWSE_revenue_error"] = str(e)

    try:
        rows = _get_json(TPEX_REVENUE, tpex_fallback=True)
        df = _parse_revenue_rows(rows, "TPEX")
        if not df.empty:
            frames.append(df)
        report["TPEX_revenue"] = len(df)
    except Exception as e:
        report["TPEX_revenue_error"] = str(e)

    if not frames:
        return pd.DataFrame(), report

    x = pd.concat(frames, ignore_index=True)
    x = x.drop_duplicates(["market", "stock_id"], keep="last")
    return x, report


# =========================================================
# EPS
# =========================================================

def _parse_eps_summary_rows(rows, market):
    """
    官方「各產業 EPS 統計資訊」欄位：
    年度、季別、公司代號、公司名稱、基本每股盈餘(元)
    """
    out = []

    for d in rows:
        sid = _common_code(
            _first_value(d, ["公司代號", "證券代號", "股票代號"])
        )
        if not sid:
            continue

        eps = _num(_first_value(d, [
            "基本每股盈餘(元)",
            "基本每股盈餘（元）",
        ]))

        out.append({
            "market": market,
            "stock_id": sid,
            "name": str(_first_value(d, ["公司名稱", "證券名稱"]) or "").strip(),
            "eps_year": str(_first_value(d, ["年度"]) or "").strip(),
            "eps_quarter": str(_first_value(d, ["季別"]) or "").strip(),
            "eps_cumulative": eps,
        })

    return pd.DataFrame(out)


def fetch_eps_latest():
    frames = []
    report = {}

    try:
        rows = _get_json(TWSE_EPS)
        df = _parse_eps_summary_rows(rows, "TWSE")
        if not df.empty:
            frames.append(df)
        report["TWSE_eps"] = len(df)
    except Exception as e:
        report["TWSE_eps_error"] = str(e)

    try:
        rows = _get_json(TPEX_EPS, tpex_fallback=True)
        df = _parse_eps_summary_rows(rows, "TPEX")
        if not df.empty:
            frames.append(df)
        report["TPEX_eps"] = len(df)
    except Exception as e:
        report["TPEX_eps_error"] = str(e)

    if not frames:
        return pd.DataFrame(), report

    x = pd.concat(frames, ignore_index=True)
    x["eps_cumulative"] = pd.to_numeric(x["eps_cumulative"], errors="coerce")
    x = x.dropna(subset=["eps_cumulative"])
    x = x.drop_duplicates(["market", "stock_id"], keep="last")

    return x, report


# =========================================================
# 合併基本面
# =========================================================

def collect_fundamentals():
    ensure_stage1_dirs()

    rev, rev_report = fetch_revenue_latest()
    eps, eps_report = fetch_eps_latest()

    if rev.empty and eps.empty:
        return pd.DataFrame(), {
            "revenue": rev_report,
            "eps": eps_report,
        }

    if rev.empty:
        x = eps.copy()
    elif eps.empty:
        x = rev.copy()
    else:
        x = rev.merge(
            eps[[
                "market", "stock_id",
                "eps_year", "eps_quarter", "eps_cumulative"
            ]],
            on=["market", "stock_id"],
            how="outer",
        )

    for c in ["revenue_month_yoy", "revenue_cum_yoy", "eps_cumulative"]:
        if c not in x.columns:
            x[c] = np.nan
        x[c] = pd.to_numeric(x[c], errors="coerce")

    x["revenue_double_growth"] = (
        (x["revenue_month_yoy"] > 0)
        & (x["revenue_cum_yoy"] > 0)
    )

    x["eps_positive"] = x["eps_cumulative"] > 0

    # 額外保留資料品質欄位，方便手機驗收。
    x["revenue_data_ok"] = (
        x["revenue_month_yoy"].notna()
        & x["revenue_cum_yoy"].notna()
    )
    x["eps_data_ok"] = x["eps_cumulative"].notna()

    x.to_csv(FUND_FILE, index=False, encoding="utf-8-sig")

    return x, {
        "revenue": rev_report,
        "eps": eps_report,
        "rows_saved": len(x),
        "revenue_ok_rows": int(x["revenue_data_ok"].sum()),
        "eps_ok_rows": int(x["eps_data_ok"].sum()),
    }


def load_fundamentals():
    if not FUND_FILE.exists():
        return pd.DataFrame()

    x = pd.read_csv(FUND_FILE, dtype={"stock_id": str})

    for c in ["revenue_month_yoy", "revenue_cum_yoy", "eps_cumulative"]:
        if c in x.columns:
            x[c] = pd.to_numeric(x[c], errors="coerce")

    for c in [
        "revenue_double_growth", "eps_positive",
        "revenue_data_ok", "eps_data_ok"
    ]:
        if c in x.columns:
            x[c] = (
                x[c].astype(str).str.lower()
                .map({"true": True, "false": False})
                .fillna(False)
            )

    return x


def stage1_snapshot(lookback=10):
    trust = trust_snapshot(lookback=lookback)
    fund = load_fundamentals()

    if trust.empty and fund.empty:
        return pd.DataFrame()

    if trust.empty:
        x = fund.copy()
    elif fund.empty:
        x = trust.copy()
    else:
        x = trust.merge(
            fund,
            on=["market", "stock_id"],
            how="outer",
            suffixes=("", "_fund"),
        )

    # Stage1 暫時只做確認 / 排序，不做硬淘汰。
    x["stage1_score"] = 0

    if "trust_first_buy" in x.columns:
        x.loc[x["trust_first_buy"] == True, "stage1_score"] += 15

    if "trust_net" in x.columns:
        x.loc[
            pd.to_numeric(x["trust_net"], errors="coerce") > 0,
            "stage1_score"
        ] += 6

    if "revenue_double_growth" in x.columns:
        x.loc[
            x["revenue_double_growth"] == True,
            "stage1_score"
        ] += 10

    if "eps_positive" in x.columns:
        x.loc[
            x["eps_positive"] == True,
            "stage1_score"
        ] += 10

    return x
