
from stage1_data import bootstrap_twse_trust, collect_today_institutional, collect_fundamentals

if __name__ == "__main__":
    print("Bootstrap TWSE trust history...")
    print(bootstrap_twse_trust(calendar_days=25))
    print("Collect current TWSE/TPEX trust...")
    print(collect_today_institutional()[1])
    print("Collect latest revenue / EPS...")
    print(collect_fundamentals()[1])
