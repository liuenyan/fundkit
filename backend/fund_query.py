"""
全市场基金查询 — 多维度筛选
"""

import pandas as pd
import streamlit as st

import db

FUND_CATEGORIES = [
    "全部",
    "混合型",
    "债券型",
    "指数型",
    "股票型",
    "FOF",
    "货币型",
    "QDII",
    "Reits",
    "商品",
    "其他",
]

SORT_OPTIONS = {
    "默认": None,
    "综合费率从低到高": ("综合费率", True),
    "综合费率从高到低": ("综合费率", False),
    "规模从大到小": ("基金规模", False),
    "规模从小到大": ("基金规模", True),
    "成立日期从早到晚": ("成立日期", True),
    "成立日期从晚到早": ("成立日期", False),
    "净值从高到低": ("单位净值", False),
    "净值从低到高": ("单位净值", True),
}


def _classify_category(fund_type: str) -> str:
    if not fund_type or pd.isna(fund_type):
        return "其他"
    broad = fund_type.split("-")[0]
    if broad in FUND_CATEGORIES:
        return broad
    return "其他"


@st.cache_data(ttl=3600, show_spinner="获取全市场基金数据…")
def load_all_funds() -> pd.DataFrame:
    """JOIN 五表返回全市场基金信息，含大类分类和最近净值"""
    db.init_db()
    with db.engine.connect() as conn:
        df = pd.read_sql(
            db.text("""
                SELECT
                    cat.基金代码,
                    cat.基金简称 AS 基金名称,
                    cat.基金类型,
                    pf.基金管理人,
                    pf.基金经理,
                    pf.发行日期,
                    pf.成立日期,
                    pf.业绩比较基准,
                    pf.跟踪标的,
                    pf.跟踪方式,
                    fee.申购费,
                    fee.管理费,
                    fee.托管费,
                    fee.销售服务费,
                    fee.综合费率,
                    fee.起购金额,
                    scale.净资产规模 AS 基金规模,
                    nav.单位净值,
                    nav.日增长率,
                    nav.日期 AS 净值日期
                FROM fund_catalog cat
                LEFT JOIN fund_profile pf ON cat.基金代码 = pf.基金代码
                LEFT JOIN fund_fee fee ON cat.基金代码 = fee.基金代码
                LEFT JOIN fund_scale scale ON cat.基金代码 = scale.基金代码
                LEFT JOIN (
                    SELECT n.* FROM fund_nav n
                    INNER JOIN (
                        SELECT 基金代码, MAX(日期) AS max_date
                        FROM fund_nav GROUP BY 基金代码
                    ) m ON n.基金代码 = m.基金代码 AND n.日期 = m.max_date
                ) nav ON cat.基金代码 = nav.基金代码
            """),
            conn,
        )
    if df.empty:
        return df
    df["大类"] = df["基金类型"].apply(_classify_category)
    return df


def query_funds(
    df: pd.DataFrame,
    keyword: str | None = None,
    category: str | None = None,
    manager: str | None = None,
    fund_manager: str | None = None,
    sort_by: str | None = None,
) -> pd.DataFrame:
    result = df.copy()

    if keyword:
        kw = keyword.strip()
        mask = (
            result["基金名称"].str.contains(kw, case=False, na=False)
            | result["基金代码"].str.contains(kw, case=False, na=False)
            | result["基金经理"].str.contains(kw, case=False, na=False)
            | result["基金管理人"].str.contains(kw, case=False, na=False)
        )
        result = result[mask]

    if category and category != "全部":
        if category == "其他":
            known = {c for c in FUND_CATEGORIES if c not in ("全部", "其他")}
            result = result[~result["大类"].isin(known)]
        else:
            result = result[result["大类"] == category]

    if manager:
        result = result[result["基金管理人"] == manager]

    if fund_manager:
        fm = fund_manager.strip()
        result = result[result["基金经理"].str.contains(fm, case=False, na=False)]

    return sort_result(result, sort_by)


def sort_result(result: pd.DataFrame, sort_by: str | None) -> pd.DataFrame:
    config = SORT_OPTIONS.get(sort_by) if sort_by else None
    if config:
        col, asc = config
        if col in result.columns:
            return result.sort_values(col, ascending=asc, na_position="last").reset_index(drop=True)
    result["_name_len"] = result.get("基金名称", pd.Series(dtype=str)).str.len()
    result = result.sort_values("_name_len")
    drop_cols = [c for c in result.columns if c.startswith("_")]
    return result.drop(columns=drop_cols).reset_index(drop=True)


@st.cache_data(ttl=86400, show_spinner="获取基金管理人排名…")
def fetch_top_managers(n: int = 30) -> list[str]:
    """按管理规模（净资产合计）返回 Top N 基金管理人"""
    db.init_db()
    with db.engine.connect() as conn:
        df = pd.read_sql(
            db.text("""
                SELECT pf.基金管理人, SUM(COALESCE(scale.净资产规模, 0)) AS total_scale
                FROM fund_profile pf
                LEFT JOIN fund_scale scale ON pf.基金代码 = scale.基金代码
                WHERE pf.基金管理人 IS NOT NULL AND pf.基金管理人 != ''
                GROUP BY pf.基金管理人
                ORDER BY total_scale DESC
                LIMIT :limit
            """),
            conn,
            params={"limit": n},
        )
    return df["基金管理人"].tolist()
