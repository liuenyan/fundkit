[![CI](https://github.com/liuenyan/fundkit/actions/workflows/ci.yml/badge.svg)](https://github.com/liuenyan/fundkit/actions/workflows/ci.yml)

# FundKit — 中国公募基金工具箱

一站式中国公募基金分析工具，覆盖**定投回测**、**指数估值**、**指数选基**三大场景。数据源基于天天基金网、中证指数、乐咕乐股等公开平台（通过 [AKShare](https://github.com/akfamily/akshare) 获取），提供 Streamlit 图形界面与 CLI 双模式。

## 功能

### 定投回测

对任意开放式基金进行历史定投（DCA）模拟，支持多频率、多策略、自定义费率，输出收益率、回撤、图表及 CSV 明细。

- 定投频率：每日 / 每周 / 每两周 / 每月，自动匹配交易日
- 申购费 & 阶梯赎回费：可配置
- 一次性投入对比：等额资金一次性买入 vs 定投
- 止盈策略 A：目标止盈（达阈值卖出，可选循环）
- 止盈策略 B：停投持有 + 移动止盈（达标停投，回撤卖出，可选循环）
- 图表输出：双面板 PNG（净值 + 成本 / 收益率 + 回撤）
- CSV 导出

### 指数估值

追踪主流指数的 PE / PB 历史百分位，辅助判断估值高低。

- 指数覆盖：沪深300、中证500、中证红利、红利低波、CS消费50、创业板50
- 百分位曲线：5 年 / 10 年滚动百分位 + 原始值叠加
- 指数点位 & PE 叠加走势图
- 中证红利股息率 vs 十年期国债收益率：历史对比双轴图
- 低估 / 适中 / 高估 三档标签

### 指数选基

按指数名称搜索跟踪该指数的全部基金，对比规模、费率等指标，快速跳转定投回测。

- 搜索方式：文本搜索 + 热门指数下拉列表
- 综合费率展示：申购费（实际折扣后）+ 管理费 + 托管费
- 筛选：基金类型（ETF联接 / 指数增强 / 普通指数型）、份额类别（A / C / 其他）
- 排序：费率、规模、净值
- 一键跳转定投回测：点击即带参数跳转至定投回测页

### 养老金选基

筛选个人养老金账户可投资的 Y 份额基金，按类型（指数基金、FOF-目标日期、FOF-目标风险）分类展示，支持规模/费率排序。

- 数据源全 DB 查询，零 API 冷启动
- 自动加载 Y 份额净值、费率、规模
- 管理费/托管费懒加载缓存（会话级）

## 架构

```
fundkit/
├── app.py                   # Streamlit 导航中枢（四个页面）
│
├── backend/                 # 业务逻辑层
│   ├── __init__.py
│   ├── dca_backtest.py      # 定投回测 CLI 主程序（python -m backend.dca_backtest）
│   ├── index_valuation.py   # 指数估值百分位计算后端
│   ├── index_fund.py        # 指数选基数据获取 + 搜索/筛选/排序
│   ├── pension_fund.py      # 养老金选基后端
│   └── fund_data.py         # 基金数据共享层（费率解析、规模兜底等）
│
├── collect_fund_data.py     # 预采集脚本（费率/规模/档案/净值/名录/跟踪方式，根目录独立分层）
├── db.py                    # SQLAlchemy Core 数据库层（SQLite，WAL 模式，9 张活跃表）
├── cjk_font.py              # 中文字体检测与设置
│
├── app_pages/
│   ├── dca.py               # 定投回测页面
│   ├── index_valuation.py   # 指数估值页面
│   ├── index_fund.py        # 指数选基页面
│   └── pension_fund.py      # 养老金选基页面（Y 份额）
│
├── data/                    # SQLite 数据库目录（自动创建）
├── charts/                  # 图表输出目录（自动创建）
├── docs/
│   ├── dca_backtest_cli.md  # 命令行定投回测完整手册
│   ├── collect_fund_data.md # 预采集工具文档
│   ├── data_source.md       # 数据源调研与选型说明
│   └── database.md          # 数据库表设计文档
│
├── ruff.toml                # ruff 代码规范配置
├── requirements.txt         # Python 运行时依赖
└── requirements-dev.txt     # 开发依赖（ruff）
```

### 数据流

```
collect_fund_data.py ──预采集──→ SQLite (data/fundkit.db)
                                    │
Streamlit 页面 ──本地 JOIN 查询──→   │
                                    │
                                    ├─ fund_catalog   (27,037 只)
                                    ├─ fund_fee       (26,770 只)
                                    ├─ fund_scale     (26,505 只)
                                    ├─ fund_profile   (26,770 只)
                                    ├─ fund_nav       (25,333 只)
                                    ├─ index_series   (73,742 条)
                                    ├─ cache_meta     (17 条)
                                    └─ funds_meta     (3 条 TTL 标记)
```

**关键设计**：所有 Streamlit 页面（指数选基、养老金选基）通过 `db.py` 的本地 JOIN 查询读取缓存，**零 AKShare API 调用**。预采集脚本 `collect_fund_data.py` 独立管理各数据的 TTL（费率 90 天 / 净值 24 小时 / 名录 90 天）。

## 核心技术

| 技术 | 用途 |
|------|------|
| Python 3.9+ | 运行环境 |
| [AKShare](https://github.com/akfamily/akshare) | 金融数据接口（天天基金网、中证指数等） |
| Streamlit | 图形界面框架 |
| pandas / numpy | 数据处理与计算 |
| matplotlib | 图表绘制 |
| SQLAlchemy Core | 数据库管理（SQLite + WAL 模式） |

## 快速开始

```bash
# 安装依赖（虚拟环境）
./venv/bin/pip install -r requirements.txt

# 预采集数据（首次使用）
python collect_fund_data.py --catalog     # 基金名录
python collect_fund_data.py               # 费率+规模+档案+跟踪方式
python collect_fund_data.py --nav         # 净值

# 启动图形界面
streamlit run app.py

# 或使用命令行定投回测（详见 docs/dca_backtest_cli.md）
python -m backend.dca_backtest --fund 163415 --amount 1000 --start 2018-01-01
```

## 注意事项

- 依赖网络连接，数据源均为公开平台
- 图表中文显示需要系统安装中文字体（自动检测 `Noto Sans CJK` 等）
- 数据缓存于 `data/fundkit.db`，默认 24 小时刷新
