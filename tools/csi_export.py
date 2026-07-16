"""
从 csindex.com.cn 官方导出接口获取全量指数列表。

数据源：中证指数公司官网 "指数全景 → 指数列表" 的导出按钮
→ POST https://www.csindex.com.cn/csindex-home/exportExcel/indexAll/CH
返回 Excel 文件，包含 2967 条指数（1847 条股票类）。
"""

import logging

from io import BytesIO
from pathlib import Path

import pandas as pd
import requests

from backend.logger import get_logger

logger = get_logger(__name__)

_CSI_URL = "https://www.csindex.com.cn/csindex-home/exportExcel/indexAll/CH"
_CACHE_DIR = Path(__file__).resolve().parent.parent / "data"
_CACHE_FILE = _CACHE_DIR / "csi_index_list.csv"


def fetch_csi_index_list(force: bool = False) -> pd.DataFrame:
    """从 CSI 官网获取全量指数列表，优先读本地缓存。

    Args:
        force: 强制从 API 刷新缓存

    Returns:
        DataFrame，包含 指数代码/指数简称/指数全称/资产类别/指数系列 等列
    """
    if not force and _CACHE_FILE.exists():
        df = pd.read_csv(_CACHE_FILE, dtype={"指数代码": str})
        logger.info("从缓存读取 CSI 指数列表: %s 条", len(df))
        return df

    payload = {
        "sorter": {"sortField": "null", "sortOrder": None},
        "pager": {"pageNum": 1, "pageSize": 100000},
        "indexFilter": {
            "ifCustomized": None,
            "ifTracked": None,
            "ifWeightCapped": None,
            "indexCompliance": None,
            "hotSpot": None,
            "indexClassify": None,
            "currency": None,
            "region": None,
            "indexSeries": None,
            "undefined": None,
        },
    }
    headers = {"Content-Type": "application/json;charset=UTF-8"}

    logger.info("从 CSI 官网下载指数列表...")
    r = requests.post(_CSI_URL, json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    df = pd.read_excel(BytesIO(r.content))
    df["指数代码"] = df["指数代码"].astype(str).str.strip()
    logger.info("下载完成: %s 条", len(df))

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(_CACHE_FILE, index=False, encoding="utf-8")
    logger.info("已缓存到 %s", _CACHE_FILE)
    return df


def get_equity_name_map(df: pd.DataFrame | None = None) -> dict[str, tuple[str, str, str]]:
    """构建股票类指数名称→(代码, 市场前缀, 指数简称) 映射。

    映射来源：
      - 指数简称（如 "深证成指"）
      - 指数全称去掉"指数"后缀后归一化

    Returns:
        {display_name: (index_code, market_prefix, short_name)}
    """
    if df is None:
        df = fetch_csi_index_list()
    stock = df[df["资产类别"] == "股票"].copy()
    logger.info("股票类指数: %s 条", len(stock))

    name_map: dict[str, tuple[str, str, str]] = {}
    for _, row in stock.iterrows():
        code = str(row["指数代码"]).strip()
        # Determine market_prefix
        series = str(row["指数系列"]) if pd.notna(row["指数系列"]) else ""
        if code.startswith(("000", "001", "H")) or "上证" in series:
            prefix = "sh"
        elif code.startswith(("399", "98")) or "深证" in series:
            prefix = "sz"
        elif "北证" in series:
            prefix = "bj"
        else:
            prefix = "csi"

        # 指数简称
        short = str(row["指数简称"]).strip() if pd.notna(row["指数简称"]) else ""
        if short:
            name_map[short] = (code, prefix, short)

        # 指数全称（去掉"指数"后缀）
        full = str(row["指数全称"]).strip() if pd.notna(row["指数全称"]) else ""
        if full:
            if full.endswith("指数"):
                name_map[full[:-2]] = (code, prefix, short)
            name_map[full] = (code, prefix, short)

    logger.info("名称→代码映射: %s 条", len(name_map))
    return name_map


if __name__ == "__main__":
    from backend.logger import setup_logging

    setup_logging(level=logging.INFO)
    df = fetch_csi_index_list(force=True)
    print(f"总条数: {len(df)}")
    print(f"资产类别分布:\n{df['资产类别'].value_counts().to_string()}")
    print(f"\n指数系列分布:\n{df['指数系列'].value_counts().to_string()}")
