"""从 index_name_map 表重新生成 docs/index_name_map_report.md"""
from pathlib import Path

import pandas as pd

import db
from db import engine as db_engine
from tools.build_index_name_map import classify_tracking_target, normalize

REPORT_PATH = Path(__file__).resolve().parent.parent / "docs" / "index_name_map_report.md"


def rep_fund(target: str) -> str:
    sql = """
    SELECT cat.基金简称, cat.基金代码
    FROM fund_profile pf
    JOIN fund_catalog cat ON pf.基金代码 = cat.基金代码
    WHERE pf.跟踪标的 = ? AND cat.基金类型 LIKE '指数型-%'
    ORDER BY cat.基金代码 LIMIT 1
    """
    rows = pd.read_sql_query(sql, db_engine, params=(target,))
    if rows.empty:
        return "—"
    r = rows.iloc[0]
    return f"{r['基金简称']}({r['基金代码']})"


def generate() -> None:
    db.init_db()

    im = pd.read_sql_query(
        "SELECT * FROM index_name_map WHERE index_type = 'equity'", db_engine
    )
    eq_names = set(im["display_name"])
    name_map = {
        r["display_name"]: (r["index_code"], r["market_prefix"], r["source"])
        for _, r in im.iterrows()
    }

    sql = """
    SELECT DISTINCT pf.跟踪标的 AS target
    FROM fund_profile pf
    JOIN fund_catalog cat ON pf.基金代码 = cat.基金代码
    WHERE cat.基金类型 LIKE '指数型-%' AND pf.跟踪标的 IS NOT NULL
    ORDER BY pf.跟踪标的
    """
    all_targets = pd.read_sql_query(sql, db_engine)["target"].tolist()

    success: list[tuple[str, str, str, str, str]] = []
    failed: list[tuple[str, str]] = []
    bond = commodity = overseas = 0

    for target in all_targets:
        n = normalize(target)
        if n in eq_names:
            code, prefix, src = name_map[n]
            success.append((target, n, code, prefix, src))
            continue
        t = classify_tracking_target(target)
        if t == "bond":
            bond += 1
        elif t == "commodity":
            commodity += 1
        elif t == "overseas":
            overseas += 1
        else:
            failed.append((target, rep_fund(target)))

    skipped = bond + commodity + overseas
    date_str = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"""# 指数名称→代码映射验证报告

**生成时间**: {date_str}
**数据源**: fund_profile.跟踪标的 ({len(all_targets)} unique) → index_name_map 表 ({len(eq_names)} 条唯一 display_name)

---

## 汇总

| 分类 | 数量 |
|------|------|
| 总跟踪标 | {len(all_targets)} |
| 已映射 (index_name_map equity) | {len(eq_names)} |
| 覆盖的跟踪标 | {len(success)} |
| 未匹配 | {len(failed)} |
| 跳过非权益 | {skipped} (bond {bond}, commodity {commodity}, overseas {overseas}) |

---

## 成功映射的跟踪标的

共 {len(success)} 条。

| # | 跟踪标的名称 | 归一化名称 | 指数代码 | 市场前缀 | 数据源 |
|---|-------------|-----------|---------|---------|-------|
"""
    ]
    for i, (t, n, c, p, s) in enumerate(success, 1):
        lines.append(f"| {i} | {t} | {n} | {c} | {p} | {s} |\n")

    lines.append(f"""

---

## 未匹配的跟踪标的

共 {len(failed)} 条，运行时自动回退 acc_nav MA（Level 3）。

| # | 跟踪标的名称 | 代表基金 |
|---|-------------|---------|
""")
    for i, (t, f) in enumerate(failed, 1):
        lines.append(f"| {i} | {t} | {f} |\n")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("".join(lines), encoding="utf-8")
    print(f"OK: 成功 {len(success)} / 失败 {len(failed)} / 跳过 {skipped}")


if __name__ == "__main__":
    generate()
