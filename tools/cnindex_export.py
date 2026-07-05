"""
从 cnindex.com.cn (国证指数公司) 下载指数列表。

数据源：国证指数官网首页→快捷入口→指数列表
→ https://www.cnindex.com.cn/index_1020/brochures_1593/201912/P020260506563681367298.xlsx
返回 Excel 文件，包含 1384 条指数（1212 条股票类），覆盖深证系列 + 国证系列。

这是中证指数官网 CSI 数据的互补源：CSI 有中证/上证/沪深，这里补深证/国证。
"""

import logging

from io import BytesIO
from pathlib import Path
from typing import Tuple

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_CNINDEX_URL = "https://www.cnindex.com.cn/index_1020/brochures_1593/201912/P020260506563681367298.xlsx"
_CACHE_DIR = Path(__file__).resolve().parent.parent / "data"
_CACHE_FILE = _CACHE_DIR / "cnindex_index_list.csv"

# 归一化后缀（与 build_index_name_map.py 一致）
_SUFFIXES = ["指数", "(价格)", "(四级行业)", "(全价)", "(总值)", "(总收益)", "(LOF)", "(行业)", " "]


def _normalize(name: str) -> str:
    for s in _SUFFIXES:
        name = name.replace(s, "")
    if "(" in name and name.endswith(")"):
        name = name[:name.index("(")]
    if "（" in name and name.endswith("）"):
        name = name[:name.index("（")]
    return name.strip()


def fetch_cnindex_list(force: bool = False) -> pd.DataFrame:
    """从国证官网获取指数列表，优先读本地缓存。

    Args:
        force: 强制从 API 刷新缓存

    Returns:
        DataFrame，包含 指数代码/指数简称/指数全称/资产类别/指数系列 等列
    """
    if not force and _CACHE_FILE.exists():
        df = pd.read_csv(_CACHE_FILE, dtype={"指数代码": str})
        logger.info("从缓存读取国证指数列表: %s 条", len(df))
        return df

    logger.info("从国证官网下载指数列表...")
    r = requests.get(_CNINDEX_URL, timeout=120)
    r.raise_for_status()
    df = pd.read_excel(BytesIO(r.content))
    df["指数代码"] = df["指数代码"].astype(str).str.strip()
    logger.info("下载完成: %s 条", len(df))

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(_CACHE_FILE, index=False, encoding="utf-8")
    logger.info("已缓存到 %s", _CACHE_FILE)
    return df


def get_equity_name_map(df: pd.DataFrame | None = None) -> dict[str, Tuple[str, str | None, str]]:
    """构建股票类指数名称→(代码, 市场前缀, 指数简称) 映射。

    映射来源：
      - 指数简称（如 "深证成指"）
      - 指数全称去掉后缀后归一化（如 "深证成份"）

    Returns:
        {display_name: (index_code, market_prefix, short_name)}
    """
    if df is None:
        df = fetch_cnindex_list()
    stock = df[df["资产类别"] == "股票"].copy()
    logger.info("股票类指数: %s 条", len(stock))

    name_map: dict[str, Tuple[str, str | None, str]] = {}
    for _, row in stock.iterrows():
        code = str(row["指数代码"]).strip()
        series = str(row["指数系列"]) if pd.notna(row["指数系列"]) else ""

        # Determine market_prefix
        if code.startswith("CN"):
            # CN-prefixed codes are total return indices — 无免费公开历史价格 API
            prefix = None
        elif code.startswith("399") and series == "深证系列":
            prefix = "sz"
        elif code.startswith("399"):
            # 国证系列也用 399 开头（历史原因），深交所行情
            prefix = "sz"
        else:
            prefix = "sz"

        short = str(row["指数简称"]).strip() if pd.notna(row["指数简称"]) else ""
        full = str(row["指数全称"]).strip() if pd.notna(row["指数全称"]) else ""

        if short:
            name_map[short] = (code, prefix, short)
        if full:
            name_map[full] = (code, prefix, short)
            # 全称去"指数"后缀
            stripped = full[:-2] if full.endswith("指数") else full
            name_map[stripped] = (code, prefix, short)
            # 全称归一化（保留首次匹配，避免货币变体覆盖标准版）
            normalized = _normalize(full)
            if normalized not in name_map:
                name_map[normalized] = (code, prefix, short)

    logger.info("名称→代码映射: %s 条", len(name_map))
    return name_map


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    df = fetch_cnindex_list(force=True)
    print(f"总条数: {len(df)}")
    print(f"资产类别分布:\n{df['资产类别'].value_counts().to_string()}")
    print(f"\n指数系列分布:\n{df['指数系列'].value_counts().to_string()}")
