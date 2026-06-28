"""
批量预采集基金数据（费率 + 净资产规模 + 净值），写入 DB 缓存。
TTL: 费率 90 天 / 净值 24 小时

数据源:
  1. fund_purchase_em() — 批量获取 申购费 + 起购金额（1 次 API 调用）
  2. fund_overview_em() — 逐只获取 管理费/托管费/销售服务费/净资产规模（ThreadPoolExecutor 并发）
  3. fund_open_fund_daily_em() — 全市场开放基金净值（1 次 API 调用）
  4. fund_etf_fund_daily_em() — 场内 ETF 净值（1 次 API 调用）

用法:
  ./venv/bin/python collect_fund_data.py              # 采集费率+规模（默认）
  ./venv/bin/python collect_fund_data.py --nav         # 采集净值
  ./venv/bin/python collect_fund_data.py --force       # 强制全量重采费率
  ./venv/bin/python collect_fund_data.py --nav --force # 强制重采净值
  ./venv/bin/python collect_fund_data.py --codes 000001,000002  # 指定基金
"""

import argparse
import re
import sys
import time

import akshare as ak
import pandas as pd


import db
from backend.fund_data import batch_fetch_overview, fetch_purchase_data, save_overview_result



def collect_fund_data(max_workers: int = 10, force: bool = False, codes: list[str] | None = None) -> None:
    db.init_db()

    # ── TTL 检查 ──
    if not force and not codes and db.fund_fee.is_fresh():
        cnt = db.fund_fee.cached_count()
        print(f"费率缓存有效，已缓存 {cnt} 只基金，跳过。使用 --force 强制重采。")
        return

    # ── 获取所有基金代码 + 申购费 ──
    print("正在获取基金申购费数据（fund_purchase_em）…")
    purchase_data = fetch_purchase_data(codes)
    if not purchase_data:
        print("获取 fund_purchase_em 失败")
        sys.exit(1)

    all_codes = list(purchase_data.keys())
    total = len(all_codes)
    print(f"共 {total} 只基金\n")

    # ── Step 1: 保存申购费 + 起购金额 ──
    print("Step 1/2 — 保存申购费 + 起购金额…")
    for code, (purchase, min_purchase) in purchase_data.items():
        db.fund_fee.save(code, purchase, None, None, None, min_purchase, None)
    print(f"  → 已保存 {len(purchase_data)} 只基金申购费数据\n")

    # ── Step 2: 并发获取管理费/托管费/销售服务费 ──
    print(f"Step 2/2 — 并发获取管理费/托管费/销售服务费 ({max_workers} workers)…")
    t0 = time.time()
    success = 0
    failed = 0

    load_cached = db.fund_fee.load(all_codes)

    def _persist(code: str, result: dict | None) -> None:
        nonlocal success, failed
        if result is None:
            failed += 1
            return
        cached = load_cached.get(code, {})
        save_overview_result(code, result, cached.get("申购费"), cached.get("起购金额"))
        success += 1

    for done, total in batch_fetch_overview(all_codes, _persist, max_workers):
        elapsed = time.time() - t0
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        print(
            f"\r  [{done}/{total}] 成功 {success}, 失败 {failed}, 速率 {rate:.1f} 只/秒, 预计剩余 {eta:.0f}s",
            end="", flush=True,
        )

    print()
    elapsed = time.time() - t0
    print(f"\n采集完成！耗时 {elapsed:.0f}s")
    print(f"  成功: {success}  失败: {failed}")

    # ── Step 3: 获取指数基金跟踪方式 ──
    collect_tracking_method()

    # ── 标记缓存新鲜 ──
    if not codes:
        db.fund_fee.set_fresh()
        print("  费率缓存 TTL 已更新")


