"""
指数选基 — 根据指数选择跟踪的指数基金
数据源: 天天基金网 (via AKShare)
"""

import os
import re
import sqlite3
import time

import pandas as pd
import akshare as ak
import streamlit as st

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fundkit.db")
CACHE_TTL = 86400  # 24 小时

COMMON_INDICES = [
    # ── 宽基 ──
    "沪深300", "中证500", "中证1000", "中证2000",
    "中证A50", "中证A100", "中证A500",
    "上证50", "上证180", "上证380",
    "科创50", "科创100",
    "创业板指", "创业板50",
    "深证100", "深证50",
    "北证50",
    # ── 海外 / 跨境 ──
    "恒生指数", "恒生科技",
    "纳斯达克100", "标普500", "日经225",
    # ── 策略 / 红利 ──
    "中证红利", "红利低波",
    # ── 消费 ──
    "中证白酒", "中证消费",
    # ── 医药医疗 ──
    "中证医疗", "中证医药",
    # ── 科技 / 制造 ──
    "中证新能源", "中证光伏", "中证半导体", "中证芯片",
    "中证计算机", "中证人工智能", "中证通信",
    # ── 周期 ──
    "中证煤炭", "中证有色", "中证钢铁",
    # ── 金融 ──
    "中证银行", "中证证券", "中证保险",
    # ── 其他行业 ──
    "中证军工", "中证传媒",
    "中证农业", "中证环保",
    "中证基建", "中证房地产",
]


def _init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS funds_meta (key TEXT PRIMARY KEY, value TEXT, updated_at REAL)")
    conn.commit()
    conn.close()


def _cache_fresh():
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("SELECT updated_at FROM funds_meta WHERE key='funds'").fetchone()
        conn.close()
        if row is None:
            return False
        return time.time() - row[0] < CACHE_TTL
    except Exception:
        return False


def _load_from_cache():
    try:
        return pd.read_sql("SELECT * FROM funds", sqlite3.connect(DB_PATH))
    except Exception:
        return None


def _save_to_cache(df):
    conn = sqlite3.connect(DB_PATH)
    df.to_sql("funds", conn, if_exists="replace", index=False)
    conn.execute("INSERT OR REPLACE INTO funds_meta (key, value, updated_at) VALUES (?, ?, ?)",
                 ("funds", "ok", time.time()))
    conn.commit()
    conn.close()


@st.cache_data(ttl=3600, show_spinner="获取全市场指数基金数据…")
def fetch_all_index_funds():
    _init_db()
    if _cache_fresh():
        cached = _load_from_cache()
        if cached is not None:
            return cached

    domestic = ak.fund_info_index_em(symbol="全部", indicator="全部")
    domestic = domestic[[c for c in domestic.columns if c != "-"]].copy()
    domestic_codes = set(domestic["基金代码"])

    name_df = ak.fund_name_em()
    overseas_idx = name_df[name_df["基金类型"].str.contains("指数型-海外", na=False)]
    overseas_codes = set(overseas_idx["基金代码"]) - domestic_codes

    if overseas_codes:
        daily = ak.fund_open_fund_daily_em()
        daily_overseas = daily[daily["基金代码"].isin(overseas_codes)].copy()
        if not daily_overseas.empty:
            nav_col = [c for c in daily_overseas.columns if "单位净值" in c][0]
            date_str = nav_col.split("-单位净值")[0]
            for sep in ("-", "/", "."):
                parts = date_str.split(sep)
                if len(parts) == 3:
                    date_str = f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
                    break
            overseas_rows = []
            for _, r in daily_overseas.iterrows():
                overseas_rows.append({
                    "基金代码": r["基金代码"],
                    "基金名称": r["基金简称"],
                    "单位净值": float(r[nav_col]) if r[nav_col] and str(r[nav_col]).replace(".", "", 1).isdigit() else None,
                    "日期": date_str,
                    "日增长率": r["日增长率"],
                    "手续费": r["手续费"],
                    "起购金额": "",
                    "跟踪标的": "",
                    "跟踪方式": "被动指数型",
                })
            overseas_df = pd.DataFrame(overseas_rows)
            domestic = pd.concat([domestic, overseas_df], ignore_index=True)

    scale = ak.fund_scale_open_sina()
    scale = scale[["基金代码", "最近总份额"]].copy()
    domestic = domestic.merge(scale, on="基金代码", how="left")

    _save_to_cache(domestic)
    return domestic


