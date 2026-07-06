"""
解析工具函数 — 费率、规模、净值等字段的标量/向量化解析
"""

import re
from typing import Any

import pandas as pd


def parse_pct(v: Any) -> float | None:
    """解析费率字段（标量），去 % /（每年）/ --- / 空格 → float"""
    if v is None:
        return None
    try:
        s = str(v).replace("%", "").replace("（每年）", "").replace("---", "").replace(" ", "").strip()
        if not s:
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


def parse_pct_series(s: pd.Series) -> pd.Series:
    """向量化：归一化日增长率"""
    s = s.astype(str).str.strip()
    s = s.replace(["", "nan", "<NA>", "None", "—", "---"], None)
    s = s.str.replace("%", "", regex=False).str.replace(" ", "", regex=False)
    return pd.to_numeric(s, errors="coerce")


def parse_scale(s: Any) -> float | None:
    """解析规模字段（标量），处理 亿 / 万 / 裸数字 → float（亿）

    AKShare 返回值始终带"亿元"/"亿份"后缀，裸数字分支仅作为防御性
    fallback（视为已是亿单位），生产路径不命中。
    """
    if not s:
        return None
    s = str(s).strip().replace(",", "")
    try:
        if "亿" in s:
            m = re.search(r"([\d.]+)\s*亿", s)
            return float(m.group(1)) if m else None
        if "万" in s:
            m = re.search(r"([\d.]+)\s*万", s)
            v = float(m.group(1)) if m else None
            return round(v / 10000, 4) if v else None
        m = re.search(r"([\d.]+)", s)
        return float(m.group(1)) if m else None
    except (ValueError, TypeError, AttributeError):
        return None


def to_float_series(s: pd.Series) -> pd.Series:
    """向量化：转浮点"""
    s = s.astype(str).str.strip()
    s = s.replace(["", "nan", "<NA>", "None"], None)
    return pd.to_numeric(s, errors="coerce")
