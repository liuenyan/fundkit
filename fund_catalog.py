"""
基金名录 — 全市场基金标识与分类信息
数据源: 天天基金网 fund_name_em (27038 只)
缓存: data/fundkit.db → fund_catalog 表, 支持 TTL
"""

import akshare as ak
import pandas as pd

import db


def get_catalog(ttl=86400):
    """获取全市场基金名录，支持 TTL 缓存。
    返回 DataFrame(基金代码, 拼音缩写, 基金简称, 基金类型, 拼音全称)
    """
    db.init_db()
    if db.is_catalog_fresh(ttl):
        cached = db.load_catalog()
        if cached is not None:
            return cached
    df = ak.fund_name_em()
    db.save_catalog(df)
    return df
