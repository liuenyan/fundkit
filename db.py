"""
SQLite 数据库管理（SQLAlchemy Core）
统一数据库: data/fundkit.db
"""

import os
import time
from datetime import date, datetime
from typing import Any

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
def _set_wal(dbapi_connection: Any, _connection_record: Any) -> None:
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


# ── OOP 表访问层 ──


class _FundTable:
    """基金表基类——封装 is_fresh / set_fresh / clear"""

    table: Table
    meta_key: str | None = None
    default_ttl: float = 86400

    def _get_update_time(self) -> float | None:
        if not self.meta_key:
            return None
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT updated_at FROM funds_meta WHERE key=:key"),
                {"key": self.meta_key},
            ).fetchone()
            return row[0] if row else None

    def is_fresh(self, ttl: float | None = None) -> bool:
        if not self.meta_key:
            return False
        ttl = ttl or self.default_ttl
        try:
            ts = self._get_update_time()
            if ts is not None:
                return time.time() - ts < ttl
        except Exception:
            pass
        return False

    def set_fresh(self) -> None:
        if not self.meta_key:
            return
        with engine.begin() as conn:
            conn.execute(
                funds_meta.insert().prefix_with("OR REPLACE"),
                {"key": self.meta_key, "value": "ok", "updated_at": time.time()},
            )

    def clear(self) -> None:
        with engine.begin() as conn:
            conn.execute(text(f"DELETE FROM {self.table.name}"))
            if self.meta_key:
                conn.execute(text("DELETE FROM funds_meta WHERE key=:key"), {"key": self.meta_key})


class _DictTable(_FundTable):
    """加载为 {code: dict} 的表 (fund_fee / fund_scale / fund_profile)"""

    def _load_rows(self, codes: list[str]) -> dict[str, Any]:
        if not codes:
            return {}
        with engine.connect() as conn:
            stmt = self.table.select().where(self.table.c.基金代码.in_(codes))
            return {r[0]: r for r in conn.execute(stmt).fetchall()}


