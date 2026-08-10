
import streamlit as st
import pandas as pd
from yts_engine import *
from yts_engine import load_history

st.set_page_config(page_title="YTS v0.7",page_icon="📈",layout="wide",initial_sidebar_state="collapsed")
ensure_dirs()
st.title("YTS 台股多頭突破回測掃描器 v0.7")
st.caption("手機候選排序版｜歷史資料庫＋多日掃描｜第一根不追")

hist=load_history()

with st.sidebar:
    if st.button("🚀 執行今日掃描",use_container_width=True,type="primary"):
        live,report=fetch_today();st.json(report)
        if not live.empty:
            live["date"]=pd.to_datetime(live["date"]).dt.date
            hist=pd.concat([hist,live],ignore_index=True).drop_duplicates(["market","stock_id","date"],keep="last")

if hist.empty:
    st.warning("尚無歷史資料");st.stop()

s=snapshot(hist);dates=sorted(hist.date.unique())
a,b,c,d=st.columns(4)
a.metric("交易日",len(dates));b.metric("最新",str(dates[-1]));c.metric("股票數",hist.stock_id.nunique());d.metric("可算60MA",int((s.days>=60).sum()))

tabs=st.tabs(["🔥 YTS候選","⭐ 優先看","📊 多日診斷","📋 全市場快照"])
cand=yts_candidates(hist)

with tabs[0]:
    st.subheader("今日客觀初篩")
    st.caption("Close > 20MA；當日量 ≥ 前20日平均量1.5倍（不含當日）。")
    if cand.empty:
        st.info("目前無候選，或歷史尚未滿21個交易日。")
    else:
        show=cand[["stock_id","name","close","ma20","ma60","vol_ratio20","yts_score","stage","action_hint"]].copy()
        show.columns=["代號","名稱","收盤","20MA","60MA","20日量比","YTS分數","階段","建議"]
        st.dataframe(show,use_container_width=True,hide_index=True,
            column_config={
                "收盤":st.column_config.NumberColumn(format="%.2f"),
                "20MA":st.column_config.NumberColumn(format="%.2f"),
                "60MA":st.column_config.NumberColumn(format="%.2f"),
                "20日量比":st.column_config.NumberColumn(format="%.2fx"),
                "YTS分數":st.column_config.ProgressColumn(min_value=0,max_value=100)
            })
        st.warning("YTS分數只是排序工具，不是勝率；整理型態與真正頸線仍需人工看圖確認。")

with tabs[1]:
    st.subheader("⭐ 優先人工看圖")
    if cand.empty:
        st.info("目前沒有候選。")
    else:
        priority=cand[(~cand["stage"].str.contains("第一根不追",na=False))&(cand["yts_score"]>=60)].copy()
        if priority.empty:
            st.info("目前沒有同時達到 YTS分數≥60 且排除『第一根不追』的候選。")
        else:
            for _,r in priority.head(15).iterrows():
                st.markdown(f"### {r['stock_id']} {r['name']}｜YTS {int(r['yts_score'])}")
                c1,c2,c3,c4=st.columns(4)
                c1.metric("收盤",f"{r['close']:.2f}")
                c2.metric("20MA",f"{r['ma20']:.2f}" if pd.notna(r['ma20']) else "-")
                c3.metric("量比",f"{r['vol_ratio20']:.2f}x")
                c4.metric("收腳",f"{r['foot_ratio']:.0%}" if pd.notna(r['foot_ratio']) else "-")
                st.write(f"**階段：** {r['stage']}")
                st.write("**下一步：** 人工確認整理區、真正頸線、大量K支撐、壓力與籌碼。")
                st.divider()

with tabs[2]:
    m=s[s.days>=21].copy()
    if not m.empty:
        m["20日價格突破"]=m.close>m.prior20_high
        m["量能1.5倍"]=m.vol_ratio20>=1.5
        m["20MA>60MA"]=m.ma20>m.ma60
        st.dataframe(m[["date","market","stock_id","name","close","ma20","ma60","prior20_high","prior60_high","vol_ratio20","20日價格突破","量能1.5倍","20MA>60MA"]],use_container_width=True,hide_index=True)

with tabs[3]:
    st.dataframe(s,use_container_width=True,hide_index=True)
