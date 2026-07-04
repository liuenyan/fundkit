# AGENTS.md — fundkit

Single-file Python CLI for DCA (定投) backtesting of Chinese open-end funds.

## Run

```bash
./venv/bin/python -m backend.dca_backtest --fund 161725 --amount 1000 --start 2018-01-01
# or Streamlit UI
./venv/bin/python -m streamlit run app.py
```

System Python won't work (missing deps). Always use `venv/bin/python`.

## Key facts

- **Data source**: [AKShare](https://github.com/akfamily/akshare) → 天天基金网, **requires internet**
- **Tests**: pytest, run via `./venv/bin/python -m pytest tests/`
- **Rename rule**: 同名文件重命名必须用 `git mv`，否则 git 不识别
- **Code style**: ruff (line-length=120, target-version=py311), managed via `requirements-dev.txt`
- **Chart output**: `./charts/<fund_code>_dca_backtest.png` (Auto, `matplotlib.use("Agg")`)
- **CJK fonts**: `tools/cjk_font.py` — `setup_cjk_font()` via `mpl.font_manager.findfont`
- **Backtest core**: `simulate_dca()` at line ~220, returns `(detail_df, events_list, redeem_fee, final_val)`
- **Redeem fee**: `calc_redeem_fee(fee_batches, date, nav, redeem_schedule)` — 计算全部申购批次赎回费
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
├─ fetch_fund_data()       # fund_nav_history cache-first → em_fetcher
│  └─ BacktestError        # raised on failures, CLI sys.exit(1) / GUI st.error+st.stop
├─ fetch_fund_name()       # AKShare fund name lookup
├─ generate_dca_dates()    # calendar → nearest trading day
├─ simulate_dca()          # core backtest loop (uses strategy objects)
│  ├─ FixedBuyStrategy           # 定期定额买入 (backend/strategy.py)
│  ├─ ValueAveragingBuyStrategy  # 价值平均买入 (backend/strategy.py)
│  ├─ TargetProfitSellStrategy   # 目标止盈卖出 (backend/strategy.py)
│  └─ TrailingStopSellStrategy   # 移动回撤卖出 (backend/strategy.py)
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
# 买入策略: 定期定额（默认）
--amount 1000

# 买入策略: 价值平均 (取代 --amount)
--value-avg 1000 --va-max-multiple 4 --va-min-amount 10

# 策略A: 目标止盈
--take-profit 0.20 --tp-cycle

# 策略B: 停投持有+移动止盈
--stop-invest 0.20 --trailing-stop 0.08

# 均线策略（基金净值）
--ma-period 250
# 均线策略（跟踪指数收盘价，无需缓冲期）
--ma-period 60 --index-ma
```

## Progress / TODO

### Completed
- `#1+#2`: `fund_nav_history` 缓存表 + `BacktestError` 异常，`fetch_fund_data()` 缓存优先，`app_pages/dca.py` 删除 `safe_call` 包装器
- `fund_fee` → `fund_scale` / `fund_profile` 分表剥离，迁移 + 回填完成
- `collect_fees.py` → `collect_fund_data.py` 改名，扩展采集 份额规模 + 档案信息
- `fund_data.py`: `fetch_mgmt_cust_fees` 返回扩展，`enrich_fee_scale` 新增份额规模兜底
- 298 只基金确认无公开规模数据（含 13 Y 份额），UI 显示 "—"
- `fetch_one_fee` → `fetch_one_overview` 重命名
- `fund_profile` 新增 `跟踪方式` 列，`collect_tracking_method()` 通过 `fund_info_index_em`（分开调被动/增强两组 API）写入 4295 只指数基金跟踪方式，名称启发式（`增强`/`量化`/`指增`）兜底补全剩余 2157 只，共 6452 只零遗漏
- `index_fund.py` 从 `fund_profile` 读取 `跟踪方式` 替代 AKShare 硬编码值，兜底名称启发式
- `fund_nav` 表建成：`基金代码/日期/单位净值/累计净值/日增长率/数据来源/updated_at`，双源采集（`fund_open_fund_daily_em` 23,529 只 + `fund_etf_fund_daily_em` 1,549 只），覆盖 6,349 / 6,490 指数基金 (97.8%)
- `fetch_all_index_funds()` 重构为本地 SQL JOIN 优先：`fund_nav` 缓存有效时零 API 调用，JOIN `fund_catalog` + `fund_profile` + `fund_fee` + `fund_scale` 四表。支持 `collect_fund_data.py --nav` 独立刷新净值缓存
- `tools/build_index_name_map.py`: `index_name_map` 表构建器，映射率从 103/367 (22%) 提升至 491/35 (93%)
  - 匹配优先级：`KNOWN_MAP`(12) → CSI 官网（中证指数导出）→ 国证官网（cnindex.com.cn xlsx），含归一化 fallback（解决"中证180 ESG指数" vs "中证180ESG" 等空格/后缀不一致）
  - `normalize()` 自动剥离 `人民币`/`港元`/`美元`/`港币` 货币后缀；兼容全角+半角混合括号
  - KNOWN_MAP 12 条：7 条国内 + 5 条海外 P0（恒生指数/恒生中国企业/恒生科技/纳斯达克100/道琼斯工业平均），source 支持 `sina_hk`/`sina_us` 路由
  - 运行时 API 失败回退 `acc_nav`
  - 聚宽（index_stock_info）已移除：0% 唯一贡献
  - 验证支持 `_verify_sina_hk()` / `_verify_sina_us()` 对 Sina 源的正确性检查
- `tools/gen_name_map_report.py`: 从 DB 重新生成 `docs/index_name_map_report.md`（`PYTHONPATH=. ./venv/bin/python tools/gen_name_map_report.py`）
- `tools/csi_export.py`: 中证指数官网导出接口 (`POST csindex-home/exportExcel/indexAll/CH`)，返回 2,967 条指数（1,847 条股票类）。`get_equity_name_map()` 基于 指数简称 + 指数全称去"指数"后缀构建 5,471 条名称映射。本地 CSV 缓存 `data/csi_index_list.csv`，支持 `--force` 刷新
- `tools/cnindex_export.py`: 国证指数官网 xlsx 导出 (`cnindex.com.cn`)，返回 1,384 条指数（1,212 条股票类），补深证/国证系列。本地 CSV 缓存 `data/cnindex_index_list.csv`
- `tools/gen_name_map_report.py`: 从 DB 重新生成 `docs/index_name_map_report.md`（`PYTHONPATH=. ./venv/bin/python tools/gen_name_map_report.py`）
- `docs/overseas_index_mapping.md`: 海外指数映射方案文档，定义三层映射策略：P0(Sina价格源) / P1(代码映射+acc_nav回退) / P2(不处理)。已落地 5 条 P0（恒生×3 + 美股×2），mapping 从 486→491
- **`index_series` + `cache_meta` 列改名**：`name` → `index_code`，统一用裸代码（`000300` / `HSI` / `.NDX`）作主键，解决中文名碰撞问题。已有 ~74K 行迁移完成
- **`backend/index_fetcher.py`**：统一取价入口，`lookup_index()` 解析跟踪标→index_code+source，`fetch_index_price()` 按 source 路由到 csindex/sina_hk/sina_us API，缓存复用 `index_series.metric="price"`
- **`index_valuation.py` 适配**：CONFIG 新增 `code` 字段，`_get_series()` 用 `index_code` 作缓存 key（pe/pb/price 统一）
- **CLI `--index-ma`**：MA 策略支持 `--ma-period 60 --index-ma` 使用跟踪指数收盘价计算均线，无需额外缓冲期。已实测 000071（恒生指数）端到端工作

## Quirks

- `generate_dca_dates()` walks forward up to 10 trading days from the candidate date. If no match in 10 days, the date is skipped silently.
- The simulated return rate (`round_return`) can exceed the `--take-profit` / `--stop-invest` target if NAV gaps significantly between trading days (especially for volatile commodity/oil funds like 110026). This is mathematically correct — DCA buys more shares at low prices, amplifying returns on recovery.
- For monthly frequency: `day` is clamped to 28 (funds always have NAV on those days or before). For Chinese funds, day 28+ is safer than day 30/31.

## Compare tool

```bash
# 手动指定场景
./venv/bin/python -m tools.compare_strategies \
  --funds 110026,110020,160119 \
  --scenarios "熊市底部:2019-01-10,市场平均:2020-04-10,牛市顶部:2021-07-09" \
  --output docs/strategy_comparison.md

# 自动识别场景（基于净值历史找最高/最低/中位数）
./venv/bin/python -m tools.find_scenarios --fund 110026 \
  --scenarios "牛市顶部:2021,熊市底部:2018-2019,市场平均:2020"
# 输出: 牛市顶部:2021-08-04,熊市底部:2018-10-18,市场平均:2020-09-28

# 组合使用：自动场景 + 对比
./venv/bin/python -m tools.compare_strategies \
  --funds 110026 \
  --auto-scenarios 110026 \
  --scenarios-spec "牛市顶部:2021,熊市底部:2018-2019,市场平均:2020"
```

## Git rules

- 每次编写完新代码后，不提交到 git 仓库，待用户发出指令再提交。
