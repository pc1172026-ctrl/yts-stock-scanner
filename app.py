
import streamlit as st
import pandas as pd
from yts_engine import *
from yts_engine import load_history

st.set_page_config(
    page_title="YTS v0.8",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

ensure_dirs()

st.title("YTS 台股多頭突破回測掃描器 v0.8")
st.caption("初篩＋精選雙層版｜第一根不追｜優先找第一次回測")

hist = load_history()

with st.sidebar:
    st.header("📱 每日操作")
    if st.button("🚀 執行今日掃描", use_container_width=True, type="primary"):
        live, report = fetch_today()
        st.json(report)
        if not live.empty:
            live["date"] = pd.to_datetime(live["date"]).dt.date
            hist = pd.concat([hist, live], ignore_index=True).drop_duplicates(
                ["market", "stock_id", "date"], keep="last"
            )

if hist.empty:
    st.warning("尚無歷史資料")
    st.stop()

s = snapshot(hist)
dates = sorted(hist.date.unique())

a, b, c, d = st.columns(4)
a.metric("交易日", len(dates))
b.metric("最新", str(dates[-1]))
c.metric("股票數", hist.stock_id.nunique())
d.metric("可算60MA", int((s.days >= 60).sum()))

cand = yts_candidates(hist)

tabs = st.tabs([
    "🔥 初篩候選",
    "🎯 精選候選",
    "⭐ 優先看",
    "📊 多日診斷",
    "📋 全市場快照"
])

with tabs[0]:
    st.subheader("🔥 初篩候選")
    st.caption("條件：Close > 20MA；當日量 ≥ 前20日平均量1.5倍（不含當日）。")
    if cand.empty:
        st.info("目前無候選，或歷史尚未滿21個交易日。")
    else:
        show = cand[
            ["stock_id", "name", "close", "ma20", "ma60",
             "vol_ratio20", "yts_score", "stage", "action_hint"]
        ].copy()

        show.columns = [
            "代號", "名稱", "收盤", "20MA", "60MA",
            "20日量比", "YTS分數", "階段", "建議"
        ]

        st.dataframe(
            show,
            use_container_width=True,
            hide_index=True,
            column_config={
                "收盤": st.column_config.NumberColumn(format="%.2f"),
                "20MA": st.column_config.NumberColumn(format="%.2f"),
                "60MA": st.column_config.NumberColumn(format="%.2f"),
                "20日量比": st.column_config.NumberColumn(format="%.2fx"),
                "YTS分數": st.column_config.ProgressColumn(min_value=0, max_value=100),
            },
        )

        st.warning("初篩只是候選池，不是買進名單。第一根突破不追，仍需再看位置、回測與收腳。")

with tabs[1]:
    st.subheader("🎯 精選候選")
    st.caption(
        "嚴格條件：MA20 > MA60、量比1.5～4倍、距MA20在0～8%、排除第一根突破、收腳≥50%。"
    )

    if cand.empty:
        st.info("目前沒有初篩候選。")
    else:
        refined = cand.copy()

        refined["距MA20%"] = (refined["close"] / refined["ma20"] - 1) * 100
        refined["收腳%"] = refined["foot_ratio"] * 100

        refined = refined[
            refined["ma60"].notna()
            & (refined["ma20"] > refined["ma60"])
            & (refined["vol_ratio20"] >= 1.5)
            & (refined["vol_ratio20"] <= 4.0)
            & (refined["距MA20%"] >= 0)
            & (refined["距MA20%"] <= 8)
            & (refined["收腳%"] >= 50)
            & (~refined["stage"].str.contains("第一根不追", na=False))
        ].copy()

        # 更接近「回測支撐＋收腳」的標的優先
        refined["回測加分"] = 0
        refined.loc[
            refined["stage"].str.contains("嚴格收腳", na=False), "回測加分"
        ] = 20
        refined.loc[
            refined["stage"].str.contains("一般收腳", na=False), "回測加分"
        ] = 12
        refined.loc[
            refined["stage"].str.contains("接近20日高", na=False), "回測加分"
        ] = 6

        refined["精選分數"] = (refined["yts_score"] + refined["回測加分"]).clip(upper=100)

        refined = refined.sort_values(
            ["精選分數", "yts_score", "vol_ratio20"],
            ascending=[False, False, False]
        ).head(15)

        if refined.empty:
            st.info("今天沒有符合嚴格精選條件的標的。這反而代表不必勉強出手。")
        else:
            show = refined[
                [
                    "stock_id", "name", "close", "ma20", "ma60",
                    "vol_ratio20", "距MA20%", "收腳%",
                    "精選分數", "stage"
                ]
            ].copy()

            show.columns = [
                "代號", "名稱", "收盤", "20MA", "60MA",
                "20日量比", "距20MA%", "收腳%",
                "精選分數", "階段"
            ]

            st.dataframe(
                show,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "收盤": st.column_config.NumberColumn(format="%.2f"),
                    "20MA": st.column_config.NumberColumn(format="%.2f"),
                    "60MA": st.column_config.NumberColumn(format="%.2f"),
                    "20日量比": st.column_config.NumberColumn(format="%.2fx"),
                    "距20MA%": st.column_config.NumberColumn(format="%.1f%%"),
                    "收腳%": st.column_config.NumberColumn(format="%.0f%%"),
                    "精選分數": st.column_config.ProgressColumn(min_value=0, max_value=100),
                },
            )

            st.success(f"本次精選 {len(refined)} 檔；接著人工確認頸線、大量K、上方壓力與籌碼。")

