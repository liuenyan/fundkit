[![CI](https://github.com/liuenyan/fundkit/actions/workflows/ci.yml/badge.svg)](https://github.com/liuenyan/fundkit/actions/workflows/ci.yml)
![coverage](https://img.shields.io/badge/coverage-41%25-red)

# FundKit — 中国公募基金工具箱

一站式中国公募基金分析工具，覆盖**定投回测**、**基金查询**、**指数选基**、**养老金选基**、**指数估值**五大场景。数据源基于天天基金网、中证指数、乐咕乐股等公开平台（通过 [AKShare](https://github.com/akfamily/akshare) 获取），提供 Streamlit 图形界面与 CLI 双模式。

## 功能（按 Streamlit 页面顺序）

### 定投回测

对任意开放式基金进行历史定投（DCA）模拟，支持多频率、多策略、自定义费率，输出收益率、回撤、图表及 CSV 明细。

- 定投频率：每日 / 每周 / 每两周 / 每月，自动匹配交易日
- 申购费 & 阶梯赎回费：可配置
- 一次性投入对比：等额资金一次性买入 vs 定投
- 止盈策略 A：目标止盈（达阈值卖出，可选循环）
- 止盈策略 B：停投持有 + 移动止盈（达标停投，回撤卖出，可选循环）
- 图表输出：双面板 PNG（净值 + 成本 / 收益率 + 回撤）
- CSV 导出

### 基金查询

按基金代码或名称搜索基金，查看基本信息、净值、费率、规模等关键指标。

- 文本搜索：基金代码、名称拼音、关键词
- 信息展示：基金类型、基金经理、成立日期、管理/托管费率
- 一键跳转定投回测：点击即带基金代码参数跳转

### 指数选基

按指数名称搜索跟踪该指数的全部基金，对比规模、费率等指标，快速跳转定投回测。

- 搜索方式：文本搜索 + 热门指数下拉列表
- 综合费率展示：申购费（实际折扣后）+ 管理费 + 托管费
- 筛选：基金类型（ETF联接 / 指数增强 / 普通指数型）、份额类别（A / C / 其他）
- 排序：费率、规模、净值
- 一键跳转定投回测

### 养老金选基

筛选个人养老金账户可投资的 Y 份额基金，按类型（指数基金、FOF-目标日期、FOF-目标风险）分类展示，支持规模/费率排序。

- 数据源全 DB 查询，零 API 冷启动
- 自动加载 Y 份额净值、费率、规模
- 管理费/托管费懒加载缓存（会话级）

### 指数估值

追踪主流指数的 PE / PB 历史百分位，辅助判断估值高低。

- 指数覆盖：沪深300、中证500、中证红利、红利低波、CS消费50、创业板50
- 百分位曲线：5 年 / 10 年滚动百分位 + 原始值叠加
- 指数点位 & PE 叠加走势图
- 中证红利股息率 vs 十年期国债收益率：历史对比双轴图
- 低估 / 适中 / 高估 三档标签

## 架构

```
fundkit/
├── app.py                   # Streamlit 导航中枢（st.navigation，五个页面）
│
├── backend/                 # 业务逻辑层
│   ├── __init__.py
│   ├── dca_backtest.py      # 定投回测 CLI 主程序（cache-first，BacktestError 异常）
│   ├── em_fetcher.py        # 东方财富 pingzhongdata JS 直取（一次 HTTP + JS eval）
│   ├── strategy.py          # 买入/卖出策略对象（固定金额、价值平均、目标止盈、移动止盈）
│   ├── charting.py          # matplotlib 双面板图表绘制
│   ├── fund_query.py        # 基金查询逻辑
│   ├── index_fund.py        # 指数选基数据获取 + 搜索/筛选/排序
│   ├── pension_fund.py      # 养老金选基后端
│   ├── index_valuation.py   # 指数估值百分位计算后端
│   └── fund_data.py         # 基金数据共享层（费率解析、规模兜底等）
│
├── app_pages/               # Streamlit 页面（与 app.py 一一对应）
│   ├── dca.py               # 定投回测
│   ├── fund_query.py        # 基金查询
│   ├── index_fund.py        # 指数选基
│   ├── pension_fund.py      # 养老金选基
│   └── index_valuation.py   # 指数估值
│
├── tools/                   # 通用工具模块
│   ├── cjk_font.py          # 中文字体检测与设置（setup_cjk_font）
│   ├── stats.py             # 统计函数（max_drawdown / calc_annualized / calc_percentile）
│   └── formatters.py        # 格式化工具
│
├── collect_fund_data.py     # 数据预采集（费率/规模/档案/净值/名录/跟踪方式）
├── db.py                    # SQLAlchemy Core 数据库层（SQLite WAL，10 张表）
│
├── data/                    # SQLite 数据库目录（自动创建）
├── charts/                  # 图表输出目录（自动创建）
│
├── docs/
│   ├── dca_backtest_cli.md  # 命令行定投回测完整手册
│   ├── collect_fund_data.md # 数据采集工具文档
│   ├── data_source.md       # 数据源调研与选型说明
│   └── database.md          # 数据库表设计文档
│
├── pyproject.toml           # 项目配置与依赖声明
└── uv.lock                  # 依赖锁定文件
```

### 数据流

```
collect_fund_data.py ──预采集──→ SQLite (data/fundkit.db)
                                    │
Streamlit 页面 ──本地 JOIN 查询──→   │
                                    │
                                    ├─ fund_catalog    (27,037 只)
                                    ├─ fund_fee        (26,770 只)
                                    ├─ fund_scale      (26,505 只)
                                    ├─ fund_profile    (26,770 只)
                                    ├─ fund_nav        (25,333 只)  ← 日频快照
                                    ├─ fund_nav_history(3,273 条/基) ← 全量历史缓存(回测用)
                                    ├─ index_series    (73,742 条)
                                    ├─ cache_meta      (17 条)
                                    └─ funds_meta      (3 条 TTL 标记)
```

**关键设计**：所有 Streamlit 页面通过 `db.py` 的本地 JOIN 查询读取缓存，**零 AKShare API 调用**。预采集脚本 `collect_fund_data.py` 独立管理各数据的 TTL（费率 90 天 / 净值 24 小时 / 名录 90 天）。定投回测 `fetch_fund_data()` 优先读取 `fund_nav_history` 本地缓存。

## 核心技术

| 技术 | 用途 |
|------|------|
| Python 3.9+ | 运行环境 |
| [AKShare](https://github.com/akfamily/akshare) | 金融数据接口（天天基金网、中证指数等） |
| Streamlit | 图形界面框架 |
| pandas / numpy | 数据处理与计算 |
| matplotlib | 图表绘制 |
| SQLAlchemy Core | 数据库管理（SQLite + WAL 模式） |
| py_mini_racer | JS 引擎（解析东方财富 pingzhongdata 文件） |

## 快速开始

```bash
# 安装依赖（自动创建 .venv）
uv sync --extra dev

# 预采集数据（首次使用）
uv run python collect_fund_data.py --catalog     # 基金名录
uv run python collect_fund_data.py               # 费率+规模+档案+跟踪方式
uv run python collect_fund_data.py --nav         # 净值

# 启动图形界面
uv run streamlit run app.py

# 或使用命令行定投回测（详见 docs/dca_backtest_cli.md）
uv run python -m backend.dca_backtest --fund 163415 --amount 1000 --start 2018-01-01
```

## 注意事项

- 依赖网络连接，数据源均为公开平台
- 图表中文显示需要系统安装中文字体（自动检测 `Noto Sans CJK` 等）
- 数据缓存于 `data/fundkit.db`，默认 24 小时刷新
