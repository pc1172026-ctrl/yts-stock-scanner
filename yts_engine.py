
from pathlib import Path
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import io, re, time
import numpy as np
import pandas as pd
import requests
import urllib3

TZ=ZoneInfo("Asia/Taipei")
ROOT=Path(__file__).resolve().parent
DAILY=ROOT/"data"/"daily"
WATCH=ROOT/"config"/"watchlist.csv"
TWSE_ALL="https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TWSE_MI="https://www.twse.com.tw/exchangeReport/MI_INDEX"
TPEX_ALL="https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

def ensure_dirs():
    DAILY.mkdir(parents=True,exist_ok=True)
    WATCH.parent.mkdir(parents=True,exist_ok=True)

def num(x):
    if x is None:return np.nan
    s=str(x).strip().replace(",","").replace("--","")
    try:return float(s)
    except:return np.nan

def pick(d,*ks):
    for k in ks:
        if k in d and d[k] not in (None,""):return d[k]

def common(s):
    s=str(s).strip()
    return s.isdigit() and len(s)==4 and not s.startswith("0")

def get_json(url,params=None,tpex=False):
    try:
        r=requests.get(url,params=params,timeout=45);r.raise_for_status()
        return r.json()
    except requests.exceptions.SSLError:
        if not tpex: raise
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r=requests.get(url,params=params,timeout=45,verify=False);r.raise_for_status()
        return r.json()

def fetch_today():
    today=datetime.now(TZ).date().isoformat()
    frames=[]; report={}
    try:
        rows=get_json(TWSE_ALL); out=[]
        for d in rows:
            sid=str(pick(d,"Code","證券代號") or "").strip()
            if not common(sid):continue
            out.append(dict(date=today,market="TWSE",stock_id=sid,name=str(pick(d,"Name","證券名稱") or ""),
                open=num(pick(d,"OpeningPrice","開盤價")),high=num(pick(d,"HighestPrice","最高價")),
                low=num(pick(d,"LowestPrice","最低價")),close=num(pick(d,"ClosingPrice","收盤價")),
                volume=num(pick(d,"TradeVolume","成交股數"))))
        frames.append(pd.DataFrame(out));report["TWSE"]=len(out)
    except Exception as e: report["TWSE_error"]=str(e)
    try:
        rows=get_json(TPEX_ALL,tpex=True); out=[]
        for d in rows:
            sid=str(pick(d,"SecuritiesCompanyCode","Code","股票代號","證券代號") or "").strip()
            if not common(sid):continue
            out.append(dict(date=today,market="TPEX",stock_id=sid,name=str(pick(d,"CompanyName","SecuritiesCompanyName","Name","股票名稱","證券名稱") or ""),
                open=num(pick(d,"Open","OpenPrice","開盤")),high=num(pick(d,"High","HighestPrice","最高")),
                low=num(pick(d,"Low","LowestPrice","最低")),close=num(pick(d,"Close","ClosePrice","收盤")),
                volume=num(pick(d,"TradingShares","TradeVolume","成交股數","成交量"))))
        frames.append(pd.DataFrame(out));report["TPEX"]=len(out)
    except Exception as e: report["TPEX_error"]=str(e)
    df=pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()
    return df,report

def merge_daily(df):
    ensure_dirs()
    for d,day in df.groupby("date"):
        p=DAILY/f"{d}.csv"
        if p.exists():
            old=pd.read_csv(p,dtype={"stock_id":str})
            day=pd.concat([old,day],ignore_index=True).drop_duplicates(["market","stock_id","date"],keep="last")
        day.to_csv(p,index=False,encoding="utf-8-sig")

def parse_mi(js,d):
    wanted={"證券代號","證券名稱","成交股數","開盤價","最高價","最低價","收盤價"}
    out=[]
    for t in js.get("tables",[]):
        f=t.get("fields",[])
        if not wanted.issubset(set(f)):continue
        ix={k:f.index(k) for k in wanted}
        for r in t.get("data",[]):
            sid=str(r[ix["證券代號"]]).strip()
            if not common(sid):continue
            out.append(dict(date=d.isoformat(),market="TWSE",stock_id=sid,name=str(r[ix["證券名稱"]]),
                open=num(r[ix["開盤價"]]),high=num(r[ix["最高價"]]),low=num(r[ix["最低價"]]),
                close=num(r[ix["收盤價"]]),volume=num(r[ix["成交股數"]])))
        if out:break
    return pd.DataFrame(out)

