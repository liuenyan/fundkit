"""
SQLite 数据库管理（SQLAlchemy Core）
统一数据库: data/fundkit.db
"""

import os
import time
from datetime import date, datetime, timedelta
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

from backend.logger import get_logger

logger = get_logger(__name__)

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
    Column("index_code", String, nullable=False),
    Column("metric", String, nullable=False),
    Column("date", String, nullable=False),
    Column("value", Float),
    PrimaryKeyConstraint("index_code", "metric", "date"),
)

cache_meta = Table(
    "cache_meta",
    metadata,
    Column("index_code", String, nullable=False),
    Column("metric", String, nullable=False),
    Column("last_updated", String, nullable=False),
    Column("source", String),
    PrimaryKeyConstraint("index_code", "metric"),
)

funds_meta = Table(
    "funds_meta",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", String),
    Column("updated_at", Float),
)

index_name_map = Table(
    "index_name_map",
    metadata,
    Column("display_name", String, nullable=False),  # 归一化名称
    Column("short_name", String),  # 指数简称（原始）
    Column("index_code", String, nullable=False),  # 数字代码
    Column("market_prefix", String),  # "sh"/"sz"/"csi" 用于 daily_em 后备
    Column("source", String),  # "csindex"/"daily_em"/"manual"
    Column("index_type", String, nullable=False),  # "equity"/"bond"/"commodity"/"overseas"
    PrimaryKeyConstraint("display_name"),
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

fund_nav_history = Table(
    "fund_nav_history",
    metadata,
    Column("基金代码", String, nullable=False),
    Column("日期", String, nullable=False),
    Column("单位净值", Float),
    Column("累计净值", Float),
    Column("日增长率", Float),
    Column("updated_at", Float),
    PrimaryKeyConstraint("基金代码", "日期"),
)

fund_dividend = Table(
    "fund_dividend",
    metadata,
    Column("基金代码", String, nullable=False),
    Column("除息日", String, nullable=False),
    Column("每份分红", Float),
    Column("updated_at", Float),
    PrimaryKeyConstraint("基金代码", "除息日"),
)

CATALOG_TTL = 86400  # 基金名录默认 TTL
FEE_TTL = 7776000  # 费率缓存 90 天
SCALE_TTL = 86400  # 规模缓存 24 小时
NAV_TTL = 86400  # 净值缓存 24 小时
DIVIDEND_TTL = 7776000  # 分红缓存 90 天


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
            logger.warning("缓存未就绪: %s", self.meta_key or self.table.name)
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
                "申购费": r[1],
                "管理费": r[2],
                "托管费": r[3],
                "销售服务费": r[4],
                "起购金额": r[5],
                "综合费率": r[6],
            }
            for code, r in rows.items()
        }

    def save(
        self,
        code: str,
        purchase: float | None,
        mgmt: float | None,
        cust: float | None,
        sales_service: float | None,
        min_purchase: str | None,
        total: float | None,
    ) -> None:
        with engine.begin() as conn:
            conn.execute(
                self.table.insert().prefix_with("OR REPLACE"),
                {
                    "基金代码": code,
                    "申购费": purchase,
                    "管理费": mgmt,
                    "托管费": cust,
                    "销售服务费": sales_service,
                    "起购金额": min_purchase,
                    "综合费率": total,
                    "updated_at": time.time(),
                },
            )

    def cached_count(self) -> int:
        try:
            with engine.connect() as conn:
                row = conn.execute(text("SELECT COUNT(*) FROM fund_fee")).fetchone()
                return row[0] if row else 0
        except Exception:
            logger.warning("查 fund_fee 数量失败")
            return 0


