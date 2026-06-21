# TODO

## 性能

- [ ] 首次加载 ~9s：`fund_open_fund_daily_em()` 占 8.5s，好在 `@st.cache_data` 只需查一次
