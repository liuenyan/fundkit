"""
批量预采集基金费率数据，写入 DB 缓存。
TTL: 90 天

数据源:
  1. fund_purchase_em() — 批量获取 申购费 + 起购金额（1 次 API 调用）
  2. fund_overview_em() — 逐只获取 管理费/托管费/销售服务费（ThreadPoolExecutor 并发）

用法:
  ./venv/bin/python collect_fees.py
  ./venv/bin/python collect_fees.py --force
  ./venv/bin/python collect_fees.py --codes 000001,000002  # 指定基金
"""

import argparse
import concurrent.futures
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


def fetch_one_fee(code):
    """单只基金获取管理费/托管费/销售服务费/净资产规模"""
    try:
        df = ak.fund_overview_em(symbol=code)
        if df.empty:
            return None
        row = df.iloc[0]
        mgmt = parse_fee_pct(row.get("管理费率"))
        cust = parse_fee_pct(row.get("托管费率"))
        sales_service = parse_fee_pct(row.get("销售服务费率"))
        scale = _parse_scale(row.get("净资产规模"))
        return mgmt, cust, sales_service, scale
    except Exception:
        return None


def collect(max_workers=10, force=False, codes=None):
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
        fut_map = {pool.submit(fetch_one_fee, code): code for code in all_codes}
        done = 0
        for f in concurrent.futures.as_completed(fut_map):
            done += 1
            code = fut_map[f]
            result = f.result()
            if result is None:
                failed += 1
            else:
                mgmt, cust, sales_service, scale = result
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
                    code, purchase, mgmt, cust, sales_service,
                    min_purchase, total_fee, scale
                )
                success += 1

            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 else 0
            eta = (total - done) / rate if rate > 0 else 0
            print(
                f"\r  [{done}/{total}] 成功 {success}, 失败 {failed}, "
                f"速率 {rate:.1f} 只/秒, 预计剩余 {eta:.0f}s",
                end="", flush=True,
            )

    print()
    elapsed = time.time() - t0
    print(f"\n采集完成！耗时 {elapsed:.0f}s")
    print(f"  成功: {success}  失败: {failed}")

    # ── 标记缓存新鲜 ──
    if not codes:
        db.set_fee_cache_fresh()
        print("  费率缓存 TTL 已更新")


def main():
    parser = argparse.ArgumentParser(description="预采集基金费率数据")
    parser.add_argument("--force", action="store_true", help="强制全量重采")
    parser.add_argument("--codes", help="指定基金代码（逗号分隔）")
    parser.add_argument("--workers", type=int, default=10, help="并发数（默认 10）")
    args = parser.parse_args()

    codes = args.codes.split(",") if args.codes else None
    if codes:
        codes = [c.strip() for c in codes if c.strip()]

    collect(max_workers=args.workers, force=args.force, codes=codes)


if __name__ == "__main__":
    main()
