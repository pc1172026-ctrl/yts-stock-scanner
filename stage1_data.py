
from __future__ import annotations

from pathlib import Path
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import re, time
import numpy as np
import pandas as pd
import requests
import urllib3

TZ = ZoneInfo("Asia/Taipei")
ROOT = Path(__file__).resolve().parent
STAGE1_DIR = ROOT / "data" / "stage1"
INST_DIR = STAGE1_DIR / "institutional"
FUND_FILE = STAGE1_DIR / "fundamentals_latest.csv"

TWSE_T86 = "https://www.twse.com.tw/fund/T86"
TPEX_TRUST = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_trading"

TWSE_REVENUE = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TPEX_REVENUE = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"

TWSE_EPS_ENDPOINTS = [
    "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci",
    "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_basi",
    "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_bd",
    "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_fh",
    "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ins",
    "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_mim",
]
TPEX_EPS_ENDPOINTS = [
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci",
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_basi",
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_bd",
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_fh",
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ins",
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_mim",
]

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

def _find_key(d, includes, excludes=()):
    for k in d.keys():
        kl = str(k).lower()
        if all(str(x).lower() in kl for x in includes) and not any(str(x).lower() in kl for x in excludes):
            return k
    return None

def _common_code(x):
    s = str(x).strip()
    return s if s.isdigit() and len(s) == 4 and not s.startswith("0") else ""

# ---------------- 投信 ----------------

def fetch_twse_trust_for_date(d: date):
    js = _get_json(
        TWSE_T86,
        params={"response": "json", "date": d.strftime("%Y%m%d"), "selectType": "ALLBUT0999"},
    )
    wanted_code = "證券代號"
    wanted_name = "證券名稱"
    wanted_net = "投信買賣超股數"

    rows = []
    tables = js.get("tables", [])
    for t in tables:
        fields = t.get("fields", [])
        if wanted_code not in fields or wanted_net not in fields:
            continue
        ix = {f: fields.index(f) for f in [wanted_code, wanted_name, wanted_net] if f in fields}
        for r in t.get("data", []):
            sid = _common_code(r[ix[wanted_code]])
            if not sid:
                continue
            rows.append({
                "date": d.isoformat(),
                "market": "TWSE",
                "stock_id": sid,
                "name": str(r[ix[wanted_name]]).strip() if wanted_name in ix else "",
                "trust_net": _num(r[ix[wanted_net]]),
            })
        if rows:
            break

    return pd.DataFrame(rows)