def _tokenize(query):
    """将查询拆成有意义的 token：连续中文每 2 字一组 + 非中文连续串。"""
    tokens = []
    i = 0
    while i < len(query):
        if '\u4e00' <= query[i] <= '\u9fff':
            end = i
            while end < len(query) and '\u4e00' <= query[end] <= '\u9fff':
                end += 1
            chars = query[i:end]
            for j in range(0, len(chars), 2):
                tokens.append(chars[j:j+2])
            i = end
        else:
            end = i
            while end < len(query) and not ('\u4e00' <= query[end] <= '\u9fff'):
                end += 1
            tokens.append(query[i:end])
            i = end
    return [t for t in tokens if t]


SORT_OPTIONS = {
    "默认": None,
    "综合费率从低到高": ("综合费率", True),
    "综合费率从高到低": ("综合费率", False),
    "规模从大到小": ("基金规模", False),
    "规模从小到大": ("基金规模", True),
}


def _parse_fee_val(v):
    """解析雪球费用值，返回 float（百分比数值）"""
    if v is None:
        return None
    try:
        return float(str(v).replace("%", "").strip())
    except (ValueError, TypeError):
        return None


@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_mgmt_cust(code):
    """从雪球获取单只基金的管理费和托管费。"""
    try:
        df = ak.fund_individual_detail_info_xq(symbol=code)
        result = {"管理费": None, "托管费": None}
        for _, r in df.iterrows():
            cond = str(r.get("条件或名称", "")).strip()
            v = _parse_fee_val(r.get("费用"))
            if "管理费" in cond:
                result["管理费"] = v
            if "托管费" in cond:
                result["托管费"] = v
        return result
    except Exception:
        return {"管理费": None, "托管费": None}


def fetch_fund_fees(codes):
    """批量获取管理费和托管费，返回 {code: {管理费, 托管费}}"""
    fees = {}
    for code in codes:
        fees[code] = _fetch_mgmt_cust(code)
    return fees


def classify_share_class(name):
    name_upper = str(name).upper().rstrip("①②③④⑤⑥⑦⑧⑨⑩")
    if name_upper.endswith("A") or "A类" in name_upper:
        return "A类"
    if name_upper.endswith("C") or "C类" in name_upper:
        return "C类"
    return "其他"


def classify_fund_type(name):
    name_str = str(name)
    if "联接" in name_str:
        return "ETF联接"
    if "增强" in name_str:
        return "指数增强"
    return "普通指数型"


def filter_funds(df, fund_type=None, share_class=None):
    result = df.copy()
    if fund_type:
        result = result[result["基金名称"].apply(classify_fund_type) == fund_type]
    if share_class:
        result = result[result["基金名称"].apply(classify_share_class) == share_class]
    return result.reset_index(drop=True)


def enrich_fee_scale(result):
    """对搜索结果补充费率和规模信息"""
    result = result.copy()
    nav = pd.to_numeric(result["单位净值"], errors="coerce")
    shares = pd.to_numeric(result["最近总份额"], errors="coerce")
    result["基金规模"] = (nav * shares / 1e8).round(2)

    fee_raw = result["手续费"].astype(str).str.replace("%", "", regex=False)
    result["买入费率_天天"] = pd.to_numeric(fee_raw, errors="coerce")

    codes = result["基金代码"].tolist()
    fees = fetch_fund_fees(codes)
    result["管理费"] = result["基金代码"].map(lambda c: fees.get(c, {}).get("管理费"))
    result["托管费"] = result["基金代码"].map(lambda c: fees.get(c, {}).get("托管费"))

    buy = result["买入费率_天天"].fillna(0)
    mgmt = result["管理费"]
    cust = result["托管费"]
    result["综合费率"] = ((buy + mgmt + cust).round(2)).where(
        mgmt.notna() & cust.notna(), pd.NA
    )
    return result


def sort_result(result, sort_by):
    sort_config = SORT_OPTIONS.get(sort_by) if sort_by else None
    if sort_config:
        col, asc = sort_config
        if col == "综合费率":
            result = result.sort_values("综合费率", ascending=asc)
        elif col == "基金规模":
            result = result.sort_values("基金规模", ascending=asc)
    else:
        result["_name_len"] = result["基金名称"].str.len()
        result = result.sort_values("_name_len")
    drop_cols = [c for c in result.columns if c.startswith("_")]
    return result.drop(columns=drop_cols).reset_index(drop=True)


def search_funds_by_index(df, index_name, sort_by=None):
    if not index_name:
        return pd.DataFrame()
    pattern = re.escape(index_name)
    mask = df["基金名称"].str.contains(pattern, case=False, na=False, regex=True)
    result = df[mask].copy()
    if result.empty:
        tokens = _tokenize(index_name)
        if len(tokens) < 2:
            return pd.DataFrame()
        mask = pd.Series(True, index=df.index)
        for t in tokens:
            mask &= df["基金名称"].str.contains(re.escape(t), case=False, na=False, regex=True)
        result = df[mask].copy()

    result = enrich_fee_scale(result)
    result = sort_result(result, sort_by)
    return result