with tabs[2]:
    st.subheader("⭐ 優先人工看圖")

    if cand.empty:
        st.info("目前沒有候選。")
    else:
        priority = cand.copy()
        priority["距MA20%"] = (priority["close"] / priority["ma20"] - 1) * 100

        priority = priority[
            (~priority["stage"].str.contains("第一根不追", na=False))
            & (priority["yts_score"] >= 60)
            & (priority["距MA20%"] <= 10)
        ].copy()

        priority = priority.sort_values(
            ["yts_score", "vol_ratio20"],
            ascending=[False, False]
        ).head(15)

        if priority.empty:
            st.info("目前沒有需要優先人工看圖的候選。")
        else:
            for _, r in priority.iterrows():
                st.markdown(f"### {r['stock_id']} {r['name']}｜YTS {int(r['yts_score'])}")

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("收盤", f"{r['close']:.2f}")
                c2.metric("20MA", f"{r['ma20']:.2f}" if pd.notna(r["ma20"]) else "-")
                c3.metric("量比", f"{r['vol_ratio20']:.2f}x")
                c4.metric("收腳", f"{r['foot_ratio']:.0%}" if pd.notna(r["foot_ratio"]) else "-")

                st.write(f"**階段：** {r['stage']}")
                st.write(
                    "**人工檢查：** 整理區／真正頸線／大量K支撐／上方壓力／籌碼集中度／是否第一次回測。"
                )
                st.divider()

with tabs[3]:
    st.subheader("📊 多日診斷")
    m = s[s.days >= 21].copy()

    if m.empty:
        st.info("資料不足。")
    else:
        m["20日價格突破"] = m.close > m.prior20_high
        m["量能1.5倍"] = m.vol_ratio20 >= 1.5
        m["20MA>60MA"] = m.ma20 > m.ma60
        m["距20MA%"] = (m["close"] / m["ma20"] - 1) * 100

        st.dataframe(
            m[
                [
                    "date", "market", "stock_id", "name",
                    "close", "ma20", "ma60",
                    "prior20_high", "prior60_high",
                    "vol_ratio20", "距20MA%",
                    "20日價格突破", "量能1.5倍", "20MA>60MA"
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

with tabs[4]:
    st.subheader("📋 全市場快照")
    st.dataframe(s, use_container_width=True, hide_index=True)
