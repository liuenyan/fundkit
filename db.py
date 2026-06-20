"""
SQLite 数据库管理（SQLAlchemy Core）
统一数据库: data/fundkit.db
"""

import os
import time
from datetime import date, datetime

import pandas as pd
from sqlalchemy import (
    Column,
    Float,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    create_engine,
    event,
    text,
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "fundkit.db")
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, echo=False)


@event.listens_for(engine, "connect")
def _set_wal(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


metadata = MetaData()

# ── 表定义 ──

index_series = Table(
    "index_series",
    metadata,
    Column("name", String, nullable=False),
    Column("metric", String, nullable=False),
    Column("date", String, nullable=False),
    Column("value", Float),
    PrimaryKeyConstraint("name", "metric", "date"),
)

cache_meta = Table(
    "cache_meta",
    metadata,
    Column("name", String, nullable=False),
    Column("metric", String, nullable=False),
    Column("last_updated", String, nullable=False),
    Column("source", String),
    PrimaryKeyConstraint("name", "metric"),
)

funds = Table(
    "funds",
    metadata,
    Column("基金代码", String, primary_key=True),
    Column("基金名称", String),
    Column("单位净值", Float),
    Column("日期", String),
    Column("日增长率", String),
    Column("近1周", String),
    Column("近1月", String),
    Column("近3月", String),
    Column("近6月", String),
    Column("近1年", String),
    Column("近2年", String),
    Column("近3年", String),
    Column("今年来", String),
    Column("成立来", String),
    Column("手续费", Float),
    Column("起购金额", String),
    Column("跟踪标的", String),
    Column("跟踪方式", String),
    Column("最近总份额", Float),
)

funds_meta = Table(
    "funds_meta",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", String),
    Column("updated_at", Float),
)

fund_fees = Table(
    "fund_fees",
    metadata,
    Column("基金代码", String, primary_key=True),
    Column("管理费", Float),
    Column("托管费", Float),
    Column("净资产规模", Float),
    Column("单位净值_fof", Float),
    Column("净值日期_fof", String),
    Column("updated_at", Float),
)

fund_catalog = Table(
    "fund_catalog",
    metadata,
    Column("基金代码", String, primary_key=True),
    Column("拼音缩写", String),
    Column("基金简称", String),
    Column("基金类型", String),
    Column("拼音全称", String),
)

FUND_CACHE_TTL = 86400  # 24 小时
CATALOG_TTL = 86400  # 基金名录默认 TTL


# ── 初始化 ──


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    metadata.create_all(engine)
    for col in ["净资产规模", "单位净值_fof", "净值日期_fof"]:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE fund_fees ADD COLUMN {col}"))
        except Exception:
            pass


# ── 基金缓存 ──


def load_funds():
    try:
        return pd.read_sql(text("SELECT * FROM funds"), engine)
    except Exception:
        return None


def save_funds(df):
    df.to_sql("funds", engine, if_exists="replace", index=False)
    with engine.begin() as conn:
        conn.execute(
            funds_meta.insert().prefix_with("OR REPLACE"),
            {"key": "funds", "value": "ok", "updated_at": time.time()},
        )


def is_funds_cache_fresh():
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT updated_at FROM funds_meta WHERE key='funds'")
            ).fetchone()
            if row and row[0]:
                return time.time() - row[0] < FUND_CACHE_TTL
    except Exception:
        pass
    return False


# ── 估值序列缓存 ──


def load_series(name, metric):
    return pd.read_sql_query(
        "SELECT date, value FROM index_series WHERE name=? AND metric=? ORDER BY date",
        engine, params=(name, metric),
    )


def upsert_series(name, metric, df):
    with engine.begin() as conn:
        for _, row in df.iterrows():
            conn.execute(
                index_series.insert().prefix_with("OR IGNORE"),
                {"name": name, "metric": metric,
                 "date": str(row["date"]), "value": float(row["value"])},
            )


