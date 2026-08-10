
from pathlib import Path
import sys
from yts_engine import collect_today

def main():
    df, report, warnings_list = collect_today(save_local=True)
    print("YTS daily updater")
    print(report)
    for w in warnings_list:
        print("WARNING:", w)
    if df.empty:
        print("No market data fetched.")
        return 2
    print(f"Saved {len(df)} rows.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
