"""
基金数据共享层 — 规模、费率、排序等通用功能
数据源: 天天基金网优先，雪球兜底
"""

import concurrent.futures
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


def _parse_scale(s):
    if not s:
        return None
    s = str(s).strip()
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


def fetch_one_overview(code):
    """单只基金获取管理费/托管费/销售服务费/净资产规模/份额规模/档案信息"""
    try:
        df = ak.fund_overview_em(symbol=code)
        if df.empty:
            return None
        row = df.iloc[0]
        mgmt = parse_fee_pct(row.get("管理费率"))
        cust = parse_fee_pct(row.get("托管费率"))
        sales_service = parse_fee_pct(row.get("销售服务费率"))
        scale = _parse_scale(row.get("净资产规模"))
        scale_shares = _parse_scale(row.get("份额规模"))
        establish_full = str(row.get("成立日期/规模")) if pd.notna(row.get("成立日期/规模")) else None
        establish_date = establish_full.split(" / ")[0] if establish_full else None
        return (
            mgmt,
            cust,
            sales_service,
            scale,
            scale_shares,
            str(row.get("发行日期")) or None,
            establish_date,
            str(row.get("基金管理人")) or None,
            str(row.get("基金托管人")) or None,
            str(row.get("基金经理人")) or None,
            str(row.get("业绩比较基准")) or None,
            str(row.get("跟踪标的")) or None,
        )
    except Exception:
        return None


def batch_fetch_overview(codes, on_result, max_workers=10):
    """并发调用 fetch_one_overview，对每个结果回调 on_result(code, 12字段元组或None)。
    Yields (done, total) 供调用方处理进度。
    """
    total = len(codes)
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        fut_map = {pool.submit(fetch_one_overview, c): c for c in codes}
        for f in concurrent.futures.as_completed(fut_map):
            done += 1
            on_result(fut_map[f], f.result())
            yield done, total