def collect_tracking_method() -> None:
    """
    从 fund_info_index_em 获取指数基金的跟踪方式（被动指数型 / 增强指数型），
    写入 fund_profile.跟踪方式。
    """
    print("\nStep 3 — 获取指数基金跟踪方式…")
    db.init_db()
    try:
        passive = ak.fund_info_index_em(symbol="全部", indicator="被动指数型")
        enhanced = ak.fund_info_index_em(symbol="全部", indicator="增强指数型")
    except Exception as e:
        print(f"  fund_info_index_em 调用失败: {e}")
        return

    method_map = {}
    for code in passive["基金代码"]:
        method_map[code] = "被动指数型"
    for code in enhanced["基金代码"]:
        method_map[code] = "增强指数型"

    if not method_map:
        print("  未获取到跟踪方式数据，跳过")
        return

    db.fund_profile.batch_update_tracking_method(method_map)
    print(f"  → 已写入 {len(method_map)} 只基金跟踪方式（被动 {len(passive)} / 增强 {len(enhanced)}）")

    # ── 名称启发式兜底（覆盖场内ETF/海外/固收等 fund_info_index_em 未覆盖的） ──
    print("\nStep 4 — 名称启发式兜底跟踪方式…")
    with db.engine.begin() as conn:
        # 先标记增强：名称含 增强 / 量化 / 指增
        result = conn.execute(
            db.text("""
            UPDATE fund_profile SET 跟踪方式 = '增强指数型'
            WHERE (跟踪方式 IS NULL OR 跟踪方式 = '')
              AND 基金代码 IN (
                SELECT 基金代码 FROM fund_catalog
                WHERE 基金类型 LIKE '指数型-%'
                  AND (基金简称 LIKE '%增强%' OR 基金简称 LIKE '%量化%' OR 基金简称 LIKE '%指增%')
              )
        """)
        )
        enhanced_cnt = result.rowcount

        # 剩余全部标记为被动
        result = conn.execute(
            db.text("""
            UPDATE fund_profile SET 跟踪方式 = '被动指数型'
            WHERE (跟踪方式 IS NULL OR 跟踪方式 = '')
              AND 基金代码 IN (
                SELECT 基金代码 FROM fund_catalog
                WHERE 基金类型 LIKE '指数型-%'
              )
        """)
        )
        passive_cnt = result.rowcount

    print(f"  → 名称启发式完成：增强 {enhanced_cnt}, 被动 {passive_cnt}")


def _parse_daily_pct_series(s: pd.Series) -> pd.Series:
    """向量化：归一化日增长率"""
    s = s.astype(str).str.strip()
    s = s.replace(["", "nan", "<NA>", "None", "—", "---"], None)
    s = s.str.replace("%", "", regex=False).str.replace(" ", "", regex=False)
    return pd.to_numeric(s, errors="coerce")


def _to_float_series(s: pd.Series) -> pd.Series:
    """向量化：转浮点"""
    s = s.astype(str).str.strip()
    s = s.replace(["", "nan", "<NA>", "None"], None)
    return pd.to_numeric(s, errors="coerce")


def _build_nav_part(*, df: pd.DataFrame, date_val: str, nav_col: str, cum_col: str,
                    growth_col: str, source: str, ts: float) -> pd.DataFrame:
    """向量化构建净值记录 DataFrame"""
    return pd.DataFrame({
        "基金代码": df["基金代码"].astype(str),
        "日期": date_val,
        "单位净值": _to_float_series(df[nav_col]),
        "累计净值": _to_float_series(df[cum_col]),
        "日增长率": _parse_daily_pct_series(df[growth_col]),
        "数据来源": source,
        "updated_at": ts,
    })


def _extract_date_from_columns(cols: pd.Index) -> tuple[str | None, str | None, str | None]:
    """
    从动态列名中提取最新日期。
    列名模式: 'YYYY-MM-DD-单位净值' | 'YYYY-MM-DD-累计净值'
    返回 (date_str, unit_nav_col, cum_nav_col)
    """
    date_set = set()
    for c in cols:
        m = re.match(r"(\d{4}-\d{2}-\d{2})-(单位净值|累计净值)", str(c))
        if m:
            date_set.add(m.group(1))
    if not date_set:
        return None, None, None
    latest = max(date_set)
    return latest, f"{latest}-单位净值", f"{latest}-累计净值"


