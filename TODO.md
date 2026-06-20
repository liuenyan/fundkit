# TODO

## 性能

- [ ] 首次加载 ~9s：`fund_open_fund_daily_em()` 占 8.5s，好在 `@st.cache_data` 只需查一次
- [ ] 指数选基页可能也有类似性能问题，需确认是否依赖慢 API

## 数据

- [ ] `fund_fee` 表存 `净资产规模` 语义不符，应拆成独立 `fund_scale` 表
- [ ] 298 只基金（含 13 只 Y 份额）无规模数据，API 本身不返回，UI 显示 "—"

## 代码

- [ ] `fetch_fund_scale()` 函数已无调用方，可删除死代码
