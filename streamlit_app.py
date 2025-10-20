
# -*- coding: utf-8 -*-
import streamlit as st
from backend.db import init_db
from backend.config import get_db_path, get_data_dir

st.set_page_config(page_title="Restaurant Chat Demo", page_icon="🍽️", layout="wide")

st.title("InnovaChat para Restaurantes · Demo estable")
st.caption("Versión estable mínima (texto, sin audio) — Python 3.12 · Streamlit · SQLite")

init_db(seed=True)

st.success(f"DB inicializada en: {get_db_path()}")
st.info(f"Directorio de datos: {get_data_dir()}")

st.write("---")
st.markdown("### Páginas (menú lateral)")
st.markdown("- **Client** → chat de cliente con sugerencias de LLM y validación de datos.")
st.markdown("- **Restaurant** → gestión de menú, imágenes, órdenes, y pendientes (**con login**).")
st.markdown("- **Admin** → configuración, tenants/usuarios y FAQ (**con login**).")
