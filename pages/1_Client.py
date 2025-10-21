# -*- coding: utf-8 -*-
from __future__ import annotations
import streamlit as st
from uuid import uuid4

from backend.utils import render_js_carousel, menu_table_component
from backend.config import get_config
from backend.db import (
    fetch_menu, fetch_menu_images, create_order_from_chat_ready,
    has_pending_for_conversation, fetch_unnotified_decisions,
    mark_pending_notified
)
from backend.llm_chat import (
    client_assistant_reply,
    extract_client_info,
    ensure_all_required_present,
    parse_items_from_chat
)

st.set_page_config(page_title="Cliente", page_icon="💬", layout="wide")


def _t(lang: str):
    return (lambda es, en: es if lang == "es" else en)


cfg = get_config()
lang = cfg.get("language", "es")
t = _t(lang)
currency = cfg.get("currency", "USD")

st.title(t("💬 Cliente", "💬 Client"))

# Botón "Nuevo chat" sin recargar la página entera
if st.button(t("🗑️ Nuevo chat", "🗑️ New chat"), help=t("Reinicia esta conversación.", "Reset this conversation.")):
    for k in ["conv_id", "conv", "client_info", "order_items", "collecting_info", "last_question_field", "prompted_confirm", "asked_for_data", "last_notified_ids"]:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

menu = fetch_menu()
if not menu:
    st.warning(t("El restaurante aún no ha cargado su menú.",
               "The restaurant has not uploaded its menu yet."))
    st.stop()

ss = st.session_state
if "conv_id" not in ss:
    ss.conv_id = uuid4().hex
if "conv" not in ss:
    ss.conv = [{
        "role": "assistant",
        "content": t("Gracias por comunicarte con nosotros. ¿Cómo podemos ayudarte?",
                     "Thanks for contacting us. How can we help?")
    }]
if "client_info" not in ss:
    ss.client_info = {}
if "order_items" not in ss:
    ss.order_items = []
if "collecting_info" not in ss:
    ss.collecting_info = False
if "last_question_field" not in ss:
    ss.last_question_field = None
if "prompted_confirm" not in ss:
    ss.prompted_confirm = False
if "asked_for_data" not in ss:
    ss.asked_for_data = False
if "last_notified_ids" not in ss:
    ss.last_notified_ids = set()

# Banner de pendientes
if has_pending_for_conversation(ss.conv_id):
    st.warning(t("⏳ Consultando con cocina… te confirmamos en ~1 minuto.",
                 "⏳ Checking with the kitchen… we’ll confirm within ~1 minute."))

# Inyectar decisiones del restaurante no notificadas
decisions = fetch_unnotified_decisions(ss.conv_id)
for d in decisions:
    status = (d["status"] or "").lower()
    msg = d.get("answer") or ""
    if status == "approved":
        text = t("✅ Cocina aprobó la solicitud. Procedemos.",
                 "✅ Kitchen approved the request. Proceeding.")
        if msg:
            text += f" {msg}"
    elif status == "denied":
        text = t("❌ Cocina no aprobó la solicitud. Elige otra opción, por favor.",
                 "❌ Kitchen did not approve. Please choose another option.")
        if msg:
            text += f" {msg}"
    else:
        text = msg or t("Actualización de cocina recibida.",
                        "Kitchen replied.")
    ss.conv.append({"role": "assistant", "content": text})
    mark_pending_notified(d["id"])

# UI: menú
view = st.radio(t("Visualización del menú", "Menu view"), [
                t("Tabla", "Table"), t("Imágenes", "Images")], horizontal=True)
col_menu, col_chat = st.columns([1, 1])

with col_menu:
    st.subheader(t("📖 Menú", "📖 Menu"))
    if view == t("Tabla", "Table"):
        menu_table_component(menu, lang)
    else:
        gallery = fetch_menu_images()
        if not gallery:
            st.info(t("No hay imágenes cargadas aún.", "No images uploaded yet."))
        else:
            render_js_carousel(gallery, interval_ms=5000, aspect_ratio=16/7,
                               key_prefix="client_menu", show_dots=True, height_px=520)

