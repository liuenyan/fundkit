"""
构建 index_name_map 表：跟踪标的名称 → 指数代码映射。

用法:
  uv run python -m tools.build_index_name_map           # 采集并写入
  uv run python -m tools.build_index_name_map --dry-run  # 预览不写入
"""

import argparse
import logging
from datetime import datetime

import pandas as pd
import akshare as ak

import db
from backend.logger import get_logger, setup_logging
from backend.parse_utils import normalize
from db import engine as db_engine
from tools.csi_export import get_equity_name_map as get_csi_name_map
from tools.cnindex_export import get_equity_name_map as get_cnindex_name_map

logger = get_logger(__name__)

_TODAY = datetime.now().strftime("%Y%m%d")

# ── 非权益关键词（按优先级从高到低）──
NON_EQUITY_KEYWORDS = [
    (
        "bond",
        [
            "中债",
            "国债",
            "国开行",
            "农发行",
            "进出口行",
            "政金债",
            "政策性金融债",
            "金融债",
            "信用债",
            "可转债",
            "可交换债",
            "短融",
            "中票",
            "城投债",
            "地方政府债",
            "公司债",
            "全价",
            "财富",
            "债券",
            "同业存单",
        ],
    ),
    ("commodity", ["上期有色金属", "上海金", "黄金", "原油", "商品"]),
    (
        "overseas",
        [
            "纳斯达克",
            "标普",
            "S&P",
            "道琼斯",
            "Dow Jones",
            "MSCI",
            "恒生",
            "iBoxx",
            "iEdge",
            "CFETS",
            "Emerging Asia",
            "US REIT",
            "US 50",
        ],
    ),
]


def classify_tracking_target(name: str) -> str:
    """返回 index_type: equity / bond / commodity / overseas"""
    for itype, keywords in NON_EQUITY_KEYWORDS:
        for kw in keywords:
            if kw in name:
                return itype
    return "equity"


# ── 手工兜底映射（数据源无法覆盖的条目）──

KNOWN_MAP: dict[str, tuple[str, str | None, str, str, str]] = {
    # (normalized_name) → (code, market_prefix, source, index_type, short_name)
    # CNINDEX 只有"国证新能源车"（无"汽"），聚宽能匹配但已移除
    "国证新能源汽车": ("399417", "sz", "daily_em", "equity", "新能源车"),
    # CSI 只有"责任指数"（保留"指数"），normalize 后"责任"不匹配
    "责任": ("000048", "sh", "csindex", "equity", "责任指数"),
    # CSI 只有"中证800有色金属"（无"有色"缩写）
    "中证800有色": ("H30031", "sh", "csindex", "equity", "800有色"),
    # CSI 只有"中证细分化工产业主题"（无"全收益"版本），回退价格指数
    "中证细分化工产业主题全收益": ("000813", "sh", "csindex", "equity", "细分化工"),
    # CSI 只有"上证科创板新能源"（无"主题"）
    "上证科创板新能源主题": ("000692", "sh", "csindex", "equity", "科创新能"),
    # CNINDEX 只有"创业板中盘200指数"（fund 缺"中盘"）
    "创业板200": ("399019", "sz", "daily_em", "equity", "创业200"),
    # tracking_target "深证300价格" → normalize 后为"深证300价格"，不会自动匹配"深证300"
    "深证300价格": ("399007", "sz", "daily_em", "equity", "深证300"),
    # tracking_target "香蜜湖金融科技指数(价格)" → normalize 后为"香蜜湖金融科技"
    "香蜜湖金融科技": ("399699", "sz", "daily_em", "equity", "金融科技"),
    # 非权益
    "上海金": ("SHAU", "sh", "daily_em", "commodity", "上海金"),
    # ── 海外指数 P0（Sina 财经可获取价格）──
    # 恒生系列 via stock_hk_index_daily_sina (normalize strips "指数" → keys are stemmed)
    # market_prefix=None：Sina API 的 symbol 在 index_code 中已完整，无需拼接
    "恒生": ("HSI", None, "sina_hk", "equity", "恒生指数"),
    "恒生中国企业": ("HSCEI", None, "sina_hk", "equity", "恒生国企"),
    "恒生科技": ("HSTECH", None, "sina_hk", "equity", "恒生科技"),
    "恒生港股通新经济": ("HSSCNE", None, "hsi", "equity", "港股通新经济"),
    # 美股系列 via index_us_stock_sina
    "纳斯达克100": (".NDX", None, "sina_us", "equity", "纳指100"),
    "道琼斯工业平均": (".DJI", None, "sina_us", "equity", "道琼斯"),
}


def _verify_csindex(code: str) -> bool:
    """验证 stock_zh_index_hist_csindex 能否返回数据"""
    try:
        df = ak.stock_zh_index_hist_csindex(symbol=code, start_date="20200101", end_date=_TODAY)
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


def _verify_sina_hk(symbol: str) -> bool:
    """验证 stock_hk_index_daily_sina 能否返回数据"""
    try:
        df = ak.stock_hk_index_daily_sina(symbol=symbol)
        return df is not None and not df.empty
    except Exception:
        return False


