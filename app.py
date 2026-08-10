
import streamlit as st, pandas as pd
from yts_engine import *

st.set_page_config(page_title="YTS v0.4",layout="wide")
ensure_dirs()
st.title("YTS 台股多頭突破回測掃描器 v0.4")
st.caption("新增：多重支撐自動計數、支撐群聚中心、個股容許距離、壓力/支撐模板")

with st.sidebar:
    if st.button("抓取今日官方收盤",use_container_width=True):
        st.json(collect_today())
    st.divider()
    st.subheader("TWSE 歷史初始化")
    ids=st.text_area("上市代號",value="3048,2368,8110,2464")
    months=st.slider("月份",3,12,6)
    if st.button("補齊上市歷史"):
        st.dataframe(pd.DataFrame(bootstrap_twse(ids.split(","),months)),hide_index=True)
    st.divider()
    st.subheader("匯入官方歷史CSV")
    up=st.file_uploader("TWSE/TPEx 官方下載CSV",type=["csv"])
    market=st.selectbox("市場",["TPEX","TWSE"])
    sid=st.text_input("CSV股票代號")
    nm=st.text_input("CSV名稱")
    if st.button("匯入CSV") and up:
        try:
            n=import_official_history_csv(up.getvalue(),market,sid,nm)
            st.success(f"匯入 {n} 筆")
        except Exception as e: st.error(str(e))

hist=load_history()
if hist.empty:
    st.info("先抓今日資料或匯入歷史。"); st.stop()

tabs=st.tabs(["突破候選","回測追蹤&評分","加入觀察","快照","回饋","規則"])

with tabs[0]:
    c=objective_breakout_candidates(hist)
    st.dataframe(c,use_container_width=True,hide_index=True)
    st.caption("這裡只是客觀帶量候選，不代表已突破頸線。")

with tabs[1]:
    r=evaluate_watchlist(hist)
    if r.empty: st.info("尚無觀察股")
    else:
        cols=["stock_id","name","date","close","support","manual_support2","manual_support3",
              "ma20","ma60","support_cluster_count","support_cluster_labels","support_cluster_center",
              "multiple_support","pressure","pressure_distance_pct","retest_vs_breakout_volume",
              "foot_ratio","chip_score","retest_state","yts_score","note"]
        view=r[[x for x in cols if x in r.columns]].sort_values("yts_score",ascending=False)
        st.dataframe(view,use_container_width=True,hide_index=True)
        st.caption("多重支撐只做『價格群聚』計數；技術意義仍由你人工確認。")

with tabs[2]:
    st.subheader("加入 / 更新觀察股")
    a,b,c=st.columns(3)
    sid=a.text_input("代號",key="w_sid"); name=b.text_input("名稱",key="w_name"); bd=c.text_input("突破日",key="w_bd")
    d,e,f=st.columns(3)
    neck=d.number_input("頸線",min_value=0.0,value=0.0)
    sup=e.number_input("主要支撐1",min_value=0.0,value=0.0)
    press=f.number_input("第一壓力",min_value=0.0,value=0.0)
    g,h,i=st.columns(3)
    sup2=g.number_input("人工支撐2",min_value=0.0,value=0.0)
    sup3=h.number_input("人工支撐3",min_value=0.0,value=0.0)
    tol=i.slider("支撐群聚容許距離 %",0.5,3.0,1.5,0.1)
    j,k=st.columns(2)
    bv=j.number_input("突破日成交量",min_value=0.0,value=0.0)
    chip=k.slider("籌碼加分",0,10,0)
    note=st.text_area("備註")
    if st.button("加入/更新觀察"):
        upsert_watchlist(sid,name,bd,neck or float("nan"),sup or float("nan"),
                         press or float("nan"),bv or float("nan"),chip,note,
                         sup2 or float("nan"),sup3 or float("nan"),tol)
        st.success("已更新")

with tabs[3]:
    st.dataframe(latest_snapshot(hist),use_container_width=True,hide_index=True)

with tabs[4]:
    sid=st.text_input("回饋代號")
    result=st.selectbox("判定",["符合","接近符合","不符合","持續觀察"])
    reason=st.text_area("原因")
    if st.button("儲存"):
        save_manual_feedback(sid,result,reason); st.success("已儲存")

with tabs[5]:
    st.markdown("""
### YTS v0.4 新增規則
- 多重支撐來源：**頸線、人工支撐1/2/3、20MA、60MA**
- 支撐群聚：今日低點/當日區間碰到這些支撐，且距離在個股設定的容許範圍內
- 2個支撐：YTS +8
- 3個支撐：YTS +12
- 4個以上：YTS +15
- 群聚中心只是一個數學平均位置，不代表真正買點

### 原有規則保留
- 收盤 > 20MA：+20
- 20MA > 60MA：+10
- 回測到支撐：+15
- 嚴格收腳 ≥ 2/3：+20
- 一般收腳 ≥ 1/2：+12
- 回測量 / 突破量 ≤40%：+15；≤60%：+10；≤80%：+5
- 第一壓力距離 ≥8%：+10；≥5%：+6；<3%：-8
- 籌碼人工 +0~10

**YTS Score 仍只是排序分數，不等於勝率，也不是自動買進建議。**
""")