def collect_fund_nav(force: bool = False) -> None:
    """
    批量采集基金净值数据写入 fund_nav 表。
    数据源:
      1. fund_open_fund_daily_em() — 全市场开放基金，~23529 只（含场外指数基+海外）
      2. fund_etf_fund_daily_em() — 场内 ETF，~1549 只
    TTL: 24 小时
    """
    db.init_db()
    if not force and db.fund_nav.is_fresh():
        print("净值缓存有效（24h内），跳过。使用 --force 强制重采。")
        return

    nav_parts: list[pd.DataFrame] = []
    ts = time.time()

    # ── Source 1: fund_open_fund_daily_em ──
    print("Step 1/2 — 获取开放基金净值（fund_open_fund_daily_em）…")
    try:
        open_df = ak.fund_open_fund_daily_em()
    except Exception as e:
        print(f"  fund_open_fund_daily_em 调用失败: {e}")
        open_df = pd.DataFrame()

    if not open_df.empty:
        date_str, nav_col, cum_col = _extract_date_from_columns(open_df.columns)
        if date_str is None:
            print("  ! 无法从列名解析日期，跳过")
        elif "日增长率" not in open_df.columns:
            print("  ! 缺少 日增长率 列，跳过")
        else:
            part = _build_nav_part(
                df=open_df, date_val=date_str,
                nav_col=nav_col, cum_col=cum_col, growth_col="日增长率",
                source="open", ts=ts,
            )
            nav_parts.append(part)
            print(f"  → 已解析 {len(part)} 只开放基金（{date_str}）")

    # ── Source 2: fund_etf_fund_daily_em（补 ETF，与 open 无交集） ──
    print("Step 2/3 — 获取 ETF 净值（fund_etf_fund_daily_em）…")
    try:
        etf_df = ak.fund_etf_fund_daily_em()
    except Exception as e:
        print(f"  fund_etf_fund_daily_em 调用失败: {e}")
        etf_df = pd.DataFrame()

    if not etf_df.empty:
        date_str2, nav_col2, cum_col2 = _extract_date_from_columns(etf_df.columns)
        if date_str2 is None:
            print("  ! 无法从 ETF 列名解析日期，跳过")
        elif "增长率" not in etf_df.columns:
            print("  ! 缺少 增长率 列，跳过")
        else:
            part = _build_nav_part(
                df=etf_df, date_val=date_str2,
                nav_col=nav_col2, cum_col=cum_col2, growth_col="增长率",
                source="etf", ts=ts,
            )
            nav_parts.append(part)
            print(f"  → 已解析 {len(part)} 只 ETF（{date_str2}）")

    # ── Source 3: fund_open_fund_rank_em(FOF)，与 open 有重叠，需差集去重 ──
    print("Step 3/3 — 获取 FOF 净值（fund_open_fund_rank_em）…")
    try:
        fof_df = ak.fund_open_fund_rank_em(symbol="FOF")
    except Exception as e:
        print(f"  fund_open_fund_rank_em 调用失败: {e}")
        fof_df = pd.DataFrame()

    if not fof_df.empty:
        existing = set().union(*(p["基金代码"] for p in nav_parts))
        new = fof_df[~fof_df["基金代码"].astype(str).isin(existing)]
        if not new.empty:
            part = _build_nav_part(
                df=new, date_val=str(new.iloc[0]["日期"]),
                nav_col="单位净值", cum_col="累计净值", growth_col="日增长率",
                source="fof", ts=ts,
            )
            nav_parts.append(part)
            print(f"  → 新增 {len(part)} 只 FOF（{new.iloc[0]['日期']}）")

    # ── 写入 DB ──
    if not nav_parts:
        print("未采集到任何数据，跳过写入")
        return

    nav_df = pd.concat(nav_parts, ignore_index=True)
    print(f"\n写入 {len(nav_df)} 条记录到 fund_nav 表…")
    db.fund_nav.save(nav_df)
    print("写入完成。")


def collect_fund_catalog(force: bool = False) -> None:
    """采集全市场基金名录（fund_name_em），写入 fund_catalog 表。"""
    db.init_db()
    if not force and db.fund_catalog.is_fresh():
        print("基金名录缓存有效，跳过。使用 --force 强制重采。")
        return
    print("获取基金名录（fund_name_em）…")
    try:
        df = ak.fund_name_em()
    except Exception as e:
        print(f"  fund_name_em 调用失败: {e}")
        return
    db.fund_catalog.save(df)
    cnt = df["基金代码"].nunique()
    print(f"  → 已保存 {cnt} 只基金")


def main() -> None:
    parser = argparse.ArgumentParser(description="预采集基金费率数据")
    parser.add_argument("--force", action="store_true", help="强制全量重采")
    parser.add_argument("--codes", help="指定基金代码（逗号分隔）")
    parser.add_argument("--workers", type=int, default=10, help="并发数（默认 10）")
    parser.add_argument("--tracking-method", action="store_true", help="仅采集指数基金跟踪方式")
    parser.add_argument("--nav", action="store_true", help="仅采集基金净值")
    parser.add_argument("--catalog", action="store_true", help="仅采集基金名录")
    args = parser.parse_args()

    if args.tracking_method:
        collect_tracking_method()
        return
    if args.nav:
        collect_fund_nav(force=args.force)
        return
    if args.catalog:
        collect_fund_catalog(force=args.force)
        return

    codes = args.codes.split(",") if args.codes else None
    if codes:
        codes = [c.strip() for c in codes if c.strip()]

    collect_fund_data(max_workers=args.workers, force=args.force, codes=codes)


if __name__ == "__main__":
    main()