def _parse_purchase(s):
    """解析 fund_purchase_em 的 手续费，用于批量获取申购费"""
    if pd.isna(s) or s is None:
        return None
    s = str(s).strip().replace("%", "").replace("---", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def fetch_purchase_data(codes=None):
    """获取申购费+起购金额。返回 {code: (purchase, min_purchase)}。
    codes=None 表示全部；空列表返回 {}。
    """
    try:
        df = ak.fund_purchase_em()
    except Exception:
        return {}
    if codes:
        df = df[df["基金代码"].isin(codes)]
    result = {}
    for _, row in df.iterrows():
        code = row["基金代码"]
        result[code] = (
            _parse_purchase(row.get("手续费")),
            str(row.get("购买起点", "")) if pd.notna(row.get("购买起点")) else None,
        )
    return result


def save_overview_result(code, result, purchase, min_purchase):
    """将 fund_overview_em 的 12 字段结果写入 DB 三表（fee + scale + profile）"""
    if result is None:
        return
    (
        mgmt, cust, sales_service, scale, scale_shares,
        issue_date, establish_date, mgr, custodian, fund_mgr,
        benchmark, track_index,
    ) = result
    sales = sales_service if sales_service is not None else 0
    total_fee = (
        round((purchase or 0) + (mgmt or 0) + (cust or 0) + sales, 2)
        if mgmt is not None and cust is not None
        else None
    )
    db.fund_fees.save(code, purchase, mgmt, cust, sales_service, min_purchase, total_fee)
    db.fund_scale.save(code, scale, scale_shares)
    db.fund_profile.save(code, issue_date, establish_date, mgr, custodian, fund_mgr, benchmark, track_index)


def fetch_mgmt_cust_fees(codes, progress_placeholder=None):
    """批量获取管理费/托管费/销售服务费/规模/档案。
    优先级: DB 缓存(预采集) → 天天基金(fund_overview_em, 并发) → 雪球兜底
    返回 (mgmt_map, cust_map, sales_service_map, scale_map, purchase_map,
           min_purchase_map, scale_shares_map)
    """
    mgmt_map = {}
    cust_map = {}
    sales_service_map = {}
    scale_map = {}
    purchase_map = {}
    min_purchase_map = {}
    scale_shares_map = {}

    # ── 从 DB 缓存读取 ──
    cached = db.fund_fees.load(codes)
    scale_raw = db.fund_scale.load(codes)
    for c, v in scale_raw.items():
        scale_map[c] = v["净资产规模"]
        scale_shares_map[c] = v["份额规模"]
    uncached = []
    for c in codes:
        if c in cached:
            entry = cached[c]
            if entry["管理费"] is not None:
                mgmt_map[c] = entry["管理费"]
                cust_map[c] = entry["托管费"]
                sales_service_map[c] = entry["销售服务费"]
                purchase_map[c] = entry["申购费"]
                min_purchase_map[c] = entry["起购金额"]
                continue
        uncached.append(c)

    if not uncached:
        return (
            mgmt_map,
            cust_map,
            sales_service_map,
            scale_map,
            purchase_map,
            min_purchase_map,
            scale_shares_map,
        )

    # ── 未缓存: 先用 fund_purchase_em 批量补申购费+起购金额 ──
    purchase_data = fetch_purchase_data(uncached)
    for code, (p, mp) in purchase_data.items():
        purchase_map[code] = p
        min_purchase_map[code] = mp

    # ── 并发获取管理费/托管费/销售服务费 ──
    total = len(uncached)
    if progress_placeholder and total > 0:
        progress_placeholder.markdown(f"正在获取费率信息… (0/{total})")

    def _persist(code, result):
        if result is None:
            return
        (
            mgmt, cust, sales_service, scale, scale_shares,
            *_,
        ) = result
        mgmt_map[code] = mgmt
        cust_map[code] = cust
        sales_service_map[code] = sales_service
        scale_map[code] = scale
        scale_shares_map[code] = scale_shares
        save_overview_result(code, result, purchase_map.get(code), min_purchase_map.get(code))

    for done, total in batch_fetch_overview(uncached, _persist, max_workers=10):
        if progress_placeholder:
            pct = int(done / total * 100) if total else 100
            progress_placeholder.markdown(f"正在获取费率信息… ({done}/{total}, {pct}%)")

    return (
        mgmt_map,
        cust_map,
        sales_service_map,
        scale_map,
        purchase_map,
        min_purchase_map,
        scale_shares_map,
    )


def enrich_fee_scale(result, scale_source=None, progress_placeholder=None):
    """通用费率/规模补充。result 须含 基金代码 单位净值 手续费 列。
    scale_source: 外部规模 DataFrame 或 None（已含在 result 中则跳过）
    """
    result = result.copy()

    nav = pd.to_numeric(result.get("单位净值"), errors="coerce")
    codes = result["基金代码"].tolist()

    (
        mgmt_map,
        cust_map,
        sales_service_map,
        scale_map,
        purchase_map,
        min_purchase_map,
        scale_shares_map,
    ) = fetch_mgmt_cust_fees(codes, progress_placeholder)

    if "基金规模" in result.columns:
        missing = result["基金规模"].isna()
        if missing.any():
            result.loc[missing, "基金规模"] = result.loc[missing, "基金代码"].map(scale_map)
    elif scale_source is not None:
        s_map = scale_source.set_index("基金代码")["基金规模"].to_dict()
        result["基金规模"] = result["基金代码"].map(s_map)
    elif "最近总份额" in result.columns:
        shares = pd.to_numeric(result["最近总份额"], errors="coerce")
        result["基金规模"] = (nav * shares / 1e8).round(2)
    else:
        result["基金规模"] = result["基金代码"].map(scale_map)

    # 净资产规模缺失时用 份额规模 × 单位净值 兜底
    still_missing = result["基金规模"].isna()
    if still_missing.any():
        result["基金规模"] = result["基金规模"].fillna((nav * result["基金代码"].map(scale_shares_map)).round(2))
    # 费率: 申购费优先取 result 中已有手续费列，缺失则从缓存补
    if "手续费" in result.columns:
        fee_raw = result["手续费"].astype(str).str.replace("%", "", regex=False)
        result["申购费"] = pd.to_numeric(fee_raw, errors="coerce")
        missing_purchase = result["申购费"].isna()
        if missing_purchase.any():
            result.loc[missing_purchase, "申购费"] = result.loc[missing_purchase, "基金代码"].map(purchase_map)
    else:
        result["申购费"] = result["基金代码"].map(purchase_map)

    result["管理费"] = result["基金代码"].map(mgmt_map)
    result["托管费"] = result["基金代码"].map(cust_map)
    result["销售服务费"] = result["基金代码"].map(sales_service_map)
    result["起购金额"] = result["基金代码"].map(min_purchase_map)

    purchase = result["申购费"].fillna(0)
    mgmt = result["管理费"]
    cust = result["托管费"]
    sales = result["销售服务费"].fillna(0)
    result["综合费率"] = ((purchase + mgmt + cust + sales).round(2)).where(mgmt.notna() & cust.notna(), pd.NA)
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
