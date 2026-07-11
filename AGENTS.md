# AGENTS.md — fundkit

单文件 Python 工具集：定投回测、指数估值、指数选基、养老金筛选。

## Run

```bash
uv run backtest --fund 161725 --amount 1000 --start 2018-01-01
uv run streamlit run app.py
uv run collect --nav
uv run find-scenarios --fund 110026 --scenarios "熊市底部:2018-2019,市场平均:2020,牛市顶部:2021"
uv run compare-strategies --funds 110026,110020 --scenarios "..."
```

Always use `uv run` (auto `.venv`). Dev deps: `uv sync --extra dev`.

## Architecture

```
main()                          # backend/dca_backtest.py
├─ fetch_fund_data()            # fund_nav_history cache → AKShare fallback
├─ generate_dca_dates()         # calendar → nearest trading day
├─ simulate_dca()               # core loop with strategy objects
│  ├─ FixedBuyStrategy          #   定期定额 (backend/strategy.py)
│  ├─ ValueAveragingBuyStrategy #   价值平均
│  ├─ TargetProfitSellStrategy  #   目标止盈 (策略A)
│  └─ TrailingStopSellStrategy  #   移动止盈 (策略B)
├─ calc_lumpsum()               # 一次性投入对照
└─ plot_results()               # matplotlib 2-panel chart
```

**Data flow**: collect_fund_data.py → SQLite (data/fundkit.db) → Streamlit pages / CLI backtest. All UI reads via `db.py` local JOINs, zero AKShare at runtime.

**Index price** (--index-ma): `backend/index_fetcher.py` — `lookup_index()` routes to csindex/sina_hk/sina_us, caches via `index_series`.

## CLI reference

```
--fund 6位代码  --amount 每期金额  --start YYYY-MM-DD
--freq daily|weekly|biweekly|monthly  --day 1-28  --weekday 1-5
--fee 0.0015  --output path.csv  --chart ./charts
# 买入: 定期定额(默认) | 价值平均(--value-avg N --va-max-multiple 4 --va-min-amount 10)
# 策略A: --take-profit 0.20 --tp-cycle
# 策略B: --stop-invest 0.20 --trailing-stop 0.08
# 均线: --ma-period 250 | --ma-period 60 --index-ma (跟踪指数收盘价)
```

## Streamlit pages (`app.py` + `app_pages/`)

| Route | File | Key logic |
|-------|------|-----------|
| `/dca` | `dca.py` | 定投回测 (同 CLI 参数) |
| `/valuation` | `index_valuation.py` | PE/PB 百分位曲线, 中证红利股息率 vs 国债 |
| `/index_fund` | `index_fund.py` | 指数选基 (费率/规模/跟踪方式排序) |
| `/pension` | `pension_fund.py` | Y 份额养老基金筛选 |
| `/fund_query` | `fund_query.py` | 基金查询 (费率/规模/跟踪方式) |

## Key facts

- **Data**: AKShare → 天天基金网, requires internet
- **Tests**: `uv run python -m pytest tests/`
- **Code style**: ruff (line-length=120, target-version=py311), pyright standard mode
- **Pre-commit**: ruff lint+format + pyright, auto-run on `git commit`
- **Chart output**: `./charts/<fund_code>_dca_backtest.png` (Agg backend)
- **CJK fonts**: `backend/cjk_font.py` — `setup_cjk_font()` auto-detects system CJK fonts
- **Redeem fee**: `calc_redeem_fee(fee_batches, date, nav, redeem_schedule)` — 计算全部申购批次赎回费
- **Git**: 代码默认不提交，需用户审查确认后再执行 `git commit`
- **提交信息**: 必须描述实际代码逻辑变更，不能只写 "ruff format" / "fix ruff" 等泛泛描述。提交前执行 `git diff --cached` 确认变更内容

## Caveats

- `generate_dca_dates()` skips date silently if no trading day found within 10 forward days
- `round_return` can exceed take-profit threshold if NAV gaps significantly between trading days (e.g. 110026). Mathematically correct.
- Monthly `--day` clamped to 28 (Chinese funds always have NAV on/before 28th)
- Git: rename same-name files with `git mv`, otherwise git won't track
