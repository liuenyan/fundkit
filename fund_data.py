"""
基金数据共享层 — 规模、费率、排序等通用功能
数据源: 天天基金网优先，雪球兜底
"""

import re

import pandas as pd
import akshare as ak

import db

SORT_OPTIONS = {
    "默认": None,
    "综合费率从低到高": ("综合费率", True),
    "综合费率从高到低": ("综合费率", False),
    "规模从大到小": ("基金规模", False),
    "规模从小到大": ("基金规模", True),
}


def parse_fee_pct(v):
    if v is None:
        return None
    try:
        return float(str(v).replace("%", "").replace("（每年）", "").replace(" ", "").strip())
    except (ValueError, TypeError):
        return None


def fetch_fund_scale():
    """从新浪获取全市场规模数据"""
    parts = []
    for stype in ["股票型基金", "混合型基金", "债券型基金", "QDII基金"]:
        try:
            sdf = ak.fund_scale_open_sina(symbol=stype)
            parts.append(sdf)
        except Exception:
            pass
    if not parts:
        return pd.DataFrame(columns=["基金代码", "基金规模"])
    scale_all = pd.concat(parts, ignore_index=True)
    scale_col = "最新规模" if "最新规模" in scale_all.columns else "最近总份额"
    scale_all = scale_all[["基金代码", scale_col]].drop_duplicates(subset="基金代码")
    scale_all = scale_all.rename(columns={scale_col: "基金规模"})
    scale_all["基金规模"] = pd.to_numeric(scale_all["基金规模"], errors="coerce")
    return scale_all


def _fetch_mgmt_cust_from_eastmoney(code):
    """从天天基金 fund_overview_em 获取管理费/托管费"""
    try:
        df = ak.fund_overview_em(symbol=code)
        if df.empty:
            return None, None
        row = df.iloc[0]
        mgmt = parse_fee_pct(row.get("管理费率"))
        cust = parse_fee_pct(row.get("托管费率"))
        return mgmt, cust
    except Exception:
        return None, None


def _fetch_mgmt_cust_from_xueqiu(code):
    """从雪球 fund_individual_detail_info_xq 获取管理费/托管费（兜底）"""
    try:
        df = ak.fund_individual_detail_info_xq(symbol=code)
        mgmt = cust = None
        for _, r in df.iterrows():
            cond = str(r.get("条件或名称", "")).strip()
            v = parse_fee_pct(r.get("费用"))
            if "管理费" in cond:
                mgmt = v
            if "托管费" in cond:
                cust = v
        return mgmt, cust
    except Exception:
        return None, None


def fetch_mgmt_cust_fees(codes, progress_placeholder=None):
    """批量获取管理费和托管费。
    优先级: DB 缓存 → 天天基金 → 雪球兜底
    返回 {code: {管理费, 托管费}}
    """
    mgmt_map = {}
    cust_map = {}

    cached = db.load_fund_fees(codes)
    uncached = []
    for c in codes:
        if c in cached:
            mgmt_map[c] = cached[c]["管理费"]
            cust_map[c] = cached[c]["托管费"]
        else:
            uncached.append(c)

    total = len(uncached)
    if progress_placeholder and total > 0:
        progress_placeholder.markdown(f"正在获取费率信息… (0/{total})")

    for i, c in enumerate(uncached):
        if progress_placeholder:
            progress_placeholder.markdown(f"正在获取费率信息… ({i+1}/{total})")

        mgmt, cust = _fetch_mgmt_cust_from_eastmoney(c)

        if mgmt is None:
            mgmt, cust = _fetch_mgmt_cust_from_xueqiu(c)

        mgmt_map[c] = mgmt
        cust_map[c] = cust
        db.save_fund_fee(c, mgmt, cust)

    return mgmt_map, cust_map


def enrich_fee_scale(result, scale_source=None, progress_placeholder=None):
    """通用费率/规模补充。result 须含 基金代码 单位净值 手续费 列。
    scale_source: 外部规模 DataFrame 或 None（自动获取）
    """
    result = result.copy()

    nav = pd.to_numeric(result.get("单位净值"), errors="coerce")
    if scale_source is not None:
        scale_map = scale_source.set_index("基金代码")["基金规模"].to_dict()
        result["基金规模"] = result["基金代码"].map(scale_map)
    elif "最近总份额" in result.columns:
        shares = pd.to_numeric(result["最近总份额"], errors="coerce")
        result["基金规模"] = (nav * shares / 1e8).round(2)
    else:
        result["基金规模"] = None

    fee_raw = result["手续费"].astype(str).str.replace("%", "", regex=False)
    result["买入费率_天天"] = pd.to_numeric(fee_raw, errors="coerce")

    codes = result["基金代码"].tolist()
    mgmt_map, cust_map = fetch_mgmt_cust_fees(codes, progress_placeholder)
    result["管理费"] = result["基金代码"].map(mgmt_map)
    result["托管费"] = result["基金代码"].map(cust_map)

    buy = result["买入费率_天天"].fillna(0)
    mgmt = result["管理费"]
    cust = result["托管费"]
    result["综合费率"] = ((buy + mgmt + cust).round(2)).where(
        mgmt.notna() & cust.notna(), pd.NA
    )
    return result


def sort_result(result, sort_by):
    """通用排序"""
    sort_config = SORT_OPTIONS.get(sort_by) if sort_by else None
    if sort_config:
        col, asc = sort_config
        if col in result.columns:
            return result.sort_values(col, ascending=asc).reset_index(drop=True)
    result["_name_len"] = result.get("基金名称", pd.Series(dtype=str)).str.len()
    result = result.sort_values("_name_len")
    drop_cols = [c for c in result.columns if c.startswith("_")]
    return result.drop(columns=drop_cols).reset_index(drop=True)
