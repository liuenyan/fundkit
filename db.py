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
    Column("updated_at", Float),
)

fund_scale = Table(
    "fund_scale",
    metadata,
    Column("基金代码", String, primary_key=True),
    Column("净资产规模", Float),
    Column("份额规模", Float),
    Column("updated_at", Float),
)

fund_profile = Table(
    "fund_profile",
    metadata,
    Column("基金代码", String, primary_key=True),
    Column("发行日期", String),
    Column("成立日期", String),
    Column("基金管理人", String),
    Column("基金托管人", String),
    Column("基金经理", String),
    Column("业绩比较基准", String),
    Column("跟踪标的", String),
    Column("跟踪方式", String),
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

fund_nav = Table(
    "fund_nav",
    metadata,
    Column("基金代码", String, primary_key=True),
    Column("日期", String),
    Column("单位净值", Float),
    Column("累计净值", Float),
    Column("日增长率", Float),
    Column("数据来源", String),
    Column("updated_at", Float),
)

CATALOG_TTL = 86400  # 基金名录默认 TTL
FEE_TTL = 7776000  # 费率缓存 90 天
SCALE_TTL = 86400  # 规模缓存 24 小时
NAV_TTL = 86400  # 净值缓存 24 小时


# ── 初始化 ──


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    metadata.create_all(engine)
    # 迁移: fund_fee → fund_scale 拆分（旧库）
    try:
        with engine.connect() as conn:
            cols = [row[1] for row in conn.execute(
                text("PRAGMA table_info(fund_fee)")
            ).fetchall()]
            if "净资产规模" in cols:
                conn.execute(text("""
                    INSERT OR IGNORE INTO fund_scale (基金代码, 净资产规模, updated_at)
                    SELECT 基金代码, 净资产规模, updated_at FROM fund_fee
                    WHERE 净资产规模 IS NOT NULL
                """))
                conn.execute(text("ALTER TABLE fund_fee DROP COLUMN 净资产规模"))
    except Exception:
        pass
    # 迁移: fund_scale 追加份额规模列
    try:
        with engine.connect() as conn:
            cols = [row[1] for row in conn.execute(
                text("PRAGMA table_info(fund_scale)")
            ).fetchall()]
            if "份额规模" not in cols:
                conn.execute(text("ALTER TABLE fund_scale ADD COLUMN 份额规模 Float"))
    except Exception:
        pass
    # 迁移: fund_profile 追加跟踪方式列
    try:
        with engine.connect() as conn:
            cols = [row[1] for row in conn.execute(
                text("PRAGMA table_info(fund_profile)")
            ).fetchall()]
            if "跟踪方式" not in cols:
                conn.execute(text("ALTER TABLE fund_profile ADD COLUMN 跟踪方式 String"))
    except Exception:
        pass
    # 迁移: fund_nav 建表（新表，create_all 已处理，仅添加索引确保性能）
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_fund_nav_code ON fund_nav(基金代码)"))
    except Exception:
        pass
    # 迁移: 清理已废弃的 funds 表元数据
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM funds_meta WHERE key='funds'"))
    except Exception:
        pass


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
                "销售服务费": r[4],
                "起购金额": r[5],
                "综合费率": r[6],
            }
    return result


def save_fund_fee(code, purchase, mgmt, cust, sales_service, min_purchase, total):
    """写入单只基金费率缓存。"""
    with engine.begin() as conn:
        conn.execute(
            fund_fee.insert().prefix_with("OR REPLACE"),
            {"基金代码": code,
             "申购费": purchase, "管理费": mgmt, "托管费": cust,
             "销售服务费": sales_service, "起购金额": min_purchase,
             "综合费率": total,
             "updated_at": time.time()},
        )


def clear_fund_fees():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM fund_fee"))


# ── 基金规模缓存 ──


def load_fund_scale(codes):
    """从 fund_scale 表批量加载规模，返回 {code: {"净资产规模": value, "份额规模": value}}"""
    if not codes:
        return {}
    result = {}
    with engine.connect() as conn:
        stmt = fund_scale.select().where(fund_scale.c.基金代码.in_(codes))
        rows = conn.execute(stmt).fetchall()
        for r in rows:
            result[r[0]] = {"净资产规模": r[1], "份额规模": r[2]}
    return result


def save_fund_scale(code, scale, shares=None):
    """写入单只基金规模数据。scale 为净资产规模（亿元），shares 为份额规模（亿份）。"""
    with engine.begin() as conn:
        conn.execute(
            fund_scale.insert().prefix_with("OR REPLACE"),
            {"基金代码": code, "净资产规模": scale,
             "份额规模": shares, "updated_at": time.time()},
        )


