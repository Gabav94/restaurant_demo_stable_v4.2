
# -*- coding: utf-8 -*-
from __future__ import annotations
import streamlit as st
import pandas as pd

def menu_table_component(menu: list[dict], lang: str, deletable: bool=False, on_delete=None):
    if not menu:
        st.info("No hay items aún." if lang == "es" else "No items yet.")
        return
    df = pd.DataFrame(menu)
    try:
        st.dataframe(df, hide_index=True, width='stretch')
    except TypeError:
        st.dataframe(df, hide_index=True)
    if deletable and on_delete:
        names = [m["name"] for m in menu]
        sel = st.selectbox("Eliminar ítem" if lang=="es" else "Delete item", names if names else ["-"])
        if st.button("Eliminar" if lang=="es" else "Delete") and sel and sel!="-":
            on_delete(sel)
            st.success("OK")
            st.experimental_rerun()

def render_js_carousel(images: list[str], interval_ms: int=5000, key_prefix: str="gal", show_dots: bool=True, aspect_ratio: float=16/9, height_px: int=420):
    if not images:
        return
    idx_key = f"{key_prefix}_idx"
    if idx_key not in st.session_state: st.session_state[idx_key] = 0
    i = st.session_state[idx_key] % len(images)
    st.image(images[i], use_container_width=True)
    c1, c2, c3 = st.columns(3)
    if c1.button("⏮️", key=f"{key_prefix}_prev"):
        st.session_state[idx_key] = (st.session_state[idx_key]-1) % len(images)
        st.experimental_rerun()
    if c3.button("⏭️", key=f"{key_prefix}_next"):
        st.session_state[idx_key] = (st.session_state[idx_key]+1) % len(images)
        st.experimental_rerun()
