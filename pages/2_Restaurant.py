# -*- coding: utf-8 -*-
from __future__ import annotations
import io
import csv
import pandas as pd
import streamlit as st
from backend.utils import render_js_carousel, menu_table_component
from backend.config import get_config
from backend.db import (
    add_menu_item, fetch_menu, delete_menu_item, add_menu_image, fetch_menu_images,
    fetch_orders_queue, update_order_status, bump_priorities_if_sla_missed,
    fetch_pending_questions, answer_pending_question, autoapprove_expired_pendings,
    export_orders_csv, export_pendings_csv, verify_login
)

st.set_page_config(page_title="Restaurante", page_icon="🧑‍🍳", layout="wide")


def _t(lang):
    return (lambda es, en: es if lang == "es" else en)


cfg = get_config()
lang = cfg.get("language", "es")
t = _t(lang)
st.title(t("🧑‍🍳 Restaurante", "🧑‍🍳 Restaurant"))

ss = st.session_state
if "auth_user" not in ss:
    st.subheader(t("Ingresar", "Sign in"))
    u = st.text_input(t("Usuario", "Username"))
    p = st.text_input(t("Contraseña", "Password"), type="password")
    if st.button(t("Entrar", "Sign in")):
        rec = verify_login(u, p)
        if rec:
            ss.auth_user = rec
            st.rerun()
        else:
            st.error(t("Credenciales inválidas", "Invalid credentials"))
    st.stop()

user = st.session_state["auth_user"]
st.caption(t(f"Conectado como {user['username']} (rol: {user['role']}) — Tenant: {user['tenant_slug']}",
             f"Signed in as {user['username']} (role: {user['role']}) — Tenant: {user['tenant_slug']}"))

col1, col2 = st.columns(2)

with col1:
    st.subheader(t("Agregar ítem", "Add item"))
    with st.form("add_item"):
        name = st.text_input(t("Nombre", "Name"))
        desc = st.text_area(t("Descripción", "Description"))
        price = st.number_input(t("Precio", "Price"),
                                min_value=0.0, value=0.0, step=0.1)
        notes = st.text_input(t("Notas especiales (etiquetas)", "Special notes (tags)"),
                              placeholder=t("vegetariano, sin gluten, picante…", "vegetarian, gluten-free, spicy…"))
        if st.form_submit_button(t("Agregar", "Add")):
            if name.strip():
                add_menu_item(name, desc, price, cfg.get(
                    "currency", "USD"), notes)
                st.success("OK")
                st.rerun()
            else:
                st.error(t("El nombre es obligatorio", "Name is required"))

with col2:
    st.subheader(t("Carga masiva (CSV/TXT)", "Bulk upload (CSV/TXT)"))
    up = st.file_uploader(
        t("Subir CSV/TXT", "Upload CSV/TXT"), type=["csv", "txt"])
    if st.button(t("Procesar archivo", "Process file")) and up:
        try:
            content = up.read().decode("utf-8", errors="ignore")
            reader = csv.DictReader(io.StringIO(content))
            current = {m["name"] for m in fetch_menu()}
            added = 0
            for r in reader:
                nm = (r.get("name", "") or "").strip()
                if nm and nm not in current:
                    desc = (r.get("description", "") or "").strip()
                    price = float((r.get("price", "0") or "0"))
                    notes = (r.get("special_notes", "") or "").strip()
                    add_menu_item(nm, desc, price, cfg.get(
                        "currency", "USD"), notes)
                    added += 1
            st.success(t(f"Agregados: {added}", "Added: ") + str(added))
            st.rerun()
        except Exception as e:
            st.error(t("No se pudo procesar el archivo",
                     "Failed to process file") + f": {e}")

    st.caption(t("Imágenes del menú (galería)", "Menu images (gallery)"))
    img_up = st.file_uploader(t("Subir imagen del menú", "Upload menu image"), type=[
                              "png", "jpg", "jpeg"], key="menu_img")
    if st.button(t("Guardar imagen", "Save image")) and img_up:
        add_menu_image(img_up)
        st.success("OK")
        st.rerun()

