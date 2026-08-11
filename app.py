
import streamlit as st
import pandas as pd
from pathlib import Path
from yts_engine import *
from yts_engine import load_history
from stage1_data import stage1_snapshot, load_fundamentals, trust_snapshot

st.set_page_config(
    page_title="YTS v1.1 穩定排序版",
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

st.title("YTS 台股多頭突破回測掃描器 v1.1｜穩定排序版")
st.caption("技術面＋投信＋營收確認｜EPS／籌碼／大戶暫由人工判斷")

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
    priority_only = st.checkbox("只顯示 🔥 優先看", value=False)
    trust_only = st.checkbox("只顯示：投信今日買超", value=False)

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
    "🎯 精選候選",
    "⭐ 優先看",
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
            "stage1_score"
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

def build_refined(cand_df):
    if cand_df.empty:
        return pd.DataFrame()

    refined = cand_df.copy()
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

    if refined.empty:
        return refined

    refined = enrich_stage1(refined)
    refined["stage1_score"] = pd.to_numeric(
        refined.get("stage1_score"), errors="coerce"
    ).fillna(0)

    # 目前只讓「投信 + 營收」參與 Stage1 加分；EPS 暫停。
    refined["總排序分"] = (
        pd.to_numeric(refined["yts_score"], errors="coerce").fillna(0)
        + refined["stage1_score"]
    ).clip(upper=100)

    # 人工複核導向的透明分級，不因資料缺漏刪股票。
    trust_net = pd.to_numeric(refined.get("trust_net"), errors="coerce")
    trust_first = refined.get("trust_first_buy", pd.Series(False, index=refined.index)).fillna(False)
    rev_ok = refined.get("revenue_double_growth", pd.Series(False, index=refined.index)).fillna(False)

    refined["第一階段確認數"] = (
        (trust_net > 0).fillna(False).astype(int)
        + trust_first.astype(int)
        + rev_ok.astype(int)
    )

    # 技術位置越靠近 MA20、收腳越完整，優先度越高。
    tech_good = (
        refined["距MA20%"].between(0, 5)
        & refined["vol_ratio20"].between(1.5, 3.5)
        & (refined["收腳%"] >= 55)
    )

    refined["優先級"] = "🟡 一般候選"
    refined.loc[tech_good, "優先級"] = "⭐ 觀察"
    refined.loc[
        tech_good & (refined["第一階段確認數"] >= 1),
        "優先級"
    ] = "🔥 優先看"

    order = pd.Categorical(
        refined["優先級"],
        categories=["🔥 優先看", "⭐ 觀察", "🟡 一般候選"],
        ordered=True
    )
    refined["_priority_order"] = order
    refined = refined.sort_values(
        ["_priority_order", "總排序分", "stage1_score", "yts_score", "vol_ratio20"],
        ascending=[True, False, False, False, False]
    )
    return refined


with tabs[1]:
    st.subheader("🎯 精選候選")
    st.caption(
        "先用技術面縮小範圍，再用投信與營收作確認。"
        "EPS、主力、大戶、家數差目前不自動淘汰，留給人工複核。"
    )

    refined = build_refined(cand)

    if trust_only and not refined.empty:
        refined = refined[
            pd.to_numeric(refined["trust_net"], errors="coerce") > 0
        ]

    if priority_only and not refined.empty:
        refined = refined[refined["優先級"] == "🔥 優先看"]

    if refined.empty:
        st.info("目前沒有符合精選條件的標的。")
    else:
        show_cols = [
            "優先級","stock_id","name","close","ma20","ma60",
            "距MA20%","vol_ratio20","收腳%",
            "trust_status","trust_net",
            "revenue_month_yoy","revenue_cum_yoy","revenue_double_growth",
            "第一階段確認數","yts_score","stage1_score","總排序分","stage"
        ]
        show_cols = [c for c in show_cols if c in refined.columns]
        st.dataframe(
            refined[show_cols].head(30),
            use_container_width=True,
            hide_index=True
        )

        c1, c2, c3 = st.columns(3)
        c1.metric("🔥 優先看", int((refined["優先級"] == "🔥 優先看").sum()))
        c2.metric("⭐ 觀察", int((refined["優先級"] == "⭐ 觀察").sum()))
        c3.metric("🟡 一般", int((refined["優先級"] == "🟡 一般候選").sum()))

        st.info(
            "目前營收『雙成長』＝最新月營收 YoY > 0 且累計營收 YoY > 0。"
            "EPS、主力買賣超、大戶散戶比、家數差與隔日沖券商，暫由人工判斷。"
        )

with tabs[2]:
    st.subheader("⭐ 優先看")
    refined = build_refined(cand)
    priority = refined[refined["優先級"] == "🔥 優先看"].copy() if not refined.empty else pd.DataFrame()

    if priority.empty:
        st.info("今天沒有 🔥 優先看；可到『🎯 精選候選』查看 ⭐ 觀察。")
    else:
        st.caption("這裡只保留技術面位置較佳，且至少有一項投信／營收確認的候選。")
        show_cols = [
            "stock_id","name","close","距MA20%","vol_ratio20","收腳%",
            "trust_status","trust_net",
            "revenue_month_yoy","revenue_cum_yoy","revenue_double_growth",
            "yts_score","stage1_score","總排序分","stage"
        ]
        show_cols = [c for c in show_cols if c in priority.columns]
        st.dataframe(
            priority[show_cols].head(15),
            use_container_width=True,
            hide_index=True
        )
        st.warning(
            "🔥 優先看只是盤後排序，不代表買進訊號。"
            "下單前仍人工確認 EPS、主力／大戶籌碼、家數差、隔日沖分點與上方壓力。"
        )

with tabs[5]:
    st.subheader("🧩 第一階段資料品質")

    if stage1 is None or stage1.empty:
        st.warning("尚未建立第一階段資料。請先執行 GitHub Actions：YTS Bootstrap Stage1。")
    else:
        st.write("**投信初買定義：** 今日買超 > 0，而且前 N 個已有資料的交易日皆 <= 0。歷史不足時顯示『資料不足』。")
        show_cols = [
            "market","stock_id","trust_date","trust_net","trust_first_buy",
            "trust_streak","trust_history_count","trust_status",
            "revenue_period","revenue_month_yoy","revenue_cum_yoy",
            "revenue_double_growth","stage1_score"
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
                    c4.metric("Stage1", f"{r['stage1_score']:.0f}" if pd.notna(r.get("stage1_score")) else "0")

                    rev_ok = "✅" if r.get("revenue_double_growth") is True else "—"
                    st.write(f"營收雙成長：{rev_ok}　｜　EPS／籌碼：人工判斷")

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
