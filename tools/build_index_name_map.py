"""
构建 index_name_map 表：跟踪标的名称 → 指数代码映射。

用法:
  ./venv/bin/python -m tools.build_index_name_map           # 采集并写入
  ./venv/bin/python -m tools.build_index_name_map --dry-run  # 预览不写入
"""

import argparse
import logging
import re
import time
from datetime import datetime

import pandas as pd
import akshare as ak

import db
from db import engine as db_engine
from tools.csi_export import get_equity_name_map as get_csi_name_map
from tools.cnindex_export import get_equity_name_map as get_cnindex_name_map

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_TODAY = datetime.now().strftime("%Y%m%d")

# ── 非权益关键词（按优先级从高到低）──
NON_EQUITY_KEYWORDS = [
    ("bond", ["中债", "国债", "国开行", "农发行", "进出口行", "政金债",
              "政策性金融债", "金融债", "信用债", "可转债", "可交换债",
              "短融", "中票", "城投债", "地方政府债", "公司债",
              "全价", "财富", "债券", "同业存单"]),
    ("commodity", ["上期有色金属", "上海金", "黄金", "原油", "商品"]),
    ("overseas", ["纳斯达克", "标普", "S&P", "道琼斯", "Dow Jones",
                  "MSCI", "恒生", "iBoxx", "iEdge", "CFETS",
                  "Emerging Asia", "US REIT", "US 50"]),
]


def classify_tracking_target(name: str) -> str:
    """返回 index_type: equity / bond / commodity / overseas"""
    for itype, keywords in NON_EQUITY_KEYWORDS:
        for kw in keywords:
            if kw in name:
                return itype
    return "equity"


# ── 名称归一化 ──

_SUFFIXES = [
    "指数", "(价格)", "(四级行业)", "(全价)", "(总值)", "(总收益)",
    "(LOF)", "(行业)", " ",
]
_CURRENCY_SUFFIXES = ["人民币", "港元", "美元", "港币"]


def normalize(name: str) -> str:
    for s in _SUFFIXES:
        name = name.replace(s, "")
    for s in _CURRENCY_SUFFIXES:
        if name.endswith(s):
            name = name[: -len(s)]
            break
    # 去掉末尾残留括号内容
    if "(" in name and name.endswith(")"):
        name = name[:name.index("(")]
    # 全角括号也处理
    if "（" in name and name.endswith("）"):
        name = name[:name.index("（")]
    return name.strip()


# ── 手工兜底映射（数据源无法覆盖的条目）──

KNOWN_MAP: dict[str, tuple[str, str, str, str]] = {
    # (normalized_name) → (code, market_prefix, source, index_type)

    # CNINDEX 只有"国证新能源车"（无"汽"），聚宽能匹配但已移除
    "国证新能源汽车":    ("399417", "sz", "csindex", "equity"),

    # CSI 只有"责任指数"（保留"指数"），normalize 后"责任"不匹配
    "责任":              ("000048", "sh", "csindex", "equity"),

    # 非权益
    "上海金":            ("SHAU", "sh", "daily_em", "commodity"),
}


def _verify_csindex(code: str) -> bool:
    """验证 stock_zh_index_hist_csindex 能否返回数据"""
    try:
        df = ak.stock_zh_index_hist_csindex(
            symbol=code, start_date="20200101", end_date=_TODAY
        )
        return df is not None and not df.empty
    except Exception:
        return False


def _verify_daily_em(prefix: str, code: str) -> bool:
    """验证 stock_zh_index_daily_em 能否返回数据"""
    try:
        df = ak.stock_zh_index_daily_em(
            symbol=f"{prefix}{code}",
            start_date="20200101",
            end_date=_TODAY,
        )
        return df is not None and not df.empty
    except Exception:
        return False


def _fetch_close_from_csindex(code: str) -> pd.DataFrame | None:
    try:
        df = ak.stock_zh_index_hist_csindex(
            symbol=code, start_date="20000101", end_date=_TODAY
        )
        if df is None or df.empty or "收盘" not in df.columns:
            return None
        out = df[["日期", "收盘"]].dropna().copy()
        out.columns = ["date", "value"]
        return out
    except Exception:
        return None