st.write("---")
view = st.radio(t("Visualización del menú", "Menu view"), [t("Tabla", "Table"), t(
    "Imágenes", "Images")], horizontal=True, key="menu_view_admin")
menu = fetch_menu()
if view == t("Tabla", "Table"):
    menu_table_component(menu, lang, deletable=True,
                         on_delete=delete_menu_item)
else:
    gallery = fetch_menu_images()
    if not gallery:
        st.info(t("No hay imágenes cargadas aún.", "No images uploaded yet."))
    else:
        render_js_carousel(gallery, interval_ms=5000, aspect_ratio=16/6,
                           key_prefix="rest_menu", show_dots=True, height_px=520)

st.write("---")
c1, c2 = st.columns(2)

with c1:
    st.subheader(t("Órdenes", "Orders"))
    bump_priorities_if_sla_missed()
    orders = fetch_orders_queue()
    if not orders:
        st.info(t("No hay órdenes aún.", "No orders yet."))
    else:
        df = pd.DataFrame([{
            "id": o["id"],
            t("creada", "created"): o["created_at"],
            t("cliente", "client"): o["client_name"],
            t("tipo", "type"): o["delivery_type"],
            t("total", "total"): f'{o["currency"]} {o["total"]:0.2f}',
            t("estado", "status"): o["status"],
            t("prioridad", "priority"): o["priority"],
            t("SLA", "SLA"): "⚠️" if o["sla_breached"] else "✅",
        } for o in orders])
        try:
            st.dataframe(df, hide_index=True, width='stretch')
        except TypeError:
            st.dataframe(df, hide_index=True)

        with st.expander(t("Cambiar estado", "Change status")):
            oid = st.selectbox(t("Orden", "Order"), [o["id"] for o in orders])
            newst = st.selectbox(t("Nuevo estado", "New status"), [
                                 "confirmed", "preparing", "ready", "delivered"])
            if st.button(t("Aplicar", "Apply")) and oid:
                update_order_status(oid, newst)
                st.success("OK")
                st.rerun()

        st.download_button(label=t("⬇️ Descargar órdenes (CSV)", "⬇️ Download orders (CSV)"),
                           data=export_orders_csv(), file_name="orders.csv", mime="text/csv")

with c2:
    st.subheader(t("Interacciones por confirmar (1 min)",
                 "Pending interactions (1 min)"))
    autoapprove_expired_pendings()
    pend = fetch_pending_questions()
    if not pend:
        st.info(t("No hay interacciones pendientes.", "No pending interactions."))
    else:
        for p in pend:
            st.markdown(f"**ID:** {p['id']}  \n**Pregunta:** {p['question']}  \n**Idioma:** {
                        p['language']}  \n**Expira:** {p['expires_at']}")
            colA, colB, colC = st.columns(3)
            with colA:
                if st.button(t("Aprobar", "Approve"), key="ap_"+p["id"]):
                    answer_pending_question(p["id"], "approved", t(
                        "Aprobado por cocina.", "Approved by kitchen."))
                    st.success("OK")
                    st.rerun()
            with colB:
                if st.button(t("Negar", "Deny"), key="dn_"+p["id"]):
                    answer_pending_question(p["id"], "denied", t(
                        "No disponible.", "Not available."))
                    st.success("OK")
                    st.rerun()
            with colC:
                msg = st.text_input(t("Mensaje al cliente (opcional)",
                                    "Message to client (optional)"), key="msg_"+p["id"])
                if st.button(t("Responder con mensaje", "Reply with message"), key="rm_"+p["id"]):
                    answer_pending_question(
                        p["id"], "custom", msg or t("Aprobado.", "Approved."))
                    st.success("OK")
                    st.rerun()

        st.download_button(label=t("⬇️ Descargar interacciones (CSV)", "⬇️ Download pendings (CSV)"),
                           data=export_pendings_csv(), file_name="pendings.csv", mime="text/csv")
