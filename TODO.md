# TODO

## 性能

- [ ] 首次加载 ~9s：`fund_open_fund_daily_em()` 占 8.5s，好在 `@st.cache_data` 只需查一次
- [x] 指数选基页：移除 `fund_scale_open_sina()`，规模由 `enrich_fee_scale` 从 DB 缓存读取

## 数据

- [ ] `fund_fee` 表存 `净资产规模` 语义不符，应拆成独立 `fund_scale` 表
- [ ] 298 只基金（含 13 只 Y 份额）无规模数据，API 本身不返回，UI 显示 "—"

## 代码

- [x] `fetch_fund_scale()` 函数已无调用方，已删除死代码
