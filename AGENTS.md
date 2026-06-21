# AGENTS.md — fundkit

Single-file Python CLI for DCA (定投) backtesting of Chinese open-end funds.

## Run

```bash
./venv/bin/python dca_backtest.py --fund 161725 --amount 1000 --start 2018-01-01
# or Streamlit UI
./venv/bin/python -m streamlit run app.py
```

System Python won't work (missing deps). Always use `venv/bin/python`.

## Key facts

- **Data source**: [AKShare](https://github.com/akfamily/akshare) → 天天基金网, **requires internet**
- **No tests**: no test framework, no CI, no lint/typecheck config
- **Rename rule**: 同名文件重命名必须用 `git mv`，否则 git 不识别
- **Code style**: ruff (line-length=120, target-version=py311), managed via `requirements-dev.txt`
- **Chart output**: `./charts/<fund_code>_dca_backtest.png` (Auto, `matplotlib.use("Agg")`)
- **CJK fonts**: `cjk_font.py` — `setup_cjk_font()` via `mpl.font_manager.findfont`
- **Backtest core**: `simulate_dca()` at line 184, returns `(detail_df, events_list, redeem_fee, final_val)`
- **Two stop-profit strategies**:
  - **A**: `--take-profit` + `--tp-cycle` (目标止盈，达阈值即卖出)
  - **B**: `--stop-invest` + `--trailing-stop` (停投持有+移动止盈，回撤卖出后自动循环)

## Streamlit UI (`app.py` + `app_pages/`)

- `app.py` → 导航中枢 (`st.navigation`)，四个页面：
  - `app_pages/dca.py` → 定投回测 (`/dca`)
  - `app_pages/index_valuation.py` → 指数估值 (`/valuation`)
  - `app_pages/index_fund.py` → 指数选基 (`/index_fund`)
  - `app_pages/pension_fund.py` → 养老金选基 (`/pension`)

## Architecture

```
main()
├─ fetch_fund_data()       # AKShare → unit_nav + acc_nav
├─ fetch_fund_name()       # AKShare fund name lookup
├─ generate_dca_dates()    # calendar → nearest trading day
├─ simulate_dca()          # core backtest loop
├─ calc_lumpsum()          # lump-sum comparison
└─ plot_results()          # matplotlib (2-panel chart)
```

## Streamlit UI — 养老金选基 (`app_pages/pension_fund.py`)
- 筛选 Y 份额基金（个人养老金账户可投资）
- 分类：指数基金 / FOF-目标日期 / FOF-目标风险（稳健/均衡/积极）
- 数据源：`fund_name_em` → Y份额筛选 + `fund_open_fund_daily_em`（净值/费率）+ 雪球（管理费/托管费）
- 排序规则同指数选基页，管理费/托管费通过 `index_fund.fetch_fund_fees` 懒加载（`@st.cache_data` 会话内缓存）

## Streamlit UI — 指数估值 (`app_pages/index_valuation.py`)
- 百分位曲线 (PE/PB, 5年/10年滚动, 原始值叠加)
- 指数点位 & PE 叠加图
- **中证红利股息率 vs 十年期国债收益率**: 折叠面板，双轴对比图
  - 国债数据: `bond_zh_us_rate()` → 6109行 (2002~)
  - 股息率数据: 用 `stock_zh_index_value_csindex("000922")` 快照校准 payout ratio，结合 csindex PE 历史估算 → ~3572行 (2011~)

## Common args

```
--fund 6位代码  --amount 每期金额  --start YYYY-MM-DD
--freq daily|weekly|biweekly|monthly  --day 1-28  --weekday 1-5
--fee 0.0015  --output path.csv  --chart ./charts
# 策略A: 目标止盈
--take-profit 0.20 --tp-cycle

# 策略B: 停投持有+移动止盈
--stop-invest 0.20 --trailing-stop 0.08
```

## Progress / TODO

### Completed
- `fund_fee` → `fund_scale` / `fund_profile` 分表剥离，迁移 + 回填完成
- `collect_fees.py` → `collect_fund_data.py` 改名，扩展采集 份额规模 + 档案信息
- `fund_data.py`: `fetch_mgmt_cust_fees` 返回扩展，`enrich_fee_scale` 新增份额规模兜底
- 298 只基金确认无公开规模数据（含 13 Y 份额），UI 显示 "—"
- `fetch_one_fee` → `fetch_one_overview` 重命名
- `fund_profile` 新增 `跟踪方式` 列，`collect_tracking_method()` 通过 `fund_info_index_em`（分开调被动/增强两组 API）写入 4295 只指数基金跟踪方式，名称启发式（`增强`/`量化`/`指增`）兜底补全剩余 2157 只，共 6452 只零遗漏
- `index_fund.py` 从 `fund_profile` 读取 `跟踪方式` 替代 AKShare 硬编码值，兜底名称启发式
- `fund_nav` 表建成：`基金代码/日期/单位净值/累计净值/日增长率/数据来源/updated_at`，双源采集（`fund_open_fund_daily_em` 23,529 只 + `fund_etf_fund_daily_em` 1,549 只），覆盖 6,349 / 6,490 指数基金 (97.8%)
- `fetch_all_index_funds()` 重构为本地 SQL JOIN 优先：`fund_nav` 缓存有效时零 API 调用，JOIN `fund_catalog` + `fund_profile` + `fund_fee` + `fund_scale` 四表。支持 `collect_fund_data.py --nav` 独立刷新净值缓存

## Quirks

- `generate_dca_dates()` walks forward up to 10 trading days from the candidate date. If no match in 10 days, the date is skipped silently.
- The simulated return rate (`round_return`) can exceed the `--take-profit` / `--stop-invest` target if NAV gaps significantly between trading days (especially for volatile commodity/oil funds like 110026). This is mathematically correct — DCA buys more shares at low prices, amplifying returns on recovery.
- For monthly frequency: `day` is clamped to 28 (funds always have NAV on those days or before). For Chinese funds, day 28+ is safer than day 30/31.