def get_series_last_date(name, metric):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT MAX(date) FROM index_series WHERE name=:name AND metric=:metric"),
            {"name": name, "metric": metric},
        ).fetchone()
        return row[0] if row and row[0] else None


def get_cache_meta(name, metric):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT * FROM cache_meta WHERE name=:name AND metric=:metric"),
            {"name": name, "metric": metric},
        ).fetchone()


def set_cache_meta(name, metric, source):
    today = date.today().isoformat()
    with engine.begin() as conn:
        conn.execute(
            cache_meta.insert().prefix_with("OR REPLACE"),
            {"name": name, "metric": metric,
             "last_updated": today, "source": source},
        )


def is_series_fresh(name, metric, max_age_days=2):
    last = get_series_last_date(name, metric)
    if last is not None:
        last_date = datetime.strptime(last, "%Y-%m-%d").date()
        if (datetime.now().date() - last_date).days <= max_age_days:
            return True
    meta = get_cache_meta(name, metric)
    if meta and meta.last_updated:
        meta_date = datetime.strptime(meta.last_updated, "%Y-%m-%d").date()
        if (datetime.now().date() - meta_date).days <= 1:
            return True
    return False


# ── 清空 ──


# ── 基金费率缓存 ──


def load_fund_fees(codes):
    """从缓存批量加载费率+规模+FOF净值，返回 {code: {...}}"""
    if not codes:
        return {}
    result = {}
    with engine.connect() as conn:
        stmt = fund_fees.select().where(fund_fees.c.基金代码.in_(codes))
        rows = conn.execute(stmt).fetchall()
        for r in rows:
            result[r[0]] = {
                "管理费": r[1],
                "托管费": r[2],
                "净资产规模": r[3] if len(r) > 3 else None,
                "单位净值_fof": r[4] if len(r) > 4 else None,
                "净值日期_fof": r[5] if len(r) > 5 else None,
            }
    return result


def save_fund_fee(code, mgmt, cust, scale=None, nav=None, nav_date=None):
    """写入单只基金费率+规模+FOF净值缓存"""
    with engine.begin() as conn:
        conn.execute(
            fund_fees.insert().prefix_with("OR REPLACE"),
            {"基金代码": code, "管理费": mgmt, "托管费": cust,
             "净资产规模": scale,
             "单位净值_fof": nav, "净值日期_fof": nav_date,
             "updated_at": time.time()},
        )


def clear_fund_fees():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM fund_fees"))


# ── 基金名录缓存 ──


def load_catalog():
    """从 fund_catalog 表加载基金名录，返回 DataFrame 或 None"""
    try:
        return pd.read_sql(text("SELECT * FROM fund_catalog"), engine)
    except Exception:
        return None


def save_catalog(df):
    """写入基金名录到 fund_catalog 表并记录 TTL"""
    df.to_sql("fund_catalog", engine, if_exists="replace", index=False)
    with engine.begin() as conn:
        conn.execute(
            funds_meta.insert().prefix_with("OR REPLACE"),
            {"key": "fund_catalog", "value": "ok", "updated_at": time.time()},
        )


def is_catalog_fresh(ttl=None):
    """检查 fund_catalog 缓存是否仍在 TTL 内"""
    if ttl is None:
        ttl = CATALOG_TTL
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT updated_at FROM funds_meta WHERE key='fund_catalog'")
            ).fetchone()
            if row and row[0]:
                return time.time() - row[0] < ttl
    except Exception:
        pass
    return False


def clear_catalog():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM fund_catalog"))
        conn.execute(text("DELETE FROM funds_meta WHERE key='fund_catalog'"))


def clear_all():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM index_series"))
        conn.execute(text("DELETE FROM cache_meta"))
        conn.execute(text("DELETE FROM funds"))
        conn.execute(text("DELETE FROM funds_meta"))
        conn.execute(text("DELETE FROM fund_fees"))
