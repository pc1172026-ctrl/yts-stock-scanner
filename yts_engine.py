
from __future__ import annotations
from pathlib import Path
from datetime import datetime, date
from zoneinfo import ZoneInfo
import re, time, io
import requests
import pandas as pd
import numpy as np

MARKET_TZ = ZoneInfo("Asia/Taipei")
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DAILY_DIR = DATA_DIR / "daily"
STATE_DIR = DATA_DIR / "state"
WATCHLIST_FILE = STATE_DIR / "watchlist.csv"
FEEDBACK_FILE = DATA_DIR / "feedback.csv"

TWSE_DAILY_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_DAILY = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TWSE_STOCK_DAY = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"

def ensure_dirs():
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

def _num(x):
    if x is None: return np.nan
    s = str(x).strip().replace(",", "").replace("--","").replace("---","")
    if s in {"","-","nan","None"}: return np.nan
    try: return float(s)
    except: return np.nan

def _pick(d, candidates):
    for k in candidates:
        if k in d and d[k] not in (None,""):
            return d[k]
    return None

def _is_stock(sid):
    return isinstance(sid,str) and sid.isdigit() and len(sid)==4

def roc_to_iso(s):
    m = re.match(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", str(s).strip())
    if not m: return None
    y,mn,d = map(int,m.groups())
    return date(y+1911,mn,d).isoformat()

def collect_today():
    ensure_dirs()
    today = datetime.now(MARKET_TZ).date().isoformat()
    frames, report = [], {}
    try:
        rows = requests.get(TWSE_DAILY_ALL,timeout=30).json()
        out=[]
        for d in rows:
            sid=str(_pick(d,["Code","證券代號"]) or "").strip()
            if not _is_stock(sid): continue
            out.append({"date":today,"market":"TWSE","stock_id":sid,
                        "name":str(_pick(d,["Name","證券名稱"]) or ""),
                        "open":_num(_pick(d,["OpeningPrice","開盤價"])),
                        "high":_num(_pick(d,["HighestPrice","最高價"])),
                        "low":_num(_pick(d,["LowestPrice","最低價"])),
                        "close":_num(_pick(d,["ClosingPrice","收盤價"])),
                        "volume":_num(_pick(d,["TradeVolume","成交股數"]))})
        frames.append(pd.DataFrame(out)); report["TWSE"]=len(out)
    except Exception as e:
        report["TWSE_error"]=str(e)

    try:
        rows = requests.get(TPEX_DAILY,timeout=30).json()
        out=[]
        for d in rows:
            sid=str(_pick(d,["SecuritiesCompanyCode","Code","股票代號","證券代號"]) or "").strip()
            if not _is_stock(sid): continue
            out.append({"date":today,"market":"TPEX","stock_id":sid,
                        "name":str(_pick(d,["CompanyName","SecuritiesCompanyName","Name","股票名稱","證券名稱"]) or ""),
                        "open":_num(_pick(d,["Open","OpenPrice","開盤"])),
                        "high":_num(_pick(d,["High","HighestPrice","最高"])),
                        "low":_num(_pick(d,["Low","LowestPrice","最低"])),
                        "close":_num(_pick(d,["Close","ClosePrice","收盤"])),
                        "volume":_num(_pick(d,["TradingShares","TradeVolume","成交股數","成交量"]))})
        frames.append(pd.DataFrame(out)); report["TPEX"]=len(out)
    except Exception as e:
        report["TPEX_error"]=str(e)

    if frames:
        df=pd.concat(frames,ignore_index=True)
        df=df[df.close.notna()].copy()
        path=DAILY_DIR/f"{today}.csv"
        df.to_csv(path,index=False,encoding="utf-8-sig")
        report["saved"]=len(df); report["file"]=str(path)
    return report

def fetch_twse_history(stock_id, months=6):
    today=datetime.now(MARKET_TZ).date()
    frames=[]
    for i in range(months):
        y=today.year; m=today.month-i
        while m<=0:
            y-=1; m+=12
        r=requests.get(TWSE_STOCK_DAY,params={"response":"json","date":f"{y}{m:02d}01","stockNo":stock_id},timeout=30)
        js=r.json()
        if not js.get("data"): continue
        f=pd.DataFrame(js["data"],columns=js["fields"]).rename(columns={
            "日期":"date","成交股數":"volume","開盤價":"open","最高價":"high","最低價":"low","收盤價":"close"})
        f["date"]=f["date"].map(roc_to_iso)
        for c in ["open","high","low","close","volume"]: f[c]=f[c].map(_num)
        f["stock_id"]=stock_id; f["market"]="TWSE"
        frames.append(f[["date","market","stock_id","open","high","low","close","volume"]])
        time.sleep(.1)
    return pd.concat(frames,ignore_index=True).drop_duplicates(["stock_id","date"]) if frames else pd.DataFrame()

def bootstrap_twse(stock_ids,months=6):
    ensure_dirs(); report=[]
    for sid in [str(x).strip() for x in stock_ids]:
        if not _is_stock(sid): continue
        try:
            df=fetch_twse_history(sid,months)
            if df.empty:
                report.append({"stock_id":sid,"status":"no_data"}); continue
            merge_into_daily(df)
            report.append({"stock_id":sid,"status":"ok","rows":len(df)})
        except Exception as e:
            report.append({"stock_id":sid,"status":"error","error":str(e)})
    return report

def import_official_history_csv(file_bytes, market, stock_id, name=""):
    """Import official TWSE/TPEx CSV downloaded by user.
    Flexible header matching, no OCR/guessing.
    """
    ensure_dirs()
    bio=io.BytesIO(file_bytes)
    attempts=[]
    for enc in ["utf-8-sig","utf-8","cp950","big5"]:
        try:
            bio.seek(0)
            df=pd.read_csv(bio,encoding=enc)
            attempts.append(df)
            break
        except Exception:
            continue
    if not attempts:
        raise ValueError("無法讀取CSV編碼")
    df=attempts[0]
    cols={str(c).strip():c for c in df.columns}
    def col(cands):
        for c in cands:
            if c in cols: return cols[c]
        return None
    dc=col(["日期","Date","date"])
    oc=col(["開盤價","開盤","Open","open"])
    hc=col(["最高價","最高","High","high"])
    lc=col(["最低價","最低","Low","low"])
    cc=col(["收盤價","收盤","Close","close"])
    vc=col(["成交股數","成交量","TradingShares","TradeVolume","volume"])
    if None in [dc,oc,hc,lc,cc,vc]:
        raise ValueError(f"CSV欄位不足，讀到欄位：{list(df.columns)}")
    out=pd.DataFrame()
    rawd=df[dc].astype(str)
    parsed=pd.to_datetime(rawd,errors="coerce")
    if parsed.isna().mean()>0.5:
        out["date"]=rawd.map(roc_to_iso)
    else:
        out["date"]=parsed.dt.date.astype(str)
    out["market"]=market
    out["stock_id"]=str(stock_id)
    out["name"]=name
    for new,old in [("open",oc),("high",hc),("low",lc),("close",cc),("volume",vc)]:
        out[new]=df[old].map(_num)
    out=out.dropna(subset=["date","close"])
    merge_into_daily(out)
    return len(out)

def merge_into_daily(df):
    for d,day in df.groupby("date"):
        path=DAILY_DIR/f"{d}.csv"
        if path.exists():
            old=pd.read_csv(path,dtype={"stock_id":str})
            merged=pd.concat([old,day],ignore_index=True)
            merged=merged.drop_duplicates(["stock_id","date"],keep="last")
        else:
            merged=day.copy()
        merged.to_csv(path,index=False,encoding="utf-8-sig")

def load_history():
    ensure_dirs()
    files=sorted(DAILY_DIR.glob("*.csv"))
    if not files: return pd.DataFrame()
    df=pd.concat([pd.read_csv(f,dtype={"stock_id":str}) for f in files],ignore_index=True)
    df["date"]=pd.to_datetime(df["date"],errors="coerce").dt.date
    for c in ["open","high","low","close","volume"]:
        df[c]=pd.to_numeric(df[c],errors="coerce")
    return df.dropna(subset=["date","stock_id"]).sort_values(["stock_id","date"]).drop_duplicates(["stock_id","date"],keep="last")

def add_indicators(df):
    x=df.copy().sort_values(["stock_id","date"])
    g=x.groupby("stock_id",group_keys=False)
    for n in [5,10,20,60]:
        x[f"ma{n}"]=g["close"].transform(lambda s,n=n:s.rolling(n,min_periods=n).mean())
    x["avg_volume_prev20"]=g["volume"].transform(lambda s:s.shift(1).rolling(20,min_periods=20).mean())
    x["volume_ratio_20"]=x["volume"]/x["avg_volume_prev20"]
    x["prev_volume"]=g["volume"].shift(1)
    rng=x["high"]-x["low"]
    x["foot_ratio"]=np.where(rng>0,(x["close"]-x["low"])/rng,np.nan)
    x["close_above_ma20"]=x["close"]>x["ma20"]
    x["ma20_above_ma60"]=x["ma20"]>x["ma60"]
    return x

def latest_snapshot(df):
    if df.empty:return df
    x=add_indicators(df)
    return x.groupby("stock_id",as_index=False).tail(1).reset_index(drop=True)

def objective_breakout_candidates(df):
    s=latest_snapshot(df)
    if s.empty:return s
    out=s[(s.close_above_ma20==True)&(s.volume_ratio_20>=1.5)].copy()
    out["stage"]="帶量候選（人工確認頸線/整理）"
    return out


def upsert_watchlist(stock_id,name="",breakout_date="",neckline=np.nan,support=np.nan,pressure=np.nan,
                     breakout_volume=np.nan,chip_score=0,note="",manual_support2=np.nan,
                     manual_support3=np.nan, support_tolerance_pct=1.5):
    ensure_dirs()
    row=pd.DataFrame([{
        "stock_id":str(stock_id),"name":name,"breakout_date":breakout_date,
        "neckline":neckline,"support":support,"manual_support2":manual_support2,
        "manual_support3":manual_support3,"pressure":pressure,
        "breakout_volume":breakout_volume,"chip_score":chip_score,
        "support_tolerance_pct":support_tolerance_pct,"note":note,
        "status":"等待第一次回測",
        "updated_at":datetime.now(MARKET_TZ).isoformat(timespec="seconds")
    }])
    if WATCHLIST_FILE.exists():
        old=pd.read_csv(WATCHLIST_FILE,dtype={"stock_id":str})
        old=old[old.stock_id!=str(stock_id)]
        row=pd.concat([old,row],ignore_index=True)
    row.to_csv(WATCHLIST_FILE,index=False,encoding="utf-8-sig")

def load_watchlist():
    if not WATCHLIST_FILE.exists(): return pd.DataFrame()
    return pd.read_csv(WATCHLIST_FILE,dtype={"stock_id":str})

def _near(a,b,tol_pct):
    if pd.isna(a) or pd.isna(b) or b==0: return False
    return abs(a-b)/abs(b) <= tol_pct/100.0

def _support_cluster(latest, r, tol_pct=1.5):
    """Count nearby support sources around today's low/close.
    Sources: confirmed neckline, manual support1/2/3, MA20, MA60.
    This is a proximity count only; it does NOT claim technical validity.
    """
    candidates=[]
    for label,key in [("頸線","neckline"),("人工支撐1","support"),
                      ("人工支撐2","manual_support2"),("人工支撐3","manual_support3")]:
        val=r.get(key,np.nan)
        if pd.notna(val) and val>0: candidates.append((label,float(val)))
    for label,key in [("20MA","ma20"),("60MA","ma60")]:
        val=latest.get(key,np.nan)
        if pd.notna(val) and val>0: candidates.append((label,float(val)))
    ref_price=float(latest["low"]) if pd.notna(latest.get("low")) else float(latest["close"])
    matched=[(lab,val) for lab,val in candidates if _near(ref_price,val,tol_pct) or (latest["low"]<=val<=latest["high"])]
    labels=[x[0] for x in matched]
    vals=[x[1] for x in matched]
    center=float(np.mean(vals)) if vals else np.nan
    return len(matched), ", ".join(labels), center

def evaluate_watchlist(df,tolerance=0.015):
    w=load_watchlist()
    if w.empty or df.empty:return pd.DataFrame()
    x=add_indicators(df)
    rows=[]
    for _,r in w.iterrows():
        h=x[x.stock_id==str(r.stock_id)].sort_values("date")
        if h.empty: continue
        latest=h.iloc[-1]
        ref=r.get("support",np.nan)
        if pd.isna(ref): ref=r.get("neckline",np.nan)
        tol_pct=float(r.get("support_tolerance_pct", tolerance*100) or tolerance*100)
        rec=dict(r)
        rec.update({
            "date":latest.date,"close":latest.close,"high":latest.high,"low":latest.low,
            "ma20":latest.ma20,"ma60":latest.ma60,"volume":latest.volume,
            "volume_ratio_20":latest.volume_ratio_20,"foot_ratio":latest.foot_ratio,
        })
        bv=r.get("breakout_volume",np.nan)
        rec["retest_vs_breakout_volume"]=latest.volume/bv if pd.notna(bv) and bv>0 else np.nan
        p=r.get("pressure",np.nan)
        rec["pressure_distance_pct"]=(p-latest.close)/latest.close if pd.notna(p) and p>0 else np.nan
        count, labels, center = _support_cluster(latest, rec, tol_pct=tol_pct)
        rec["support_cluster_count"]=count
        rec["support_cluster_labels"]=labels
        rec["support_cluster_center"]=center
        rec["multiple_support"] = count >= 2
        if pd.isna(ref):
            state="待人工設定支撐"
        else:
            near=abs(latest.low-ref)/ref<=tol_pct/100.0 or (latest.low<=ref<=latest.high)
            if not near: state="尚未回測"
            elif latest.close>=ref and latest.foot_ratio>=2/3: state="回測＋嚴格收腳確認"
            elif latest.close>=ref and latest.foot_ratio>=0.5: state="回測＋一般收腳確認"
            elif latest.close>=ref: state="回測到位但收腳不足"
            else: state="回測但收盤未站回支撐"
        rec["retest_state"]=state
        rec["yts_score"]=score_row(rec)
        rows.append(rec)
    return pd.DataFrame(rows)

def score_row(r):
    """Transparent v0.4 score for sorting only; not a validated win rate."""
    score=0
    if pd.notna(r.get("ma20")) and r.get("close",0)>r["ma20"]: score+=20
    if pd.notna(r.get("ma60")) and pd.notna(r.get("ma20")) and r["ma20"]>r["ma60"]: score+=10
    state=r.get("retest_state","")
    if "回測" in state: score+=15
    if "嚴格收腳" in state: score+=20
    elif "一般收腳" in state: score+=12
    elif "收腳不足" in state: score+=4
    vr=r.get("retest_vs_breakout_volume",np.nan)
    if pd.notna(vr):
        if vr<=0.4: score+=15
        elif vr<=0.6: score+=10
        elif vr<=0.8: score+=5
    pdist=r.get("pressure_distance_pct",np.nan)
    if pd.notna(pdist):
        if pdist>=0.08: score+=10
        elif pdist>=0.05: score+=6
        elif pdist<0.03: score-=8
    cnt=int(r.get("support_cluster_count",0) or 0)
    if cnt>=4: score+=15
    elif cnt==3: score+=12
    elif cnt==2: score+=8
    try: score+=int(r.get("chip_score",0))
    except: pass
    return max(0,min(100,score))

def save_manual_feedback(stock_id,result,reason):
    row=pd.DataFrame([{"timestamp":datetime.now(MARKET_TZ).isoformat(timespec="seconds"),
                       "stock_id":str(stock_id),"result":result,"reason":reason}])
    if FEEDBACK_FILE.exists():
        old=pd.read_csv(FEEDBACK_FILE,dtype={"stock_id":str})
        row=pd.concat([old,row],ignore_index=True)
    row.to_csv(FEEDBACK_FILE,index=False,encoding="utf-8-sig")
