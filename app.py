
import streamlit as st
import pandas as pd
from yts_engine import *
from yts_engine import load_history
st.set_page_config(page_title="YTS v0.6",page_icon="📈",layout="wide")
ensure_dirs()
st.title("YTS 台股多頭突破回測掃描器 v0.6")
st.caption("歷史資料庫＋多日掃描｜第一根不追")

hist=load_history()
with st.sidebar:
    if st.button("🚀 執行今日掃描",use_container_width=True,type="primary"):
        live,report=fetch_today();st.json(report)
        if not live.empty:
            live["date"]=pd.to_datetime(live["date"]).dt.date
            hist=pd.concat([hist,live],ignore_index=True).drop_duplicates(["market","stock_id","date"],keep="last")
    st.divider()
    st.write("TPEx 過去歷史：請使用櫃買中心官方 CSV。")
    up=st.file_uploader("匯入官方歷史CSV",type=["csv"])
    market=st.selectbox("市場",["TPEX","TWSE"])
    sid=st.text_input("股票代號")
    name=st.text_input("名稱")
    if st.button("匯入CSV") and up:
        try:st.success(f"匯入 {import_official_csv(up.getvalue(),market,sid,name)} 筆")
        except Exception as e:st.error(str(e))

if hist.empty:
    st.warning("尚無歷史資料");st.stop()

s=snapshot(hist); dates=sorted(hist.date.unique())
a,b,c,d=st.columns(4)
a.metric("交易日",len(dates));b.metric("最新",str(dates[-1]));c.metric("股票數",hist.stock_id.nunique());d.metric("可算60MA",int((s.days>=60).sum()))

tabs=st.tabs(["🔥 YTS候選","📊 多日診斷","📋 全市場快照"])
with tabs[0]:
    x=yts_candidates(hist)
    if x.empty:
        st.info("目前無候選，或歷史尚未滿21個交易日。")
    else:
        cols=["date","market","stock_id","name","close","ma20","ma60","vol_ratio20","prior20_high","prior60_high","foot_ratio","strong_trend","stage"]
        st.dataframe(x[cols].sort_values("vol_ratio20",ascending=False),use_container_width=True,hide_index=True)
with tabs[1]:
    m=s[s.days>=21].copy()
    if not m.empty:
        m["20日價格突破"]=m.close>m.prior20_high
        m["量能1.5倍"]=m.vol_ratio20>=1.5
        m["20MA>60MA"]=m.ma20>m.ma60
        st.dataframe(m[["date","market","stock_id","name","close","ma20","ma60","prior20_high","prior60_high","vol_ratio20","20日價格突破","量能1.5倍","20MA>60MA"]],use_container_width=True,hide_index=True)
with tabs[2]:
    st.dataframe(s,use_container_width=True,hide_index=True)