class FundScaleTable(_DictTable):
    table = fund_scale
    meta_key = None

    def load(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        rows = self._load_rows(codes)
        return {code: {"净资产规模": r[1], "份额规模": r[2]} for code, r in rows.items()}

    def save(self, code: str, scale: float | None, shares: float | None = None) -> None:
        with engine.begin() as conn:
            conn.execute(
                self.table.insert().prefix_with("OR REPLACE"),
                {"基金代码": code, "净资产规模": scale, "份额规模": shares, "updated_at": time.time()},
            )


class FundProfileTable(_DictTable):
    table = fund_profile
    meta_key = None

    def load(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        rows = self._load_rows(codes)
        return {
            code: {
                "发行日期": r[1],
                "成立日期": r[2],
                "基金管理人": r[3],
                "基金托管人": r[4],
                "基金经理": r[5],
                "业绩比较基准": r[6],
                "跟踪标的": r[7],
                "跟踪方式": r[8],
            }
            for code, r in rows.items()
        }

    def save(
        self,
        code: str,
        issue_date: str | None,
        establish_date: str | None,
        mgr: str | None,
        custodian: str | None,
        fund_mgr: str | None,
        benchmark: str | None,
        track_index: str | None,
        track_method: str | None = None,
    ) -> None:
        with engine.begin() as conn:
            conn.execute(
                self.table.insert().prefix_with("OR REPLACE"),
                {
                    "基金代码": code,
                    "发行日期": issue_date,
                    "成立日期": establish_date,
                    "基金管理人": mgr,
                    "基金托管人": custodian,
                    "基金经理": fund_mgr,
                    "业绩比较基准": benchmark,
                    "跟踪标的": track_index,
                    "跟踪方式": track_method,
                    "updated_at": time.time(),
                },
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
            logger.error("批量加载 %s 失败", self.table.name, exc_info=True)
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


def _last_available_data_day(end_date: str, now: datetime | None = None) -> str:
    """返回 end_date 当天已知的最新有净值数据的交易日。

    规则：
      1. 周末 → 本周五
      2. 今天且未到 22:00 → 上一个交易日
      3. 其他情况 → end_date 本身
    """
    if now is None:
        now = datetime.now()
    end = datetime.strptime(end_date, "%Y-%m-%d")

    # 周末 → 本周五
    if end.weekday() >= 5:
        days_after_friday = end.weekday() - 4
        return (end - timedelta(days=days_after_friday)).strftime("%Y-%m-%d")

    # 今天且未到 22:00 → 上一个交易日
    if end.date() == now.date() and now.hour < 22:
        prev = end - timedelta(days=1)
        while prev.weekday() >= 5:
            prev -= timedelta(days=1)
        return prev.strftime("%Y-%m-%d")

    return end_date


class FundNavHistoryTable:
    """历史净值缓存表——每个基金独立的一整段历史 OR REPLACE 积累"""

    table = fund_nav_history

    def is_cached(self, fund_code: str, end_date: str, _now: datetime | None = None) -> bool:
        """检查本地缓存是否覆盖 end_date 已知的最新交易日"""
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT MAX(日期) FROM fund_nav_history WHERE 基金代码=:code"),
                    {"code": fund_code},
                ).fetchone()
                if row is None or row[0] is None:
                    return False
                expected = _last_available_data_day(end_date, now=_now)
                return row[0] >= expected
        except Exception:
            logger.warning("净值缓存过期检查失败: %s", fund_code)
            return False

    def load(self, fund_code: str, start_date: str, end_date: str) -> pd.DataFrame | None:
        """读取缓存中指定日期范围的净值数据"""
        try:
            df = pd.read_sql_query(
                "SELECT 日期, 单位净值, 累计净值, 日增长率 FROM fund_nav_history "
                "WHERE 基金代码=? AND 日期 BETWEEN ? AND ? ORDER BY 日期",
                engine,
                params=(fund_code, start_date, end_date),
            )
            if df.empty:
                return None
            df = df.rename(columns={"日期": "净值日期"})
            return df
        except Exception:
            logger.error("加载净值失败: %s", fund_code, exc_info=True)
            return None

    def save(self, fund_code: str, df: pd.DataFrame) -> None:
        """保存全量历史净值到缓存（OR REPLACE）"""
        with engine.begin() as conn:
            data = [
                {
                    "基金代码": fund_code,
                    "日期": str(row["净值日期"]),
                    "单位净值": float(row["单位净值"]),
                    "累计净值": float(row["累计净值"]),
                    "日增长率": float(row["日增长率"]) if pd.notna(row["日增长率"]) else None,
                    "updated_at": time.time(),
                }
                for _, row in df.iterrows()
            ]
            if data:
                conn.execute(
                    self.table.insert().prefix_with("OR REPLACE"),
                    data,
                )


class FundDividendTable:
    """分红缓存表——按基金代码存取"""

    table = fund_dividend

    def load(self, fund_code: str, ttl: float | None = None) -> pd.DataFrame | None:
        try:
            ttl = ttl or DIVIDEND_TTL
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT MAX(updated_at) FROM fund_dividend WHERE 基金代码=:code"),
                    {"code": fund_code},
                ).fetchone()
                if row and row[0] is not None and time.time() - row[0] < ttl:
                    df = pd.read_sql_query(
                        "SELECT 除息日, 每份分红 FROM fund_dividend WHERE 基金代码=? ORDER BY 除息日",
                        engine,
                        params=(fund_code,),
                    )
                    if not df.empty:
                        return df
        except Exception:
            logger.warning("分红数据读取失败: %s", fund_code)
        return None

    def save(self, fund_code: str, df: pd.DataFrame) -> None:
        if df.empty:
            return
        with engine.begin() as conn:
            data = [
                {
                    "基金代码": fund_code,
                    "除息日": str(row["除息日"]),
                    "每份分红": float(row["每份分红"]),
                    "updated_at": time.time(),
                }
                for _, row in df.iterrows()
            ]
            if data:
                conn.execute(
                    self.table.insert().prefix_with("OR REPLACE"),
                    data,
                )


# ── 单例实例 ──
fund_fee = FundFeeTable()
fund_scale = FundScaleTable()
fund_profile = FundProfileTable()
fund_nav = FundNavTable()
fund_catalog = FundCatalogTable()
fund_nav_history = FundNavHistoryTable()
fund_dividend = FundDividendTable()


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


def load_series(index_code: str, metric: str) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT date, value FROM index_series WHERE index_code=? AND metric=? ORDER BY date",
        engine,
        params=(index_code, metric),
    )


