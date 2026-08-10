from yts_engine import fetch_today, merge_daily
if __name__=="__main__":
    df,report=fetch_today();print(report)
    if df.empty:raise SystemExit(2)
    merge_daily(df)
