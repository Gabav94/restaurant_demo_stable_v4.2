# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import streamlit as st
import pandas as pd


def menu_table_component(menu: list[dict], lang: str, deletable: bool = False, on_delete=None):
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
        sel = st.selectbox("Eliminar ítem" if lang ==
                           "es" else "Delete item", names if names else ["-"])
        if st.button("Eliminar" if lang == "es" else "Delete") and sel and sel != "-":
            on_delete(sel)
            st.success("OK")
            st.rerun()


def _safe_st_image(img_bytes_or_path):
    try:
        st.image(img_bytes_or_path, use_container_width=True)
    except TypeError:
        st.image(img_bytes_or_path, use_column_width=True)


def render_js_carousel(
    images: list[str | bytes],
    interval_ms: int = 5000,
    key_prefix: str = "gal",
    show_dots: bool = True,
    aspect_ratio: float = 16 / 9,
    height_px: int = 420,
):
    if not images:
        return

    normalized: list[bytes] = []
    for itm in images:
        try:
            if isinstance(itm, (bytes, bytearray)):
                normalized.append(bytes(itm))
            elif isinstance(itm, str):
                if os.path.exists(itm):
                    with open(itm, "rb") as f:
                        normalized.append(f.read())
                else:
                    continue
            else:
                continue
        except Exception:
            continue

    if not normalized:
        st.info("No hay imágenes disponibles o no se pudieron leer.")
        return

    idx_key = f"{key_prefix}_idx"
    if idx_key not in st.session_state:
        st.session_state[idx_key] = 0
    i = st.session_state[idx_key] % len(normalized)

    _safe_st_image(normalized[i])

    c1, _, c3 = st.columns(3)
    if c1.button("⏮️", key=f"{key_prefix}_prev"):
        st.session_state[idx_key] = (
            st.session_state[idx_key] - 1) % len(normalized)
        st.rerun()
    if c3.button("⏭️", key=f"{key_prefix}_next"):
        st.session_state[idx_key] = (
            st.session_state[idx_key] + 1) % len(normalized)
        st.rerun()