with col_chat:
    for m in ss.conv:
        if m["role"] == "user":
            st.chat_message("user").write(m["content"])
        else:
            st.chat_message("assistant").write(m["content"])

    user_text = st.chat_input(t("Escribe tu mensaje…", "Type your message…"))
    if user_text:
        ut = user_text.strip()
        ss.conv.append({"role": "user", "content": ut})

        reply = client_assistant_reply(
            ss.conv, menu, cfg, conversation_id=ss.conv_id)
        ss.conv.append({"role": "assistant", "content": reply})

        # Extraer info y parsear items
        info = extract_client_info(ss.conv, lang)
        ss.client_info.update({k: v for k, v in info.items() if v})
        ss.order_items = parse_items_from_chat(ss.conv, menu, cfg, lang=lang)

        # Heurística: ¿debemos pasar a pedir datos?
        def looks_like_total_trigger(text: str) -> bool:
            low = (text or "").lower()
            if "subtotal" in low:
                return False
            return any(tok in low for tok in ["total", "precio", "price", "usd", "$"])

        def user_closed_intent(text: str) -> bool:
            low = (text or "").lower()
            tokens = ["eso sería todo", "nada más", "listo", "confirmar", "confirmo", "eso es todo",
                      "that's all", "nothing else", "done", "confirm"]
            return any(tk in low for tk in tokens)

        last_assistant = next((m["content"] for m in reversed(
            ss.conv) if m["role"] == "assistant"), "")
        should_collect = ss.order_items and (
            looks_like_total_trigger(last_assistant) or user_closed_intent(ut))

        # Disparar bloque de datos solo una vez
        if should_collect and not ss.asked_for_data:
            pre = ("Ahora necesito unos datos para completar tu pedido. Te los pediré uno a uno"
                   if lang == "es" else
                   "I now need a few details to complete your order. I'll ask for them one by one")
            ss.conv.append({"role": "assistant", "content": pre})
            ss.collecting_info = True
            ss.last_question_field = None
            ss.asked_for_data = True

        if ss.collecting_info:
            missing_seq = ensure_all_required_present(ss.client_info, lang)

            def next_question(field: str, lang: str, info: dict) -> str:
                prompts = {
                    "name": ("¿Cuál es tu nombre?" if lang == "es" else "What is your name?"),
                    "phone": ("¿Cuál es tu número de teléfono?" if lang == "es" else "What is your phone number?"),
                    "delivery_type": ("¿Será para recoger (pickup) o entrega a domicilio?" if lang == "es" else "Pickup or delivery?"),
                    "address": ("¿Cuál es la dirección para la entrega?" if lang == "es" else "What is the delivery address?"),
                    "pickup_eta_min": ("¿En cuántos minutos pasarías a recoger?" if lang == "es" else "In how many minutes would you pick up?"),
                    "payment_method": ("¿Cuál es tu método de pago (efectivo, tarjeta u online)?" if lang == "es" else "What is your payment method (cash, card, online)?"),
                }
                if (info.get("delivery_type") or "").lower() == "delivery" and field == "pickup_eta_min":
                    return ""
                return prompts[field]

            if missing_seq:
                nf = missing_seq[0]
                q = next_question(nf, lang, ss.client_info)
                if q:
                    ss.conv.append({"role": "assistant", "content": q})
                    ss.last_question_field = nf
            else:
                ss.last_question_field = None
                ss.collecting_info = False
                if not ss.prompted_confirm:
                    msg = ("Pedido listo para confirmación. Por favor, presiona el botón **Confirmar**."
                           if lang == "es" else
                           "Order ready for confirmation. Please press the **Confirm** button.")
                    ss.conv.append({"role": "assistant", "content": msg})
                    ss.prompted_confirm = True

        st.rerun()

st.write("---")
missing = ensure_all_required_present(
    st.session_state.get("client_info", {}), lang)
label_map_es = {"name": "nombre", "phone": "teléfono", "delivery_type": "tipo de entrega",
                "payment_method": "método de pago", "address": "dirección", "pickup_eta_min": "tiempo de retiro (min)"}
label_map_en = {"name": "name", "phone": "phone", "delivery_type": "delivery type",
                "payment_method": "payment method", "address": "address", "pickup_eta_min": "pickup ETA (min)"}
lm = label_map_es if lang == "es" else label_map_en
miss_str = ", ".join([lm[m] for m in missing])

left, right = st.columns([2, 1])
with left:
    if missing:
        st.warning((f"Faltan datos para confirmar: {
                   miss_str}." if lang == "es" else f"Missing fields: {miss_str}."))
    else:
        st.success(t("Tenemos todos los datos. Puedes confirmar.",
                   "All data present. You can confirm."))
        if st.session_state.get("order_items"):
            st.caption(t("Items detectados: ", "Detected items: ") + "; ".join(
                [f"{i['name']} x{i['qty']}" for i in st.session_state["order_items"]]))

with right:
    if st.button(t("✅ Confirmar pedido", "✅ Confirm order")):
        if missing:
            st.error((f"No se puede confirmar. Falta: {
                     miss_str}" if lang == "es" else f"Cannot confirm. Missing: {miss_str}"))
        else:
            create_order_from_chat_ready(client=st.session_state.get("client_info", {}),
                                         items=st.session_state.get(
                                             "order_items", []),
                                         currency=currency)
            st.session_state.conv.append({"role": "assistant", "content": t(
                "¡Pedido confirmado! Lo estamos preparando 🚗💨 si es a domicilio, o listo según tu hora de retiro.",
                "Order confirmed! We're on it 🚗💨 for delivery, or ready at your pickup time."
            )})
            st.success(t("¡Pedido confirmado!", "Order confirmed!"))
            st.rerun()
