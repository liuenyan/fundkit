# 中国开放式基金定投回测工具

基于 Python 的命令行工具，用于对中国开放式基金进行定投（DCA）回测分析。数据来源于天天基金网（通过 [AKShare](https://github.com/akfamily/akshare) 获取）。

## 功能特性

- **定投频率**：支持每日、每周、每两周、每月定投
- **定投日期**：可按月指定日期（1–28 日），按周指定交易日（周一至周五）
- **自动匹配交易日**：若定投日为非交易日，自动顺延至最近交易日
- **申购费**：可配置费率（默认 0.15%）
- **赎回费**：按持有期限阶梯费率计算（默认：<7 天 1.5%、7–30 天 0.75%、30–365 天 0.5%、1–2 年 0.25%、≥2 年 0%）
- **一次性投入对比**：将等额资金一次性投入的收益与定投收益进行对比
- **收益率计算**：总收益率、年化收益率、最大回撤
- **图表输出**：自动生成双面板 PNG 图表（净值走势 & 定投成本 / 定投收益率 & 回撤）
- **CSV 导出**：支持将定投明细导出为 CSV
- **基金名称识别**：自动识别并显示基金简称

## 安装

### 依赖

- Python >= 3.9
- pip

### 安装步骤

```bash
# 克隆或进入项目目录
cd fund_dca_backtest

# 创建虚拟环境（可选）
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt
```

## 使用方法

```bash
python dca_backtest.py --fund <基金代码> --amount <每期金额> [选项]
```

### 参数说明

| 参数 | 必需 | 说明 |
|------|------|------|
| `--fund` | 是 | 基金代码（6 位数字） |
| `--amount` | 是 | 每期定投金额（元） |
| `--start` | 是 | 开始日期（YYYY-MM-DD） |
| `--end` | 否 | 结束日期（默认当天） |
| `--freq` | 否 | 定投频率：`daily` / `weekly` / `biweekly` / `monthly`（默认 `monthly`） |
| `--day` | 否 | 每月定投日 1–28（仅 `monthly` 有效，默认 10） |
| `--weekday` | 否 | 每周定投日 1=周一..5=周五（仅 `weekly` / `biweekly` 有效，默认 1） |
| `--fee` | 否 | 申购费率（默认 0.0015 = 0.15%） |
| `--output` | 否 | CSV 导出路径 |
| `--chart` | 否 | 图表输出目录（默认 `./charts`） |

### 示例

**月度定投**：每月 10 日定投招商中证白酒指数基金 1000 元，2018 年至 2025 年：

```bash
python dca_backtest.py --fund 161725 --amount 1000 --start 2018-01-01 --end 2025-12-31
```

**周定投**：每周一定投 500 元：

```bash
python dca_backtest.py --fund 161725 --amount 500 --freq weekly --start 2020-01-01
```

**双周定投**：每两周周四定投：

```bash
python dca_backtest.py --fund 161725 --amount 500 --freq biweekly --weekday 4 --start 2020-01-01
```

**每日定投**：

```bash
python dca_backtest.py --fund 161725 --amount 100 --freq daily --start 2023-01-01
```

## 输出说明

### 控制台输出

- 回测摘要：总投入、期末市值、赎回费、实际到账、总收益率、年化收益率、最大回撤
- 一次性投入对比：同等金额一次性投入的最终价值、收益率，并与定投结果比较胜负
- 逐期明细表：每期日期、净值、投入金额、获得份额、累计份额、市值、收益率

### 图表输出

图表保存在 `--chart` 指定目录（默认 `./charts/`），以基金代码命名：`<基金代码>_dca_backtest.png`。

图表包含两个子图：

1. **净值走势与定投成本**：单位净值、累计净值曲线 + 定投平均成本线
2. **定投收益率与回撤**：定投收益率曲线 + 回撤填充区域

### CSV 导出

使用 `--output <路径>` 可将逐期明细导出为 UTF-8 编码的 CSV 文件。

## 注意事项

- 仅支持开放式基金（非封闭式、非 ETF），使用 AKShare 接口需联网
- 图表中的中文标签需要系统安装中文字体，脚本会自动检测 `Noto Sans CJK` 等常见字体
- 赎回费使用默认阶梯费率，不同基金可能有差异，可根据实际修改
- 数据源为天天基金网，历史净值数据可能存在缺失或延迟

## 项目结构

```
fund_dca_backtest/
├── dca_backtest.py      # 主程序
├── requirements.txt     # Python 依赖
├── README.md            # 本文件
└── charts/              # 图表输出目录（自动创建）
```

## 依赖

- [AKShare](https://github.com/akfamily/akshare) — 开源金融数据接口
- pandas — 数据处理
- matplotlib — 图表绘制
- numpy — 数值计算
