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
import concurrent.futures
import re
import sys
import time

import akshare as ak
import pandas as pd

import db
from fund_data import parse_fee_pct, _parse_scale


def parse_purchase(s):
    """解析 fund_purchase_em 的手续费，支持 '0.15%'、'---'、NaN"""
    if pd.isna(s) or s is None:
        return None
    s = str(s).strip().replace("%", "").replace("---", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def fetch_one_overview(code):
    """单只基金获取管理费/托管费/销售服务费/净资产规模/份额规模/档案信息"""
    try:
        df = ak.fund_overview_em(symbol=code)
        if df.empty:
            return None
        row = df.iloc[0]
        mgmt = parse_fee_pct(row.get("管理费率"))
        cust = parse_fee_pct(row.get("托管费率"))
        sales_service = parse_fee_pct(row.get("销售服务费率"))
        scale = _parse_scale(row.get("净资产规模"))
        scale_shares = _parse_scale(row.get("份额规模"))
        establish_full = str(row.get("成立日期/规模")) if pd.notna(row.get("成立日期/规模")) else None
        establish_date = establish_full.split(" / ")[0] if establish_full else None
        return (
            mgmt,
            cust,
            sales_service,
            scale,
            scale_shares,
            str(row.get("发行日期")) or None,
            establish_date,
            str(row.get("基金管理人")) or None,
            str(row.get("基金托管人")) or None,
            str(row.get("基金经理人")) or None,
            str(row.get("业绩比较基准")) or None,
            str(row.get("跟踪标的")) or None,
        )
    except Exception:
        return None


def collect_fund_data(max_workers=10, force=False, codes=None):
    db.init_db()

    # ── TTL 检查 ──
    if not force and not codes and db.is_fee_cache_fresh():
        cnt = db.get_fee_cached_count()
        print(f"费率缓存有效，已缓存 {cnt} 只基金，跳过。使用 --force 强制重采。")
        return

    # ── 获取所有基金代码 ──
    print("正在获取基金申购费数据（fund_purchase_em）…")
    try:
        purchase_df = ak.fund_purchase_em()
    except Exception as e:
        print(f"获取 fund_purchase_em 失败: {e}")
        sys.exit(1)

    if codes:
        purchase_df = purchase_df[purchase_df["基金代码"].isin(codes)]

    all_codes = purchase_df["基金代码"].tolist()
    total = len(all_codes)
    print(f"共 {total} 只基金\n")

    # ── Step 1: 保存申购费 + 起购金额 ──
    print("Step 1/2 — 保存申购费 + 起购金额…")
    saved = 0
    for _, row in purchase_df.iterrows():
        code = row["基金代码"]
        purchase = parse_purchase(row.get("手续费"))
        min_purchase = str(row.get("购买起点", "")) if pd.notna(row.get("购买起点")) else None
        db.save_fund_fee(code, purchase, None, None, None, min_purchase, None)
        saved += 1
    print(f"  → 已保存 {saved} 只基金申购费数据\n")

    # ── Step 2: 并发获取管理费/托管费/销售服务费 ──
    print(f"Step 2/2 — 并发获取管理费/托管费/销售服务费 ({max_workers} workers)…")
    t0 = time.time()
    success = 0
    failed = 0

    load_cached = db.load_fund_fees(all_codes)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        fut_map = {pool.submit(fetch_one_overview, code): code for code in all_codes}
        done = 0
        for f in concurrent.futures.as_completed(fut_map):
            done += 1
            code = fut_map[f]
            result = f.result()
            if result is None:
                failed += 1
            else:
                (
                    mgmt,
                    cust,
                    sales_service,
                    scale,
                    scale_shares,
                    issue_date,
                    establish_date,
                    mgr,
                    custodian,
                    fund_mgr,
                    benchmark,
                    track_index,
                ) = result
                cached = load_cached.get(code, {})
                purchase = cached.get("申购费")
                min_purchase = cached.get("起购金额")
                sales = sales_service if sales_service is not None else 0
                total_fee = (
                    round((purchase or 0) + (mgmt or 0) + (cust or 0) + sales, 2)
                    if mgmt is not None and cust is not None
                    else None
                )
                db.save_fund_fee(
                    code,
                    purchase,
                    mgmt,
                    cust,
                    sales_service,
                    min_purchase,
                    total_fee,
                )
                db.save_fund_scale(code, scale, scale_shares)
                db.save_fund_profile(code, issue_date, establish_date, mgr, custodian, fund_mgr, benchmark, track_index)
                success += 1

            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 else 0
            eta = (total - done) / rate if rate > 0 else 0
            print(
                f"\r  [{done}/{total}] 成功 {success}, 失败 {failed}, 速率 {rate:.1f} 只/秒, 预计剩余 {eta:.0f}s",
                end="",
                flush=True,
            )

    print()
    elapsed = time.time() - t0
    print(f"\n采集完成！耗时 {elapsed:.0f}s")
    print(f"  成功: {success}  失败: {failed}")

    # ── Step 3: 获取指数基金跟踪方式 ──
    collect_tracking_method()

    # ── 标记缓存新鲜 ──
    if not codes:
        db.set_fee_cache_fresh()
        print("  费率缓存 TTL 已更新")


def collect_tracking_method():
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

    db.batch_update_tracking_method(method_map)
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


def _parse_daily_pct(v):
    """归一化日增长率：'7.36' → 7.36, '0.05%' → 0.05, NaN → None"""
    if pd.isna(v) or v is None or str(v).strip() in ("", "—", "---"):
        return None
    s = str(v).strip().replace("%", "").replace(" ", "")
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _extract_date_from_columns(cols):
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


def collect_fund_nav(force=False):
    """
    批量采集基金净值数据写入 fund_nav 表。
    数据源:
      1. fund_open_fund_daily_em() — 全市场开放基金，~23529 只（含场外指数基+海外）
      2. fund_etf_fund_daily_em() — 场内 ETF，~1549 只
    TTL: 24 小时
    """
    db.init_db()
    if not force and db.is_fund_nav_fresh():
        print("净值缓存有效（24h内），跳过。使用 --force 强制重采。")
        return

    def _to_float(v):
        if pd.isna(v) or v is None or str(v).strip() == "":
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    rows = []
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
        else:
            growth_col = "日增长率"
            if growth_col not in open_df.columns:
                print(f"  ! 缺少 {growth_col} 列，跳过")
            else:
                for _, r in open_df.iterrows():
                    rows.append(
                        {
                            "基金代码": str(r["基金代码"]),
                            "日期": date_str,
                            "单位净值": _to_float(r.get(nav_col)),
                            "累计净值": _to_float(r.get(cum_col)),
                            "日增长率": _parse_daily_pct(r.get(growth_col)),
                            "数据来源": "open",
                            "updated_at": ts,
                        }
                    )
                print(f"  → 已解析 {len(rows)} 只开放基金（{date_str}）")

    # ── Source 2: fund_etf_fund_daily_em（补 ETF，覆盖新代码） ──
    print("Step 2/2 — 获取 ETF 净值（fund_etf_fund_daily_em）…")
    try:
        etf_df = ak.fund_etf_fund_daily_em()
    except Exception as e:
        print(f"  fund_etf_fund_daily_em 调用失败: {e}")
        etf_df = pd.DataFrame()

    existing_codes = {r["基金代码"] for r in rows}
    etf_added = 0
    if not etf_df.empty:
        date_str2, nav_col2, cum_col2 = _extract_date_from_columns(etf_df.columns)
        if date_str2 is None:
            print("  ! 无法从 ETF 列名解析日期，跳过")
        else:
            growth_col2 = "增长率"
            if growth_col2 not in etf_df.columns:
                print(f"  ! 缺少 {growth_col2} 列，跳过")
            else:
                for _, r in etf_df.iterrows():
                    code = str(r["基金代码"])
                    if code in existing_codes:
                        continue
                    rows.append(
                        {
                            "基金代码": code,
                            "日期": date_str2,
                            "单位净值": _to_float(r.get(nav_col2)),
                            "累计净值": _to_float(r.get(cum_col2)),
                            "日增长率": _parse_daily_pct(r.get(growth_col2)),
                            "数据来源": "etf",
                            "updated_at": ts,
                        }
                    )
                    etf_added += 1
                print(f"  → 新增 {etf_added} 只 ETF（{date_str2}）")

    # ── Source 3: fund_open_fund_rank_em(FOF)（补 FOF，覆盖 FOF Y 份额） ──
    print("Step 3/3 — 获取 FOF 净值（fund_open_fund_rank_em）…")
    try:
        fof_df = ak.fund_open_fund_rank_em(symbol="FOF")
    except Exception as e:
        print(f"  fund_open_fund_rank_em 调用失败: {e}")
        fof_df = pd.DataFrame()

    existing_codes = {r["基金代码"] for r in rows}
    fof_added = 0
    if not fof_df.empty:
        for _, r in fof_df.iterrows():
            code = str(r["基金代码"])
            if code in existing_codes:
                continue
            rows.append(
                {
                    "基金代码": code,
                    "日期": str(r.get("日期", "")),
                    "单位净值": _to_float(r.get("单位净值")),
                    "累计净值": _to_float(r.get("累计净值")),
                    "日增长率": _parse_daily_pct(r.get("日增长率")),
                    "数据来源": "fof",
                    "updated_at": ts,
                }
            )
            fof_added += 1
        print(f"  → 新增 {fof_added} 只 FOF（{fof_df.iloc[0].get('日期', '')}）")

    # ── 写入 DB ──
    if not rows:
        print("未采集到任何数据，跳过写入")
        return

    nav_df = pd.DataFrame(rows)
    print(f"\n写入 {len(nav_df)} 条记录到 fund_nav 表…")
    db.save_fund_nav(nav_df)
    print("写入完成。")


def main():
    parser = argparse.ArgumentParser(description="预采集基金费率数据")
    parser.add_argument("--force", action="store_true", help="强制全量重采")
    parser.add_argument("--codes", help="指定基金代码（逗号分隔）")
    parser.add_argument("--workers", type=int, default=10, help="并发数（默认 10）")
    parser.add_argument("--tracking-method", action="store_true", help="仅采集指数基金跟踪方式")
    parser.add_argument("--nav", action="store_true", help="仅采集基金净值")
    args = parser.parse_args()

    if args.tracking_method:
        collect_tracking_method()
        return
    if args.nav:
        collect_fund_nav(force=args.force)
        return

    codes = args.codes.split(",") if args.codes else None
    if codes:
        codes = [c.strip() for c in codes if c.strip()]

    collect_fund_data(max_workers=args.workers, force=args.force, codes=codes)


if __name__ == "__main__":
    main()
