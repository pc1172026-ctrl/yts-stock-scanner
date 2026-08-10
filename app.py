
import streamlit as st
import pandas as pd

from yts_engine import (
    ensure_dirs, collect_today, load_repo_history, combine_history_with_live,
    latest_snapshot, objective_candidates, watchlist_analysis, load_watchlist
)

st.set_page_config(
    page_title="YTS 台股多頭突破回測掃描器 v0.5",
    page_icon="📈",
    layout="wide"
)
ensure_dirs()

st.title("YTS 台股多頭突破回測掃描器 v0.5")
st.caption("手機一鍵版｜GitHub 保存歷史｜TWSE＋TPEx｜第一根不追")

history = load_repo_history()

with st.sidebar:
    st.header("📱 每日操作")
    run_scan = st.button("🚀 執行今日掃描", use_container_width=True, type="primary")
    st.caption("按一次即可抓今天收盤資料並與 GitHub 歷史合併。")
    st.divider()

    if history.empty:
        st.warning("GitHub repository 尚無歷史行情。請先啟用 GitHub Actions，每個交易日資料會自動累積。")
    else:
        dates = sorted(history["date"].dropna().unique())
        st.success(f"GitHub 已保存 {len(dates)} 個交易日")
        st.write(f"最早：{dates[0]}")
        st.write(f"最新：{dates[-1]}")

    st.divider()
    st.markdown("""
**固定規則**
- Close > 20MA
- 20MA > 60MA：加分
- 當日量 ≥ 前20日均量 × 1.5
- 前20日均量不含當日
- 突破第一根不追
- 等第一次回測
- 多重支撐＋尾盤收腳才升級
""")

live = pd.DataFrame()
report = {}
warnings_list = []

if run_scan:
    with st.spinner("下載 TWSE / TPEx 官方行情並執行 YTS..."):
        live, report, warnings_list = collect_today(save_local=False)

    if report:
        c1, c2 = st.columns(2)
        c1.metric("TWSE 今日資料", report.get("TWSE", 0))
        c2.metric("TPEx 今日資料", report.get("TPEX", 0))

    for w in warnings_list:
        st.warning(w)

combined = combine_history_with_live(history, live)

if combined.empty:
    st.info("目前沒有可分析的行情。請按左側「執行今日掃描」，並啟用 GitHub Actions 累積歷史。")
    st.stop()

snap = latest_snapshot(combined)
latest_date = snap["date"].max() if not snap.empty else None
enough20 = int((snap["history_days"] >= 21).sum()) if not snap.empty else 0
enough60 = int((snap["history_days"] >= 60).sum()) if not snap.empty else 0

m1, m2, m3, m4 = st.columns(4)
m1.metric("分析日期", str(latest_date))
m2.metric("股票數", f"{snap['stock_id'].nunique():,}")
m3.metric("可算20日條件", f"{enough20:,}")
m4.metric("可算60MA", f"{enough60:,}")

tabs = st.tabs(["🔥 今日帶量候選", "🎯 回測觀察", "📋 全市場快照", "ℹ️ 使用說明"])

with tabs[0]:
    st.subheader("今日客觀帶量候選")
    cand = objective_candidates(combined)
    if cand.empty:
        if enough20 == 0:
            st.warning("目前尚未累積至少21個交易日，因此不能正確計算前20日均量與20MA。這不是『0檔符合』。")
        else:
            st.info("目前資料中沒有同時符合 Close > 20MA 且量能 ≥ 前20日均量1.5倍的股票。")
    else:
        cols = [
            "date","market","stock_id","name","close","ma20","ma60",
            "volume_ratio_20","foot_ratio","trend_grade","stage"
        ]
        st.dataframe(
            cand[cols].sort_values(["volume_ratio_20"], ascending=False),
            use_container_width=True, hide_index=True
        )
        st.warning("這裡只做客觀前置篩選。『整理漂亮／頸線突破』仍由你人工看圖確認；今天才突破的第一根不追。")

with tabs[1]:
    st.subheader("既有觀察股：第一次回測")
    wl = load_watchlist()
    if wl.empty:
        st.info("config/watchlist.csv 尚未設定觀察股。可在 GitHub 直接編輯該檔。")
    else:
        res = watchlist_analysis(combined)
        if res.empty:
            st.info("觀察股目前沒有可分析資料。")
        else:
            cols = [
                "stock_id","name","date","close","support","pressure",
                "pressure_distance_pct","ma20","ma60",
                "retest_vs_breakout_volume","foot_ratio",
                "retest_state","chip_score","yts_score","note"
            ]
            cols = [c for c in cols if c in res.columns]
            st.dataframe(
                res[cols].sort_values("yts_score", ascending=False),
                use_container_width=True, hide_index=True
            )
            st.caption("YTS Score 是排序工具，不等同勝率。")

with tabs[2]:
    cols = [
        "date","market","stock_id","name","close","ma20","ma60",
        "volume_ratio_20","foot_ratio","history_days"
    ]
    cols = [c for c in cols if c in snap.columns]
    st.dataframe(snap[cols], use_container_width=True, hide_index=True)

with tabs[3]:
    st.markdown("""
### 手機每天怎麼用
1. 打開 YTS。
2. 按 **🚀 執行今日掃描**。
3. 先看「今日帶量候選」。
4. 你人工確認整理型態與頸線。
5. 確認後把股票加入 `config/watchlist.csv`。
6. 後續在「回測觀察」等第一次回測與收腳。

### 歷史資料為什麼不會再消失？
v0.5 的每日行情由 **GitHub Actions** 寫入 repository 的 `data/daily/`。
Streamlit 重啟後會重新從 GitHub 部署內容讀取，所以不依賴暫存磁碟。

### 資料成熟度
- 至少 21 個交易日：可算 20MA、前20日均量與 1.5 倍條件。
- 至少 60 個交易日：可完整判斷 `20MA > 60MA`。
- 在資料不足前，程式會寫「資料不足」，不會把它誤稱為 0 檔。

### TPEx TLS fallback
若 Community Cloud 無法驗證 TPEx 的公開資料憑證鏈，v0.5 只針對 **無帳密的公開行情 GET** 使用唯讀 TLS fallback。
不會把這個做法用於任何登入、帳號或私人資料。
""")
