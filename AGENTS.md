# AGENTS.md — fund_dca_backtest

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
- **Chart output**: `./charts/<fund_code>_dca_backtest.png` (Auto, `matplotlib.use("Agg")`)
- **CJK fonts**: auto-detected via `_setup_cjk_font()` — falls back gracefully if missing
- **Backtest core**: `simulate_dca()` at line 184, returns `(detail_df, events_list, redeem_fee, final_val)`
- **Two stop-profit strategies**:
  - **A**: `--take-profit` + `--tp-cycle` (目标止盈，达阈值即卖出)
  - **B**: `--stop-invest` + `--trailing-stop` (停投持有+移动止盈，回撤卖出后自动循环)

## Streamlit UI (`app.py`)

- Wraps `dca_backtest.py` core functions with `safe_call()` to catch `sys.exit` → `st.error`
- Reuses `fetch_fund_data`, `simulate_dca`, `generate_dca_dates`, `calc_lumpsum` etc.
- Custom `make_charts()` returns matplotlib figure (does NOT save to file)
- Sidebar controls → `st.button("开始回测")` → all metrics/charts/tables in main panel

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

## Quirks

- `generate_dca_dates()` walks forward up to 10 trading days from the candidate date. If no match in 10 days, the date is skipped silently.
- The simulated return rate (`round_return`) can exceed the `--take-profit` / `--stop-invest` target if NAV gaps significantly between trading days (especially for volatile commodity/oil funds like 110026). This is mathematically correct — DCA buys more shares at low prices, amplifying returns on recovery.
- For monthly frequency: `day` is clamped to 28 (funds always have NAV on those days or before). For Chinese funds, day 28+ is safer than day 30/31.