def _fetch_close_from_daily_em(prefix: str, code: str) -> pd.DataFrame | None:
    try:
        df = ak.stock_zh_index_daily_em(
            symbol=f"{prefix}{code}",
            start_date="20000101",
            end_date=_TODAY,
        )
        if df is None or df.empty or "close" not in df.columns:
            return None
        out = df[["date", "close"]].dropna().copy()
        out.columns = ["date", "value"]
        return out
    except Exception:
        return None


def build_all_mappings(skip_verify: bool = False) -> tuple[list[dict], list[dict], list[dict]]:
    """
    返回 (success, failed_verify, skipped) 三条记录列表。
    每条记录含 {display_name, tracking_target, index_code, ...}
    """
    db.init_db()

    # 读取所有指数基金的跟踪标的
    sql = """
    SELECT DISTINCT pf.跟踪标的
    FROM fund_catalog cat
    JOIN fund_profile pf ON cat.基金代码 = pf.基金代码
    WHERE cat.基金类型 LIKE '指数型-%'
      AND pf.跟踪标的 IS NOT NULL
    ORDER BY pf.跟踪标的
    """
    df = pd.read_sql_query(sql, db_engine)
    all_targets = df["跟踪标的"].tolist()

    # 数据源 1：中证指数官网导出接口（主数据源，~1847 条 equity 指数）
    try:
        csi_name_map = get_csi_name_map()  # {display_name: (code, prefix, short_name)}
        logger.info("CSI 官网映射: %d 条可用", len(csi_name_map))
    except Exception as exc:
        logger.warning("CSI 导出失败: %s", exc)
        csi_name_map = {}

    # 数据源 2：国证指数官网导出接口（深证/国证系列，~1212 条 equity 指数）
    try:
        cnindex_name_map = get_cnindex_name_map()  # {display_name: (code, prefix, short_name)}
        logger.info("国证官网映射: %d 条可用", len(cnindex_name_map))
    except Exception as exc:
        logger.warning("国证导出失败: %s", exc)
        cnindex_name_map = {}

    success: list[dict] = []
    failed: list[dict] = []
    skipped: list[dict] = []

    for target in all_targets:
        index_type = classify_tracking_target(target)
        n = normalize(target)

        # 优先 KNOWN_MAP
        if n in KNOWN_MAP:
            code, prefix, source, mapped_type = KNOWN_MAP[n]
            short_name = n
            # 记录 跳过非 equity（不验证 — 只需确认不要误写入 price 缓存）
            if mapped_type != "equity":
                skipped.append({
                    "tracking_target": target,
                    "display_name": n,
                    "index_code": code,
                    "index_type": mapped_type,
                    "reason": f"non-equity({mapped_type})",
                })
                continue
        elif index_type != "equity":
            skipped.append({
                "tracking_target": target,
                "display_name": n,
                "index_code": None,
                "index_type": index_type,
                "reason": f"non-equity({index_type})",
            })
            continue
        else:
            # 自动匹配：CSI 官网 → 国证官网
            code = None
            prefix = None

            # 1) CSI 官网精确匹配
            if n in csi_name_map:
                code, prefix, short_name = csi_name_map[n]

            # 2) 国证官网精确匹配
            if code is None and n in cnindex_name_map:
                code, prefix, short_name = cnindex_name_map[n]

            if code is None:
                failed.append({
                    "tracking_target": target,
                    "display_name": n,
                    "index_code": None,
                    "index_type": "equity",
                    "reason": "no match from any source",
                })
                continue

            # 判断 source（CSI 匹配时 prefix 已确定）
            if prefix is None:
                if code.startswith(("000", "001", "H", "9")):
                    prefix = "sh" if code[0] in ("0", "H") else "csi"
                elif code.startswith("399"):
                    prefix = "sz" if code[0] == "3" else "csi"
                else:
                    failed.append({
                        "tracking_target": target,
                        "display_name": n,
                        "index_code": code,
                        "index_type": "equity",
                        "reason": f"unknown code format: {code}",
                    })
                    continue
            source = "csindex"

        # 验证（仅记录结果，不阻止写入——运行时 API 失败会回退 acc_nav）
        verified_ok = True
        if not skip_verify:
            if source == "csindex":
                ok = _verify_csindex(code)
                if not ok:
                    em_prefix = "sh" if code[0] in ("0", "H", "9") else "sz" if code[0] == "3" else "csi"
                    if _verify_daily_em(em_prefix, code):
                        source = "daily_em"
                        prefix = em_prefix
            elif source == "daily_em":
                verified_ok = _verify_daily_em(prefix, code)

        success.append({
            "tracking_target": target,
            "display_name": n,
            "short_name": short_name,
            "index_code": code,
            "market_prefix": prefix,
            "source": source,
            "index_type": "equity",
            "verified": verified_ok,
        })

    return success, failed, skipped


