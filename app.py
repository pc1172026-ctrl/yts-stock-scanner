
import streamlit as st
import pandas as pd
from pathlib import Path
from yts_engine import *
from yts_engine import load_history
from stage1_data import stage1_snapshot, load_fundamentals, trust_snapshot

st.set_page_config(
    page_title="YTS v1.0 Stage1",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

ROOT_APP = Path(__file__).resolve().parent
WATCH_FILE = ROOT_APP / "config" / "watchlist.csv"
WATCH_COLS = ["market", "stock_id", "name", "support", "resistance", "note"]

def _txt(v):
    if pd.isna(v):
        return ""
    return str(v).strip()

def load_watchlist():
    WATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not WATCH_FILE.exists():
        return pd.DataFrame(columns=WATCH_COLS)
    try:
        w = pd.read_csv(WATCH_FILE, dtype={"market": str, "stock_id": str, "name": str})
    except Exception:
        return pd.DataFrame(columns=WATCH_COLS)
    for c in WATCH_COLS:
        if c not in w.columns:
            w[c] = ""
    w = w[WATCH_COLS].copy()
    w["stock_id"] = w["stock_id"].astype(str).str.strip()
    w["market"] = w["market"].fillna("").astype(str).str.strip()
    w["name"] = w["name"].fillna("").astype(str)
    return w.drop_duplicates(["market", "stock_id"], keep="last")

def save_watchlist(w):
    WATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    out = w.copy()
    for c in WATCH_COLS:
        if c not in out.columns:
            out[c] = ""
    out[WATCH_COLS].to_csv(WATCH_FILE, index=False, encoding="utf-8-sig")

def add_watch(row):
    w = load_watchlist()
    market = _txt(row.get("market", "TWSE")) or "TWSE"
    sid = _txt(row.get("stock_id", ""))
    name = _txt(row.get("name", ""))
    if not sid:
        return False
    hit = (w["market"] == market) & (w["stock_id"] == sid)
    if hit.any():
        if name:
            w.loc[hit, "name"] = name
    else:
        w = pd.concat([w, pd.DataFrame([{
            "market": market, "stock_id": sid, "name": name,
            "support": "", "resistance": "", "note": ""
        }])], ignore_index=True)
    save_watchlist(w)
    return True

def remove_watch(market, sid):
    w = load_watchlist()
    w = w[~((w["market"] == str(market)) & (w["stock_id"] == str(sid)))].copy()
    save_watchlist(w)

def watch_status(r):
    close = r.get("close")
    ma20 = r.get("ma20")
    ma60 = r.get("ma60")
    vr = r.get("vol_ratio20")
    foot = r.get("foot_ratio")

    if pd.notna(close) and pd.notna(ma60) and close < ma60:
        return "🔴 跌破60MA"
    if pd.notna(close) and pd.notna(ma20) and close < ma20:
        return "🟠 跌破20MA"
    if pd.notna(close) and pd.notna(ma20) and ma20 > 0:
        dist = (close / ma20 - 1) * 100
        if 0 <= dist <= 2:
            return "🟢 接近20MA／觀察回測"
    if pd.notna(vr) and vr >= 1.5 and pd.notna(foot) and foot >= 0.5:
        return "🔥 重新放量且收腳"
    if pd.notna(vr) and vr < 1.0:
        return "🟡 量縮整理"
    return "⚪ 持續觀察"

ensure_dirs()

st.title("YTS 台股多頭突破回測掃描器 v1.0｜第一階段")
st.caption("技術面＋投信初買＋營收雙成長＋最新累計EPS為正")

hist = load_history()
stage1 = stage1_snapshot(lookback=10)

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

    st.divider()
    st.header("第一階段設定")
    trust_days = st.slider("投信初買回看交易日", 3, 20, 10)
    hard_filter = st.checkbox("精選只顯示：營收雙成長＋EPS>0", value=False)
    trust_only = st.checkbox("精選只顯示：投信今日買超", value=False)

    if trust_days != 10:
        stage1 = stage1_snapshot(lookback=trust_days)

if hist.empty:
    st.warning("尚無歷史行情資料")
    st.stop()

s = snapshot(hist)
cand = yts_candidates(hist)
dates = sorted(hist.date.unique())

a, b, c, d = st.columns(4)
a.metric("交易日", len(dates))
b.metric("最新", str(dates[-1]))
c.metric("股票數", hist.stock_id.nunique())
d.metric("可算60MA", int((s.days >= 60).sum()))

tabs = st.tabs([
    "🔥 初篩候選",
    "🎯 精選＋第一階段",
    "🧩 第一階段資料",
    "⭐ 我的追蹤",
    "📊 多日診斷",
])

def enrich_stage1(df):
    if df.empty:
        return df
    if stage1 is None or stage1.empty:
        x = df.copy()
        for c in [
            "trust_net","trust_first_buy","trust_streak","trust_status",
            "revenue_month_yoy","revenue_cum_yoy","revenue_double_growth",
            "eps_cumulative","eps_positive","stage1_score"
        ]:
            x[c] = pd.NA
        return x

    cols = [
        "market","stock_id","trust_net","trust_first_buy","trust_streak","trust_status",
        "revenue_period","revenue_month_yoy","revenue_cum_yoy","revenue_double_growth",
        "eps_year","eps_quarter","eps_cumulative","eps_positive","stage1_score"
    ]
    cols = [c for c in cols if c in stage1.columns]

    x = df.merge(stage1[cols], on=["market","stock_id"], how="left")
    return x

with tabs[0]:
    st.subheader("🔥 技術面初篩")
    st.caption("Close > 20MA；當日量 ≥ 前20日平均量1.5倍（不含當日）。")
    if cand.empty:
        st.info("目前無候選。")
    else:
        e = enrich_stage1(cand)
        show_cols = [
            "stock_id","name","close","ma20","ma60","vol_ratio20","yts_score",
            "trust_status","revenue_double_growth","eps_positive","stage1_score","stage"
        ]
        show_cols = [c for c in show_cols if c in e.columns]
        st.dataframe(e[show_cols], use_container_width=True, hide_index=True)

with tabs[1]:
    st.subheader("🎯 精選＋第一階段")
    st.caption("第一階段先作『確認與排序』，預設不硬淘汰；可在側邊欄開啟硬條件。")

    refined = pd.DataFrame()
    if not cand.empty:
        refined = cand.copy()
        refined["距MA20%"] = (refined["close"] / refined["ma20"] - 1) * 100
        refined["收腳%"] = refined["foot_ratio"] * 100
        refined = refined[
            refined["ma60"].notna()
            & (refined["ma20"] > refined["ma60"])
            & refined["vol_ratio20"].between(1.5, 4.0)
            & refined["距MA20%"].between(0, 8)
            & (refined["收腳%"] >= 50)
            & (~refined["stage"].str.contains("第一根不追", na=False))
        ].copy()

        refined = enrich_stage1(refined)
        refined["stage1_score"] = pd.to_numeric(refined["stage1_score"], errors="coerce").fillna(0)
        refined["總排序分"] = (refined["yts_score"] + refined["stage1_score"]).clip(upper=100)

        if hard_filter:
            refined = refined[
                (refined["revenue_double_growth"] == True)
                & (refined["eps_positive"] == True)
            ]

        if trust_only:
            refined = refined[pd.to_numeric(refined["trust_net"], errors="coerce") > 0]

        refined = refined.sort_values(
            ["總排序分","stage1_score","yts_score","vol_ratio20"],
            ascending=False
        ).head(20)

    if refined.empty:
        st.info("目前沒有符合本次精選條件的標的。")
    else:
        show_cols = [
            "stock_id","name","close","ma20","ma60","vol_ratio20","foot_ratio",
            "trust_status","trust_net",
            "revenue_month_yoy","revenue_cum_yoy","revenue_double_growth",
            "eps_cumulative","eps_positive",
            "yts_score","stage1_score","總排序分","stage"
        ]
        show_cols = [c for c in show_cols if c in refined.columns]
        st.dataframe(refined[show_cols], use_container_width=True, hide_index=True)

        st.info(
            "營收『雙成長』目前定義為：最新月營收 YoY > 0 且累計營收 YoY > 0。"
            "這不是『連續3個月成長』；等我們累積月資料後再測更嚴格版本。"
        )

with tabs[2]:
    st.subheader("🧩 第一階段資料品質")

    if stage1 is None or stage1.empty:
        st.warning("尚未建立第一階段資料。請先執行 GitHub Actions：YTS Bootstrap Stage1。")
    else:
        st.write("**投信初買定義：** 今日買超 > 0，而且前 N 個已有資料的交易日皆 <= 0。歷史不足時顯示『資料不足』。")
        show_cols = [
            "market","stock_id","trust_date","trust_net","trust_first_buy",
            "trust_streak","trust_history_count","trust_status",
            "revenue_period","revenue_month_yoy","revenue_cum_yoy",
            "revenue_double_growth","eps_year","eps_quarter",
            "eps_cumulative","eps_positive","stage1_score"
        ]
        show_cols = [c for c in show_cols if c in stage1.columns]
        st.dataframe(stage1[show_cols], use_container_width=True, hide_index=True)

with tabs[3]:
    st.subheader("⭐ 我的追蹤")
    w = load_watchlist()
    if w.empty:
        st.info("追蹤名單目前是空的。")
    else:
        latest = s.copy()
        latest["stock_id"] = latest["stock_id"].astype(str)
        w["stock_id"] = w["stock_id"].astype(str)

        track = w.merge(latest, on=["market","stock_id"], how="left", suffixes=("_watch",""))
        track = enrich_stage1(track)

        for i, r in track.iterrows():
            name = _txt(r.get("name","")) or _txt(r.get("name_watch",""))
            sid = _txt(r.get("stock_id",""))
            market = _txt(r.get("market",""))

            with st.container(border=True):
                st.markdown(f"### {sid} {name}")

                if pd.notna(r.get("close")):
                    c1,c2,c3,c4 = st.columns(4)
                    c1.metric("收盤", f"{r['close']:.2f}")
                    c2.metric("20MA", f"{r['ma20']:.2f}" if pd.notna(r.get("ma20")) else "-")
                    c3.metric("投信", _txt(r.get("trust_status","")) or "-")
                    c4.metric("EPS", f"{r['eps_cumulative']:.2f}" if pd.notna(r.get("eps_cumulative")) else "-")

                    rev_ok = "✅" if r.get("revenue_double_growth") is True else "—"
                    eps_ok = "✅" if r.get("eps_positive") is True else "—"
                    st.write(f"營收雙成長：{rev_ok}　｜　EPS>0：{eps_ok}")

                support = st.text_input("自訂支撐", value=_txt(r.get("support","")), key=f"s_{market}_{sid}_{i}")
                resistance = st.text_input("自訂壓力", value=_txt(r.get("resistance","")), key=f"r_{market}_{sid}_{i}")
                note = st.text_area("備註", value=_txt(r.get("note","")), key=f"n_{market}_{sid}_{i}", height=70)

                x,y = st.columns(2)
                if x.button("💾 儲存備註", key=f"sv_{market}_{sid}_{i}", use_container_width=True):
                    ww = load_watchlist()
                    hit = (ww["market"] == market) & (ww["stock_id"] == sid)
                    ww.loc[hit,"support"] = support
                    ww.loc[hit,"resistance"] = resistance
                    ww.loc[hit,"note"] = note
                    save_watchlist(ww)
                    st.success("已儲存")
                if y.button("🗑️ 移除追蹤", key=f"rm_{market}_{sid}_{i}", use_container_width=True):
                    remove_watch(market,sid)
                    st.rerun()

with tabs[4]:
    st.subheader("📊 多日診斷")
    st.dataframe(s, use_container_width=True, hide_index=True)
