
# YTS 台股多頭突破回測掃描器 v0.5

## v0.5 的核心改變

### 1. 歷史資料改由 GitHub 保存
`GitHub Actions -> data/daily/YYYY-MM-DD.csv -> commit -> Streamlit`

不再把 Streamlit Community Cloud 的本機磁碟當資料庫。

### 2. 手機一鍵掃描
打開 App 後只需按：
`🚀 執行今日掃描`

### 3. TWSE + TPEx
- TWSE：官方 OpenAPI `STOCK_DAY_ALL`
- TPEx：官方 OpenAPI `tpex_mainboard_daily_close_quotes`
- 若 Streamlit/GitHub runner 發生 TPEx CA chain 問題，只對公開唯讀行情 GET 使用 TLS fallback。

### 4. YTS 已固定客觀條件
- Close > 20MA
- 20MA > 60MA：加分
- 當日量 >= 前20個交易日均量 * 1.5
- 前20日均量不含當日
- 突破第一根不追
- 等第一次回測
- 收腳嚴格版 >= 2/3，一般版 >= 1/2

## 升級方式

將 v0.5 內的這些檔案上傳到你現有 GitHub repository 根目錄：

- `app.py`
- `yts_engine.py`
- `update_market_data.py`
- `requirements.txt`
- `config/watchlist.csv`

並新增：
- `.github/workflows/daily_market.yml`

保留：
- `data/daily/` 資料夾

GitHub Actions 第一次可手動執行：
Repository -> Actions -> YTS Daily Market Data -> Run workflow

之後每週一至週五台北時間 15:40 自動執行。
GitHub 排程可能因平台負載稍微延遲，所以這個工作流定位為盤後資料收集，不是即時交易訊號。

## 重要限制

若 repository 目前沒有過去歷史 CSV，v0.5 不會假裝已有完整 20MA/60MA。
它會隨每日 GitHub Actions 累積：
- 21 個交易日後：完整啟用 20MA + 前20日均量
- 60 個交易日後：完整啟用 60MA

這是為了避免使用來源不明的歷史資料。
