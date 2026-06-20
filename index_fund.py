"""
指数选基 — 根据指数选择跟踪的指数基金
数据源: 天天基金网 (via AKShare)
"""

import re

import akshare as ak
import pandas as pd
import streamlit as st

import db
import fund_catalog
import fund_data

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
    # ── 商品 ──
    "黄金ETF联接",
]


@st.cache_data(ttl=3600, show_spinner="获取全市场指数基金数据…")
def fetch_all_index_funds():
    db.init_db()
    if db.is_funds_cache_fresh():
        cached = db.load_funds()
        if cached is not None:
            return cached

    domestic = ak.fund_info_index_em(symbol="全部", indicator="全部")
    domestic = domestic[[c for c in domestic.columns if c != "-"]].copy()
    domestic_codes = set(domestic["基金代码"])

    name_df = fund_catalog.get_catalog()
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

    db.save_funds(domestic)
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


SORT_OPTIONS = fund_data.SORT_OPTIONS


def classify_share_class(name):
    name_upper = str(name).upper().rstrip("①②③④⑤⑥⑦⑧⑨⑩")
    if name_upper.endswith("Y") or "Y类" in name_upper:
        return "Y类"
    if name_upper.endswith("E") or "E类" in name_upper:
        return "E类"
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
    return fund_data.enrich_fee_scale(result)


def sort_result(result, sort_by):
    return fund_data.sort_result(result, sort_by)


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
