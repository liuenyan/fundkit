#!/usr/bin/env python3
"""
Streamlit 导航中枢
"""
import streamlit as st

dca = st.Page("app_pages/dca.py", title="定投回测", icon="📊", url_path="dca")
val = st.Page("app_pages/valuation.py", title="指数估值", icon="📈", url_path="valuation")

pg = st.navigation([dca, val])
pg.run()