def _verify_sina_us(symbol: str) -> bool:
    """验证 index_us_stock_sina 能否返回数据"""
    try:
        df = ak.index_us_stock_sina(symbol=symbol)
        return df is not None and not df.empty
    except Exception:
        return False


def _verify_sina_cn(prefix: str, code: str) -> bool:
    """验证 stock_zh_index_daily (Sina A股) 能否返回数据"""
    try:
        df = ak.stock_zh_index_daily(symbol=f"{prefix}{code}")
        return df is not None and not df.empty
    except Exception:
        return False


def _fetch_close_from_csindex(code: str) -> pd.DataFrame | None:
    try:
        df = ak.stock_zh_index_hist_csindex(symbol=code, start_date="20000101", end_date=_TODAY)
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

    # 构建归一化索引（解决 fund 跟踪标与官方名空格/后缀不一致的差异）
    csi_norm_map: dict[str, tuple[str, str, str]] = {}
    for k, v in csi_name_map.items():
        nk = normalize(k)
        if nk not in csi_norm_map:
            csi_norm_map[nk] = v

    cnindex_norm_map: dict[str, tuple[str, str | None, str]] = {}
    for k, v in cnindex_name_map.items():
        nk = normalize(k)
        if nk not in cnindex_norm_map:
            cnindex_norm_map[nk] = v

    success: list[dict] = []
    failed: list[dict] = []
    skipped: list[dict] = []

    for target in all_targets:
        index_type = classify_tracking_target(target)
        n = normalize(target)

        short_name = ""
        # 优先 KNOWN_MAP
        if n in KNOWN_MAP:
            code, prefix, source, mapped_type, short_name = KNOWN_MAP[n]
            # 记录 跳过非 equity（不验证 — 只需确认不要误写入 price 缓存）
            if mapped_type != "equity":
                skipped.append(
                    {
                        "tracking_target": target,
                        "display_name": n,
                        "index_code": code,
                        "index_type": mapped_type,
                        "reason": f"non-equity({mapped_type})",
                    }
                )
                continue
        elif index_type != "equity":
            skipped.append(
                {
                    "tracking_target": target,
                    "display_name": n,
                    "index_code": None,
                    "index_type": index_type,
                    "reason": f"non-equity({index_type})",
                }
            )
            continue
        else:
            # 自动匹配：CSI 官网 → 国证官网
            code = None
            prefix = None
            match_source = None  # "csi" or "cnindex"

            # 1) CSI 官网精确匹配（含归一化 fallback）
            if n in csi_name_map:
                code, prefix, short_name = csi_name_map[n]
                match_source = "csi"
            elif n in csi_norm_map:
                code, prefix, short_name = csi_norm_map[n]
                match_source = "csi"

            # 2) 国证官网精确匹配（含归一化 fallback）
            if code is None and n in cnindex_name_map:
                code, prefix, short_name = cnindex_name_map[n]
                match_source = "cnindex"
            elif code is None and n in cnindex_norm_map:
                code, prefix, short_name = cnindex_norm_map[n]
                match_source = "cnindex"

            if code is None:
                failed.append(
                    {
                        "tracking_target": target,
                        "display_name": n,
                        "index_code": None,
                        "index_type": "equity",
                        "reason": "no match from any source",
                    }
                )
                continue

            # 确定数据源：国证匹配的走东财，CSI 匹配的走中证
            if match_source == "cnindex":
                source = "daily_em"
            else:
                source = "csindex"

            # prefix 兜底（仅当两个匹配源均未提供时）
            if prefix is None:
                if code.startswith(("000", "001", "H", "9")):
                    prefix = "sh" if code[0] in ("0", "H") else "csi"
                elif code.startswith("399"):
                    prefix = "sz" if code[0] == "3" else "csi"
                elif code.startswith("CN"):
                    # CN 代码无市场前缀，东财直接用裸代码
                    pass
                else:
                    failed.append(
                        {
                            "tracking_target": target,
                            "display_name": n,
                            "index_code": code,
                            "index_type": "equity",
                            "reason": f"unknown code format: {code}",
                        }
                    )
                    continue

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
                    elif code.startswith("399") and _verify_sina_cn(em_prefix, code):
                        source = "sina_cn"
            elif source == "daily_em":
                verified_ok = _verify_daily_em(prefix or "", code)
            elif source == "sina_hk":
                verified_ok = _verify_sina_hk(code)
            elif source == "sina_us":
                verified_ok = _verify_sina_us(code)

        success.append(
            {
                "tracking_target": target,
                "display_name": n,
                "short_name": short_name,
                "index_code": code,
                "market_prefix": prefix,
                "source": source,
                "index_type": "equity",
                "verified": verified_ok,
            }
        )

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
    logger.info(
        "  ✅ 成功映射: %d（已验证 %d，待验证 %d）", len(success), verified_count, len(success) - verified_count
    )
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
            logger.info("  [%s]  → code=%s (%s)", r["tracking_target"][:40], r["index_code"] or "N/A", r["reason"])

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
    setup_logging(level=logging.INFO)
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