def clear_fund_scale():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM fund_scale"))


# ── 基金净值缓存 ──


def load_fund_nav():
    """返回 fund_nav 全表 DataFrame 或 None"""
    try:
        return pd.read_sql(text("SELECT * FROM fund_nav"), engine)
    except Exception:
        return None


def save_fund_nav(df):
    """替换写入 fund_nav 表"""
    df.to_sql("fund_nav", engine, if_exists="replace", index=False)
    with engine.begin() as conn:
        conn.execute(
            funds_meta.insert().prefix_with("OR REPLACE"),
            {"key": "fund_nav", "value": "ok", "updated_at": time.time()},
        )


def is_fund_nav_fresh(ttl=None):
    """检查 fund_nav 缓存是否仍在 TTL 内"""
    if ttl is None:
        ttl = NAV_TTL
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT updated_at FROM funds_meta WHERE key='fund_nav'")
            ).fetchone()
            if row and row[0]:
                return time.time() - row[0] < ttl
    except Exception:
        pass
    return False


def clear_fund_nav():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM fund_nav"))
        conn.execute(text("DELETE FROM funds_meta WHERE key='fund_nav'"))


def load_index_fund_nav():
    """JOIN fund_nav + fund_catalog + fund_profile 返回指数基金净值+跟踪方式。"""
    try:
        with engine.connect() as conn:
            return pd.read_sql(text("""
                SELECT
                    nav.基金代码,
                    cat.基金简称 AS 基金名称,
                    nav.单位净值,
                    nav.日期,
                    nav.日增长率,
                    COALESCE(pf.跟踪方式,
                        CASE
                            WHEN cat.基金简称 LIKE '%增强%' OR cat.基金简称 LIKE '%量化%' OR cat.基金简称 LIKE '%指增%'
                            THEN '增强指数型' ELSE '被动指数型'
                        END
                    ) AS 跟踪方式,
                    pf.跟踪标的
                FROM fund_nav nav
                JOIN fund_catalog cat ON nav.基金代码 = cat.基金代码
                LEFT JOIN fund_profile pf ON nav.基金代码 = pf.基金代码
                WHERE cat.基金类型 LIKE '指数型-%'
            """), conn)
    except Exception:
        return None


# ── 基金基本信息缓存 ──


def load_fund_profile(codes):
    """从 fund_profile 表批量加载基金基本信息，返回 {code: {...}}"""
    if not codes:
        return {}
    result = {}
    with engine.connect() as conn:
        stmt = fund_profile.select().where(fund_profile.c.基金代码.in_(codes))
        rows = conn.execute(stmt).fetchall()
        for r in rows:
            result[r[0]] = {
                "发行日期": r[1],
                "成立日期": r[2],
                "基金管理人": r[3],
                "基金托管人": r[4],
                "基金经理": r[5],
                "业绩比较基准": r[6],
                "跟踪标的": r[7],
                "跟踪方式": r[8],
            }
    return result


def save_fund_profile(code, issue_date, establish_date, mgr, custodian, fund_mgr, benchmark, track_index, track_method=None):
    """写入单只基金基本信息。"""
    with engine.begin() as conn:
        conn.execute(
            fund_profile.insert().prefix_with("OR REPLACE"),
            {"基金代码": code, "发行日期": issue_date,
             "成立日期": establish_date, "基金管理人": mgr,
             "基金托管人": custodian, "基金经理": fund_mgr,
             "业绩比较基准": benchmark, "跟踪标的": track_index,
             "跟踪方式": track_method,
             "updated_at": time.time()},
        )


def batch_update_tracking_method(method_map):
    """批量更新 fund_profile.跟踪方式，method_map = {code: '被动指数型'|'增强指数型'}"""
    with engine.begin() as conn:
        for code, method in method_map.items():
            conn.execute(
                text("UPDATE fund_profile SET 跟踪方式 = :method WHERE 基金代码 = :code"),
                {"method": method, "code": code},
            )


def clear_fund_profile():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM fund_profile"))


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
        conn.execute(text("DELETE FROM funds_meta WHERE key LIKE 'fund%' OR key LIKE 'index%'"))
        conn.execute(text("DELETE FROM fund_fee"))
        conn.execute(text("DELETE FROM fund_scale"))
        conn.execute(text("DELETE FROM fund_nav"))
        conn.execute(text("DELETE FROM fund_profile"))
