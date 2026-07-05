"""定投回测图表（CLI / UI 共享）"""

import numpy as np
import pandas as pd
import matplotlib.figure
import matplotlib.pyplot as plt

from backend.cjk_font import setup_cjk_font


def create_chart(nav_df: pd.DataFrame, detail: pd.DataFrame, fund_code: str, fund_name: str) -> matplotlib.figure.Figure:
    """生成两面板图表：净值走势+定投成本 / 定投收益率+回撤"""
    setup_cjk_font()

    fig, axes = plt.subplots(2, 1, figsize=(12, 10), sharex=False)

    ax1 = axes[0]
    ax1.plot(nav_df["date"], nav_df["unit_nav"], color="steelblue", lw=1.2, alpha=0.9, label="单位净值")
    ax1.plot(nav_df["date"], nav_df["acc_nav"], color="steelblue", lw=0.8, ls="--", alpha=0.6, label="累计净值")
    if not detail.empty:
        avg = (detail["total_cost"] / detail["total_units"]).replace([np.inf, -np.inf], np.nan)
        ax1.plot(detail["date"], avg, color="crimson", lw=2, label="定投平均成本")
    ax1.set_title(f"{fund_name}（{fund_code}）净值走势与定投成本")
    ax1.legend(fontsize=10, loc="upper left")
    ax1.grid(True, alpha=0.25)
    ax1.set_ylabel("净值（元）")

    ax2 = axes[1]
    if not detail.empty:
        ret = detail["return_rate"] * 100
        ax2.plot(detail["date"], ret, color="forestgreen", lw=2, label="定投收益率")
        dd_col = "total_value" if "total_value" in detail.columns else "market_value"
        roll_max = detail[dd_col].expanding().max()
        dd = (detail[dd_col] - roll_max) / roll_max * 100
        ax2.fill_between(detail["date"].values, 0, dd.values, alpha=0.25, color="firebrick", label="回撤", step="pre")
    ax2.axhline(y=0, color="gray", ls="--", lw=0.6)
    ax2.set_title(f"{fund_name}（{fund_code}）定投收益率与回撤")
    ax2.legend(fontsize=10, loc="lower left")
    ax2.grid(True, alpha=0.25)
    ax2.set_ylabel("收益率（%）")
    ax2.set_xlabel("日期")

    plt.tight_layout()
    return fig
