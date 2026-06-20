#!/usr/bin/env python3
"""
Streamlit 导航中枢
"""
import streamlit as st

dca = st.Page("app_pages/dca.py", title="定投回测", icon="📊", url_path="dca")
val = st.Page("app_pages/index_valuation.py", title="指数估值", icon="📈", url_path="valuation")
idx = st.Page("app_pages/index_fund.py", title="指数选基", icon="🎯", url_path="index_fund")

pg = st.navigation([dca, val, idx])
pg.run()
