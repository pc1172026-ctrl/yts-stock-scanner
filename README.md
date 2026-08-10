# YTS v0.4

新增：
- 多重支撐自動計數
- 支撐來源：頸線、人工支撐1/2/3、20MA、60MA
- 每檔股票可設定支撐群聚容許距離（預設 ±1.5%）
- 顯示支撐群聚中心與來源
- YTS Score 加入多重支撐分數

設計原則：程式只判斷「價格是否接近」，不自行認定某條支撐具有技術意義。

執行：
```bash
pip install -r requirements.txt
streamlit run app.py
```