def write_to_db(records: list[dict]) -> int:
    """写入 index_name_map，返回写入条数"""
    with db_engine.begin() as conn:
        data = [
            {
                "display_name": r["display_name"],
                "short_name": r.get("short_name"),
                "index_code": r["index_code"],
                "market_prefix": r.get("market_prefix"),
                "source": r.get("source"),
                "index_type": r.get("index_type", "equity"),
            }
            for r in records
        ]
        if data:
            conn.execute(
                db.index_name_map.insert().prefix_with("OR REPLACE"),
                data,
            )
    return len(data)


def print_report(success: list[dict], failed: list[dict], skipped: list[dict]) -> None:
    total = len(success) + len(failed) + len(skipped)
    logger.info("=" * 60)
    logger.info("映射报告")
    logger.info("=" * 60)
    logger.info("总跟踪标数: %d", total)
    verified_count = sum(1 for r in success if r.get("verified"))
    logger.info("  ✅ 成功映射: %d（已验证 %d，待验证 %d）",
                len(success), verified_count, len(success) - verified_count)
    logger.info("  ❌ 未匹配: %d", len(failed))
    logger.info("  ⏭️  跳过(非权益): %d", len(skipped))

    # 按 index_type 统计
    type_counts: dict[str, int] = {}
    for r in success:
        type_counts[r["index_type"]] = type_counts.get(r["index_type"], 0) + 1
    for r in skipped:
        t = r.get("index_type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    if type_counts:
        logger.info("类型分布:")
        for t, c in sorted(type_counts.items()):
            logger.info("  %s: %d", t, c)

    if failed:
        logger.info("")
        logger.info("❌ 验证失败的 equity 映射:")
        for r in failed:
            logger.info("  [%s]  → code=%s (%s)", r["tracking_target"][:40],
                        r["index_code"] or "N/A", r["reason"])

    # 列出来源分布
    source_counts: dict[str, int] = {}
    for r in success:
        s = r.get("source", "unknown")
        source_counts[s] = source_counts.get(s, 0) + 1
    if source_counts:
        logger.info("")
        logger.info("数据源分布:")
        for s, c in sorted(source_counts.items()):
            logger.info("  %s: %d", s, c)


def main() -> None:
    parser = argparse.ArgumentParser(description="构建指数名称→代码映射表")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入")
    parser.add_argument("--no-verify", action="store_true", help="跳过 API 验证")
    args = parser.parse_args()

    db.init_db()

    # 清空旧数据（重新构建）
    with db_engine.begin() as conn:
        conn.execute(db.index_name_map.delete())

    success, failed, skipped = build_all_mappings(skip_verify=args.no_verify)

    if not args.dry_run:
        n = write_to_db(success)
        logger.info("写入 index_name_map: %d 条", n)
    else:
        logger.info("DRY RUN，不写入")

    print_report(success, failed, skipped)


if __name__ == "__main__":
    main()