def upsert_series(index_code: str, metric: str, df: pd.DataFrame) -> None:
    with engine.begin() as conn:
        data = [
            {"index_code": index_code, "metric": metric, "date": str(row["date"]), "value": float(row["value"])}
            for _, row in df.iterrows()
        ]
        conn.execute(
            index_series.insert().prefix_with("OR REPLACE"),
            data,
        )


def get_series_last_date(index_code: str, metric: str) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT MAX(date) FROM index_series WHERE index_code=:index_code AND metric=:metric"),
            {"index_code": index_code, "metric": metric},
        ).fetchone()
        return row[0] if row and row[0] else None


def get_cache_meta(index_code: str, metric: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT * FROM cache_meta WHERE index_code=:index_code AND metric=:metric"),
            {"index_code": index_code, "metric": metric},
        ).fetchone()


def set_cache_meta(index_code: str, metric: str, source: str) -> None:
    today = date.today().isoformat()
    with engine.begin() as conn:
        conn.execute(
            cache_meta.insert().prefix_with("OR REPLACE"),
            {"index_code": index_code, "metric": metric, "last_updated": today, "source": source},
        )


def is_series_fresh(index_code: str, metric: str, max_age_days: int = 2) -> bool:
    last = get_series_last_date(index_code, metric)
    if last is not None:
        last_date = datetime.strptime(last, "%Y-%m-%d").date()
        if (datetime.now().date() - last_date).days <= max_age_days:
            return True
    meta = get_cache_meta(index_code, metric)
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
        logger.error("指数基金净值查询失败", exc_info=True)
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
        logger.error("养老基金查询失败", exc_info=True)
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