def fetch_tpex_trust_today():
    rows = _get_json(TPEX_TRUST, tpex_fallback=True)
    today = datetime.now(TZ).date().isoformat()
    out = []

    for d in rows:
        code = _first_value(d, [
            "SecuritiesCompanyCode", "Code", "證券代號", "股票代號", "公司代號"
        ])
        sid = _common_code(code)
        if not sid:
            continue

        name = _first_value(d, [
            "CompanyName", "SecuritiesCompanyName", "Name", "證券名稱", "股票名稱", "公司名稱"
        ]) or ""

        # 此 endpoint 本身就是「投信買賣超彙總表」。
        # 先找中文「買賣超」，再找 Difference / Net 類欄位。
        net_key = _find_key(d, ["買賣超"])
        if net_key is None:
            net_key = _find_key(d, ["difference"])
        if net_key is None:
            net_key = _find_key(d, ["net"])

        net = _num(d.get(net_key)) if net_key else np.nan

        out.append({
            "date": today,
            "market": "TPEX",
            "stock_id": sid,
            "name": str(name).strip(),
            "trust_net": net,
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
        return pd.DataFrame(columns=["date", "market", "stock_id", "name", "trust_net"])

    frames = []
    for p in files:
        try:
            frames.append(pd.read_csv(p, dtype={"stock_id": str}))
        except Exception:
            pass

    if not frames:
        return pd.DataFrame(columns=["date", "market", "stock_id", "name", "trust_net"])

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
    初買定義（可調）：
    今日投信買賣超 > 0，且前 N 個「已有投信資料的交易日」皆 <= 0。
    若歷史不足 N+1 筆，標記「資料不足」，不自行猜。
    """
    h = load_institutional_history()
    if h.empty:
        return pd.DataFrame(columns=[
            "market","stock_id","trust_net","trust_first_buy","trust_streak",
            "trust_history_count","trust_status"
        ])

    rows = []
    for (market, sid), g in h.groupby(["market", "stock_id"]):
        g = g.sort_values("date").dropna(subset=["trust_net"])
        if g.empty:
            continue

        latest = g.iloc[-1]
        current = latest["trust_net"]
        previous = g.iloc[:-1].tail(lookback)
        count = len(g)

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
            "trust_history_count": count,
            "trust_status": status,
        })

    return pd.DataFrame(rows)

# ---------------- 營收 ----------------

def _parse_revenue_rows(rows, market):
    out = []
    for d in rows:
        sid = _common_code(_first_value(d, [
            "公司代號", "證券代號", "股票代號", "Code", "CompanyCode"
        ]))
        if not sid:
            continue

        name = _first_value(d, ["公司名稱", "證券名稱", "Name", "CompanyName"]) or ""

        yoy_key = (
            _find_key(d, ["去年同月", "增減"])
            or _find_key(d, ["去年同月增減"])
            or _find_key(d, ["year", "month"])
        )
        cum_key = (
            _find_key(d, ["累計", "前期", "增減"])
            or _find_key(d, ["累計", "增減"])
            or _find_key(d, ["cumulative", "change"])
        )

        month_yoy = _num(d.get(yoy_key)) if yoy_key else np.nan
        cum_yoy = _num(d.get(cum_key)) if cum_key else np.nan

        period = _first_value(d, ["資料年月", "年月", "YearMonth", "DataYearMonth"]) or ""

        out.append({
            "market": market,
            "stock_id": sid,
            "name": str(name).strip(),
            "revenue_period": str(period).strip(),
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
        frames.append(df)
        report["TWSE_revenue"] = len(df)
    except Exception as e:
        report["TWSE_revenue_error"] = str(e)

    try:
        rows = _get_json(TPEX_REVENUE, tpex_fallback=True)
        df = _parse_revenue_rows(rows, "TPEX")
        frames.append(df)
        report["TPEX_revenue"] = len(df)
    except Exception as e:
        report["TPEX_revenue_error"] = str(e)

    if not frames:
        return pd.DataFrame(), report

    x = pd.concat(frames, ignore_index=True)
    return x.drop_duplicates(["market", "stock_id"], keep="last"), report

# ---------------- EPS ----------------

def _parse_eps_rows(rows, market):
    out = []
    for d in rows:
        sid = _common_code(_first_value(d, [
            "公司代號", "證券代號", "股票代號", "Code", "CompanyCode"
        ]))
        if not sid:
            continue

        name = _first_value(d, ["公司名稱", "證券名稱", "Name", "CompanyName"]) or ""

        eps_key = None
        for k in d.keys():
            ks = str(k)
            if "基本每股盈餘" in ks or ("每股盈餘" in ks and "稀釋" not in ks):
                eps_key = k
                break
        if eps_key is None:
            eps_key = _find_key(d, ["eps"])

        eps = _num(d.get(eps_key)) if eps_key else np.nan

        year = _first_value(d, ["年度", "Year", "資料年度"]) or ""
        quarter = _first_value(d, ["季別", "季", "Quarter", "資料季別"]) or ""

        out.append({
            "market": market,
            "stock_id": sid,
            "name": str(name).strip(),
            "eps_year": str(year).strip(),
            "eps_quarter": str(quarter).strip(),
            "eps_cumulative": eps,
        })
    return pd.DataFrame(out)

def fetch_eps_latest():
    frames = []
    report = {"TWSE_eps_endpoints": 0, "TPEX_eps_endpoints": 0}

    for url in TWSE_EPS_ENDPOINTS:
        try:
            rows = _get_json(url)
            df = _parse_eps_rows(rows, "TWSE")
            if not df.empty:
                frames.append(df)
            report["TWSE_eps_endpoints"] += 1
        except Exception as e:
            report.setdefault("TWSE_eps_errors", []).append(str(e))

    for url in TPEX_EPS_ENDPOINTS:
        try:
            rows = _get_json(url, tpex_fallback=True)
            df = _parse_eps_rows(rows, "TPEX")
            if not df.empty:
                frames.append(df)
            report["TPEX_eps_endpoints"] += 1
        except Exception as e:
            report.setdefault("TPEX_eps_errors", []).append(str(e))

    if not frames:
        return pd.DataFrame(), report

    x = pd.concat(frames, ignore_index=True)
    x = x.dropna(subset=["eps_cumulative"])
    return x.drop_duplicates(["market", "stock_id"], keep="last"), report

def collect_fundamentals():
    ensure_stage1_dirs()
    rev, rev_report = fetch_revenue_latest()
    eps, eps_report = fetch_eps_latest()

    if rev.empty and eps.empty:
        return pd.DataFrame(), {"revenue": rev_report, "eps": eps_report}

    if rev.empty:
        x = eps.copy()
    elif eps.empty:
        x = rev.copy()
    else:
        x = rev.merge(
            eps[["market","stock_id","eps_year","eps_quarter","eps_cumulative"]],
            on=["market","stock_id"],
            how="outer",
        )

    x["revenue_double_growth"] = (
        pd.to_numeric(x.get("revenue_month_yoy"), errors="coerce") > 0
    ) & (
        pd.to_numeric(x.get("revenue_cum_yoy"), errors="coerce") > 0
    )

    x["eps_positive"] = pd.to_numeric(
        x.get("eps_cumulative"), errors="coerce"
    ) > 0

    x.to_csv(FUND_FILE, index=False, encoding="utf-8-sig")
    return x, {"revenue": rev_report, "eps": eps_report}

def load_fundamentals():
    if not FUND_FILE.exists():
        return pd.DataFrame()
    x = pd.read_csv(FUND_FILE, dtype={"stock_id": str})
    for c in ["revenue_month_yoy","revenue_cum_yoy","eps_cumulative"]:
        if c in x.columns:
            x[c] = pd.to_numeric(x[c], errors="coerce")
    for c in ["revenue_double_growth","eps_positive"]:
        if c in x.columns:
            x[c] = x[c].astype(str).str.lower().map({"true": True, "false": False}).fillna(False)
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
            on=["market","stock_id"],
            how="outer",
            suffixes=("", "_fund"),
        )

    # 第一階段先當「確認／排序」，不是硬淘汰。
    x["stage1_score"] = 0

    if "trust_first_buy" in x:
        x.loc[x["trust_first_buy"] == True, "stage1_score"] += 15
    if "trust_net" in x:
        x.loc[pd.to_numeric(x["trust_net"], errors="coerce") > 0, "stage1_score"] += 6
    if "revenue_double_growth" in x:
        x.loc[x["revenue_double_growth"] == True, "stage1_score"] += 10
    if "eps_positive" in x:
        x.loc[x["eps_positive"] == True, "stage1_score"] += 10

    return x