def bootstrap_twse(days=150):
    today=datetime.now(TZ).date(); start=today-timedelta(days=days)
    result={"trading_days":0,"rows":0,"errors":[]}
    d=start
    while d<=today:
        if d.weekday()<5:
            try:
                js=get_json(TWSE_MI,{"response":"json","date":d.strftime("%Y%m%d"),"type":"ALLBUT0999"})
                df=parse_mi(js,d)
                if not df.empty:
                    merge_daily(df);result["trading_days"]+=1;result["rows"]+=len(df)
            except Exception as e: result["errors"].append(f"{d}: {e}")
            time.sleep(.12)
        d+=timedelta(days=1)
    return result

def load_history():
    ensure_dirs()
    fs=sorted(DAILY.glob("*.csv"))
    if not fs:return pd.DataFrame()
    x=pd.concat([pd.read_csv(f,dtype={"stock_id":str}) for f in fs],ignore_index=True)
    x["date"]=pd.to_datetime(x["date"],errors="coerce").dt.date
    for c in ["open","high","low","close","volume"]:x[c]=pd.to_numeric(x[c],errors="coerce")
    return x.dropna(subset=["date","stock_id","close"]).sort_values(["market","stock_id","date"]).drop_duplicates(["market","stock_id","date"],keep="last")

def indicators(df):
    x=df.copy().sort_values(["market","stock_id","date"])
    g=x.groupby(["market","stock_id"],group_keys=False)
    for n in [5,10,20,60]:
        x[f"ma{n}"]=g["close"].transform(lambda s,n=n:s.rolling(n,min_periods=n).mean())
    x["avg_vol20_prev"]=g["volume"].transform(lambda s:s.shift(1).rolling(20,min_periods=20).mean())
    x["vol_ratio20"]=x["volume"]/x["avg_vol20_prev"]
    x["prior20_high"]=g["high"].transform(lambda s:s.shift(1).rolling(20,min_periods=20).max())
    x["prior60_high"]=g["high"].transform(lambda s:s.shift(1).rolling(60,min_periods=60).max())
    rng=x["high"]-x["low"]
    x["foot_ratio"]=np.where(rng>0,(x["close"]-x["low"])/rng,np.nan)
    x["days"]=g["close"].transform("count")
    return x

def snapshot(df):
    if df.empty:return df
    x=indicators(df)
    return x.groupby(["market","stock_id"],as_index=False).tail(1).reset_index(drop=True)

def yts_candidates(df):
    s=snapshot(df)
    if s.empty:return s
    ok=(s.days>=21)&(s.close>s.ma20)&(s.vol_ratio20>=1.5)
    out=s[ok].copy()
    out["strong_trend"]=out.ma20>out.ma60
    out["stage"]="帶量候選；需人工確認整理/頸線；第一根不追"
    return out

def import_official_csv(file_bytes,market,stock_id="",name=""):
    bio=io.BytesIO(file_bytes); df=None
    for enc in ["utf-8-sig","utf-8","cp950","big5"]:
        try:
            bio.seek(0);df=pd.read_csv(bio,encoding=enc);break
        except:pass
    if df is None:raise ValueError("CSV無法讀取")
    mp={str(c).strip():c for c in df.columns}
    def col(*xs):
        for x in xs:
            if x in mp:return mp[x]
    dc=col("日期","date","Date");oc=col("開盤價","開盤","open","Open");hc=col("最高價","最高","high","High")
    lc=col("最低價","最低","low","Low");cc=col("收盤價","收盤","close","Close");vc=col("成交股數","成交量","volume","TradeVolume")
    if None in [dc,oc,hc,lc,cc,vc]:raise ValueError(f"欄位不足：{list(df.columns)}")
    raw=df[dc].astype(str)
    parsed=pd.to_datetime(raw,errors="coerce")
    if parsed.notna().sum()<len(raw)/2:
        def roc(v):
            m=re.match(r"(\d{2,3})/(\d{1,2})/(\d{1,2})",str(v))
            if not m:return None
            y,mo,da=map(int,m.groups());return date(y+1911,mo,da).isoformat()
        dates=raw.map(roc)
    else:dates=parsed.dt.date.astype(str)
    out=pd.DataFrame({"date":dates,"market":market,"stock_id":str(stock_id),"name":name,
        "open":df[oc].map(num),"high":df[hc].map(num),"low":df[lc].map(num),"close":df[cc].map(num),"volume":df[vc].map(num)})
    out=out.dropna(subset=["date","close"]);merge_daily(out);return len(out)
