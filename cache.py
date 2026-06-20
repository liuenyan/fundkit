"""
SQLite 缓存：估值数据持久化，避免重复请求 AKShare
"""

import os
import sqlite3
from datetime import datetime, date

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "fundkit.db")


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _conn():
    _ensure_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _init_tables():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS index_series (
                name    TEXT NOT NULL,
                metric  TEXT NOT NULL,
                date    TEXT NOT NULL,
                value   REAL,
                PRIMARY KEY (name, metric, date)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache_meta (
                name          TEXT NOT NULL,
                metric        TEXT NOT NULL,
                last_updated  TEXT NOT NULL,
                source        TEXT,
                PRIMARY KEY (name, metric)
            )
        """)


def _get_last_date(name, metric):
    with _conn() as conn:
        cur = conn.execute(
            "SELECT MAX(date) FROM index_series WHERE name=? AND metric=?",
            (name, metric),
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def _get_all_series(name, metric):
    with _conn() as conn:
        return pd.read_sql_query(
            "SELECT date, value FROM index_series"
            " WHERE name=? AND metric=? ORDER BY date",
            conn, params=(name, metric),
        )


def _upsert_series(name, metric, df):
    with _conn() as conn:
        for _, row in df.iterrows():
            conn.execute(
                "INSERT OR IGNORE INTO index_series (name, metric, date, value)"
                " VALUES (?, ?, ?, ?)",
                (name, metric, str(row["date"]), float(row["value"])),
            )


def _set_meta(name, metric, source):
    today = date.today().isoformat()
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cache_meta (name, metric, last_updated, source)"
            " VALUES (?, ?, ?, ?)",
            (name, metric, today, source),
        )


def _is_fresh(name, metric, max_age_days=2):
    last = _get_last_date(name, metric)
    if last is not None:
        last_date = datetime.strptime(last, "%Y-%m-%d").date()
        if (datetime.now().date() - last_date).days <= max_age_days:
            return True
    # 即使上次失败也记入 meta，避免每天反复重试
    with _conn() as conn:
        cur = conn.execute(
            "SELECT last_updated FROM cache_meta WHERE name=? AND metric=?",
            (name, metric),
        )
        row = cur.fetchone()
        if row and row[0]:
            meta_date = datetime.strptime(row[0], "%Y-%m-%d").date()
            if (datetime.now().date() - meta_date).days <= 1:
                return True
    return False


# ── Public API ──


def get_or_update_series(name, metric, source, fetch_fn):
    """
    返回 (DataFrame, 是否命中缓存)。

    如果缓存新鲜则直接返回缓存；否则调用 fetch_fn() 获取全量数据，
    新老合并后写入缓存再返回。
    """
    _init_tables()

    if _is_fresh(name, metric):
        df = _get_all_series(name, metric)
        return df, True

    try:
        df_raw = fetch_fn()
    except Exception:
        df_raw = None
    if df_raw is None or df_raw.empty:
        _set_meta(name, metric, source + ":failed")
        cached = _get_all_series(name, metric)
        return cached, True  # 回退缓存

    _upsert_series(name, metric, df_raw)
    _set_meta(name, metric, source)

    df = _get_all_series(name, metric)
    return df, False


def clear_cache():
    with _conn() as conn:
        conn.execute("DELETE FROM index_series")
        conn.execute("DELETE FROM cache_meta")
