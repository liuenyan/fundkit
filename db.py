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

fund_fee = Table(
    "fund_fee",
    metadata,
    Column("基金代码", String, primary_key=True),
    Column("申购费", Float),
    Column("管理费", Float),
    Column("托管费", Float),
    Column("销售服务费", Float),
    Column("起购金额", String),
    Column("综合费率", Float),
    Column("净资产规模", Float),
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
FEE_TTL = 7776000  # 费率缓存 90 天
SCALE_TTL = 86400  # 规模缓存 24 小时


# ── 初始化 ──


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    metadata.create_all(engine)
    # 迁移: 为 fund_fee 添加净资产规模列（若不存在）
    try:
        with engine.connect() as conn:
            cols = [row[1] for row in conn.execute(
                text("PRAGMA table_info(fund_fee)")
            ).fetchall()]
            if "净资产规模" not in cols:
                conn.execute(text("ALTER TABLE fund_fee ADD COLUMN 净资产规模 Float"))
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
    """从缓存批量加载费率，返回 {code: {...}}"""
    if not codes:
        return {}
    result = {}
    with engine.connect() as conn:
        stmt = fund_fee.select().where(fund_fee.c.基金代码.in_(codes))
        rows = conn.execute(stmt).fetchall()
        for r in rows:
            result[r[0]] = {
                "申购费": r[1],
                "管理费": r[2],
                "托管费": r[3],
                "销售服务费": r[4] if len(r) > 4 else None,
                "起购金额": r[5] if len(r) > 5 else None,
                "综合费率": r[6] if len(r) > 6 else None,
                "净资产规模": r[7] if len(r) > 7 else None,
            }
    return result


def save_fund_fee(code, purchase, mgmt, cust, sales_service, min_purchase, total, scale=None):
    """写入单只基金费率缓存。scale 为净资产规模（亿元）。"""
    with engine.begin() as conn:
        conn.execute(
            fund_fee.insert().prefix_with("OR REPLACE"),
            {"基金代码": code,
             "申购费": purchase, "管理费": mgmt, "托管费": cust,
             "销售服务费": sales_service, "起购金额": min_purchase,
             "综合费率": total, "净资产规模": scale,
             "updated_at": time.time()},
        )


def clear_fund_fees():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM fund_fee"))


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


def is_fee_cache_fresh(ttl=None):
    """检查 fund_fee 缓存是否仍在 TTL 内"""
    if ttl is None:
        ttl = FEE_TTL
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT updated_at FROM funds_meta WHERE key='fund_fee'")
            ).fetchone()
            if row and row[0]:
                return time.time() - row[0] < ttl
    except Exception:
        pass
    return False


def set_fee_cache_fresh():
    with engine.begin() as conn:
        conn.execute(
            funds_meta.insert().prefix_with("OR REPLACE"),
            {"key": "fund_fee", "value": "ok", "updated_at": time.time()},
        )


def get_fee_cached_count():
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT COUNT(*) FROM fund_fee")).fetchone()
            return row[0] if row else 0
    except Exception:
        return 0


def clear_all():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM index_series"))
        conn.execute(text("DELETE FROM cache_meta"))
        conn.execute(text("DELETE FROM funds"))
        conn.execute(text("DELETE FROM funds_meta"))
        conn.execute(text("DELETE FROM fund_fee"))
