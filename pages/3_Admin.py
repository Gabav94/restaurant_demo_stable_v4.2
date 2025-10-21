
# -*- coding: utf-8 -*-
from __future__ import annotations
import streamlit as st
import pandas as pd
from backend.config import get_config, save_config, get_db_path, get_data_dir
from backend.db import get_tenants, create_tenant, create_user, list_faqs, add_faq, delete_faq, verify_login

from backend.db import init_db
init_db(seed=True)  # crea tablas que falten (incluida pendings) y aplica migraciones

st.set_page_config(page_title="Admin", page_icon="🛠️", layout="wide")

cfg = get_config()
st.title("🛠️ Admin")

ss = st.session_state
if "admin_auth" not in ss:
    with st.expander("Iniciar sesión (Admin)"):
        u = st.text_input("Usuario", key="adm_u")
        p = st.text_input("Contraseña", type="password", key="adm_p")
        if st.button("Entrar", key="adm_btn"):
            rec = verify_login(u, p)
            if rec and rec.get("role") == "admin":
                ss.admin_auth = rec
                st.rerun()
            else:
                st.error("Credenciales inválidas o sin rol admin.")
    if "admin_auth" not in ss:
        st.stop()

st.success(f"Admin conectado: {ss.admin_auth['username']} — Tenant: {ss.admin_auth['tenant_slug']}")

st.subheader("Configuración de IA / App")
with st.form("cfg"):
    col1, col2, col3 = st.columns(3)
    with col1:
        language = st.selectbox("Idioma / Language", ["es","en"], index=(0 if cfg.get("language","es")=="es" else 1))
        model = st.text_input("Modelo (OpenAI)", cfg.get("model","gpt-4o-mini"))
        temperature = st.slider("Temperatura", 0.0, 1.2, float(cfg.get("temperature",0.4)), 0.05)
    with col2:
        assistant_name = st.text_input("Nombre del asistente", cfg.get("assistant_name","RAIVA"))
        currency = st.text_input("Moneda", cfg.get("currency","USD"))
        sla_minutes = st.number_input("SLA minutos (alerta)", min_value=5, max_value=240, value=int(cfg.get("sla_minutes",30)))
    with col3:
        tone = st.text_area("Tono del asistente", cfg.get("tone","Amable y profesional; breve, guiado."), height=120)

    if st.form_submit_button("Guardar configuración"):
        save_config({
            "language": language,
            "model": model,
            "temperature": float(temperature),
            "assistant_name": assistant_name,
            "currency": currency,
            "tone": tone,
            "sla_minutes": int(sla_minutes)
        })
        st.success("Guardado. Recarga para aplicar.")

st.write("---")
st.subheader("Tenants y usuarios (ligero)")
tenants = get_tenants()
if tenants:
    st.dataframe(pd.DataFrame(tenants), hide_index=True)
with st.form("new_tenant"):
    st.markdown("**Crear tenant**")
    name = st.text_input("Nombre")
    slug = st.text_input("Slug")
    if st.form_submit_button("Crear tenant"):
        if name and slug:
            create_tenant(name, slug); st.success("Tenant creado."); st.rerun()
        else:
            st.error("Ingresa nombre y slug.")
with st.form("new_user"):
    st.markdown("**Crear usuario**")
    tsel = st.selectbox("Tenant", [f"{t['id']} — {t['name']}" for t in tenants] if tenants else [])
    username = st.text_input("Usuario")
    password = st.text_input("Contraseña", type="password")
    role = st.selectbox("Rol", ["admin","restaurant"])
    if st.form_submit_button("Crear usuario"):
        if tsel and username and password:
            tid = int(tsel.split(" — ")[0])
            create_user(tid, username, password, role); st.success("Usuario creado."); st.rerun()
        else:
            st.error("Completa todos los campos.")

st.write("---")
st.subheader("FAQ por tenant")
lang = cfg.get("language","es")
faqs = list_faqs(ss.admin_auth["tenant_id"], lang)
if faqs:
    st.dataframe(pd.DataFrame(faqs)[["id","pattern","answer"]], hide_index=True)
with st.form("new_faq"):
    st.markdown("**Agregar FAQ (regex)**")
    pattern = st.text_input("Patrón (regex)")
    answer = st.text_area("Respuesta")
    if st.form_submit_button("Agregar"):
        if pattern and answer:
            add_faq(ss.admin_auth["tenant_id"], lang, pattern, answer)
            st.success("FAQ agregada."); st.rerun()
        else:
            st.error("Completa patrón y respuesta.")
del_id = st.text_input("ID FAQ a eliminar")
if st.button("Eliminar FAQ"):
    try:
        delete_faq(int(del_id)); st.success("FAQ eliminada."); st.rerun()
    except Exception as e:
        st.error(f"No se pudo eliminar: {e}")

st.write("---")
st.subheader("Estado")
st.caption(f"DB: {get_db_path()}")
st.caption(f"Data dir: {get_data_dir()}")
st.info("En Cloud usa `st.secrets['OPENAI_API_KEY']`. En local, crea `.env` con `OPENAI_API_KEY=...`.")
