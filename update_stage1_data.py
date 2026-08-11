
from stage1_data import collect_today_institutional, collect_fundamentals

if __name__ == "__main__":
    inst, inst_report = collect_today_institutional()
    fund, fund_report = collect_fundamentals()
    print("Institutional:", inst_report)
    print("Fundamentals:", fund_report)
    print("Institutional rows:", len(inst))
    print("Fundamental rows:", len(fund))