class FundFeeTable(_DictTable):
    table = fund_fee
    meta_key = "fund_fee"
    default_ttl = FEE_TTL

    def load(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        rows = self._load_rows(codes)
        return {
            code: {
                "申购费": r[1], "管理费": r[2], "托管费": r[3],
                "销售服务费": r[4], "起购金额": r[5], "综合费率": r[6],
            }
            for code, r in rows.items()
        }

    def save(self, code: str, purchase: float | None, mgmt: float | None, cust: float | None,
             sales_service: float | None, min_purchase: str | None, total: float | None) -> None:
        with engine.begin() as conn:
            conn.execute(
                self.table.insert().prefix_with("OR REPLACE"),
                {"基金代码": code, "申购费": purchase, "管理费": mgmt,
                 "托管费": cust, "销售服务费": sales_service,
                 "起购金额": min_purchase, "综合费率": total,
                 "updated_at": time.time()},
            )

    def cached_count(self) -> int:
        try:
            with engine.connect() as conn:
                row = conn.execute(text("SELECT COUNT(*) FROM fund_fee")).fetchone()
                return row[0] if row else 0
        except Exception:
            return 0


class FundScaleTable(_DictTable):
    table = fund_scale
    meta_key = None

    def load(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        rows = self._load_rows(codes)
        return {
            code: {"净资产规模": r[1], "份额规模": r[2]}
            for code, r in rows.items()
        }

    def save(self, code: str, scale: float | None, shares: float | None = None) -> None:
        with engine.begin() as conn:
            conn.execute(
                self.table.insert().prefix_with("OR REPLACE"),
                {"基金代码": code, "净资产规模": scale,
                 "份额规模": shares, "updated_at": time.time()},
            )


class FundProfileTable(_DictTable):
    table = fund_profile
    meta_key = None

    def load(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        rows = self._load_rows(codes)
        return {
            code: {
                "发行日期": r[1], "成立日期": r[2], "基金管理人": r[3],
                "基金托管人": r[4], "基金经理": r[5], "业绩比较基准": r[6],
                "跟踪标的": r[7], "跟踪方式": r[8],
            }
            for code, r in rows.items()
        }

    def save(self, code: str, issue_date: str | None, establish_date: str | None,
             mgr: str | None, custodian: str | None, fund_mgr: str | None,
             benchmark: str | None, track_index: str | None,
             track_method: str | None = None) -> None:
        with engine.begin() as conn:
            conn.execute(
                self.table.insert().prefix_with("OR REPLACE"),
                {"基金代码": code, "发行日期": issue_date,
                 "成立日期": establish_date, "基金管理人": mgr,
                 "基金托管人": custodian, "基金经理": fund_mgr,
                 "业绩比较基准": benchmark, "跟踪标的": track_index,
                 "跟踪方式": track_method, "updated_at": time.time()},
            )

    def batch_update_tracking_method(self, method_map: dict[str, str]) -> None:
        with engine.begin() as conn:
            for code, method in method_map.items():
                conn.execute(
                    text("UPDATE fund_profile SET 跟踪方式 = :method WHERE 基金代码 = :code"),
                    {"method": method, "code": code},
                )


class _BulkTable(_FundTable):
    """全表替换的表 (fund_nav / fund_catalog)"""

    def load(self) -> pd.DataFrame | None:
        try:
            return pd.read_sql(text(f"SELECT * FROM {self.table.name}"), engine)
        except Exception:
            return None

    def save(self, df: pd.DataFrame) -> None:
        with engine.begin() as conn:
            conn.execute(text(f"DELETE FROM {self.table.name}"))
        df.to_sql(self.table.name, engine, if_exists="append", index=False)
        self.set_fresh()


class FundNavTable(_BulkTable):
    table = fund_nav
    meta_key = "fund_nav"
    default_ttl = NAV_TTL


class FundCatalogTable(_BulkTable):
    table = fund_catalog
    meta_key = "fund_catalog"
    default_ttl = CATALOG_TTL


# ── 单例实例 ──
fund_fee = FundFeeTable()
fund_scale = FundScaleTable()
fund_profile = FundProfileTable()
fund_nav = FundNavTable()
fund_catalog = FundCatalogTable()


# ── 初始化 ──

_DB_INITIALIZED = False


def init_db() -> None:
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    metadata.create_all(engine)
    _DB_INITIALIZED = True


# ── 估值序列缓存 ──


def load_series(name: str, metric: str) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT date, value FROM index_series WHERE name=? AND metric=? ORDER BY date",
        engine,
        params=(name, metric),
    )


def upsert_series(name: str, metric: str, df: pd.DataFrame) -> None:
    with engine.begin() as conn:
        data = [
            {"name": name, "metric": metric, "date": str(row["date"]), "value": float(row["value"])}
            for _, row in df.iterrows()
        ]
        conn.execute(
            index_series.insert().prefix_with("OR REPLACE"),
            data,
        )


def get_series_last_date(name: str, metric: str) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT MAX(date) FROM index_series WHERE name=:name AND metric=:metric"),
            {"name": name, "metric": metric},
        ).fetchone()
        return row[0] if row and row[0] else None


def get_cache_meta(name: str, metric: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT * FROM cache_meta WHERE name=:name AND metric=:metric"),
            {"name": name, "metric": metric},
        ).fetchone()


def set_cache_meta(name: str, metric: str, source: str) -> None:
    today = date.today().isoformat()
    with engine.begin() as conn:
        conn.execute(
            cache_meta.insert().prefix_with("OR REPLACE"),
            {"name": name, "metric": metric, "last_updated": today, "source": source},
        )


def is_series_fresh(name: str, metric: str, max_age_days: int = 2) -> bool:
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


# ── 复杂 JOIN 查询 ──


def load_index_fund_nav() -> pd.DataFrame | None:
    """JOIN fund_nav + fund_catalog + fund_profile + fund_fee + fund_scale
    返回指数基金净值+费率+规模+跟踪方式——单次查询，无需后续 enrich_fee_scale。"""
    try:
        with engine.connect() as conn:
            return pd.read_sql(
                text("""
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
                    pf.跟踪标的,
                    fee.申购费,
                    fee.管理费,
                    fee.托管费,
                    fee.销售服务费,
                    fee.综合费率,
                    fee.起购金额,
                    scale.净资产规模 AS 基金规模
                FROM fund_nav nav
                JOIN fund_catalog cat ON nav.基金代码 = cat.基金代码
                LEFT JOIN fund_profile pf ON nav.基金代码 = pf.基金代码
                LEFT JOIN fund_fee fee ON nav.基金代码 = fee.基金代码
                LEFT JOIN fund_scale scale ON nav.基金代码 = scale.基金代码
                WHERE cat.基金类型 LIKE '指数型-%'
            """),
                conn,
            )
    except Exception:
        return None


def load_pension_funds() -> pd.DataFrame | None:
    """JOIN fund_catalog + fund_nav + fund_fee + fund_scale
    返回 Y 份额基金净值+费率+规模——单次查询，无需后续 enrich_fee_scale。"""
    try:
        with engine.connect() as conn:
            return pd.read_sql(
                text("""
                SELECT
                    cat.基金代码,
                    cat.基金简称 AS 基金名称,
                    cat.基金类型,
                    nav.单位净值,
                    nav.累计净值,
                    nav.日增长率,
                    nav.日期 AS 净值日期,
                    fee.申购费,
                    fee.管理费,
                    fee.托管费,
                    fee.销售服务费,
                    fee.综合费率,
                    fee.起购金额,
                    scale.净资产规模 AS 基金规模
                FROM fund_catalog cat
                LEFT JOIN fund_nav nav ON cat.基金代码 = nav.基金代码
                LEFT JOIN fund_fee fee ON cat.基金代码 = fee.基金代码
                LEFT JOIN fund_scale scale ON cat.基金代码 = scale.基金代码
                WHERE cat.基金简称 LIKE '%Y' OR cat.基金简称 LIKE '%Y类%'
            """),
                conn,
            )
    except Exception:
        return None


# ── 全局操作 ──


def clear_index_cache() -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM index_series"))
        conn.execute(text("DELETE FROM cache_meta"))


def clear_fund_cache() -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM funds_meta WHERE key LIKE 'fund%'"))
        conn.execute(text("DELETE FROM fund_fee"))
        conn.execute(text("DELETE FROM fund_scale"))
        conn.execute(text("DELETE FROM fund_nav"))
        conn.execute(text("DELETE FROM fund_profile"))


def clear_all() -> None:
    clear_index_cache()
    clear_fund_cache()
