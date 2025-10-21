# -*- coding: utf-8 -*-
from __future__ import annotations
import re
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

# Reset conversation
if st.button(t("🗑️ Nuevo chat", "🗑️ New chat"), help=t("Reinicia esta conversación.", "Reset this conversation.")):
    for k in ["conv_id", "conv", "client_info", "order_items", "collecting_info", "last_question_field", "prompted_confirm", "asked_for_data", "awaiting_more_confirmation"]:
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
    ss.conv = [{"role": "assistant", "content": t(
        "Gracias por comunicarte con nosotros. ¿Cómo podemos ayudarte?", "Thanks for contacting us. How can we help?")}]
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
if "awaiting_more_confirmation" not in ss:
    ss.awaiting_more_confirmation = False

# Pending banner
if has_pending_for_conversation(ss.conv_id):
    st.warning(t("⏳ Consultando con cocina… te confirmamos en ~1 minuto.",
               "⏳ Checking with the kitchen… we’ll confirm within ~1 minute."))

# Inject kitchen decisions
for d in fetch_unnotified_decisions(ss.conv_id):
    status = (d["status"] or "").lower()
    msg = d.get("answer") or ""
    if status == "approved":
        text = t("✅ Cocina aprobó la solicitud. Procedemos.",
                 "✅ Kitchen approved the request. Proceeding.")
    elif status == "denied":
        text = t("❌ Cocina no aprobó la solicitud. Elige otra opción, por favor.",
                 "❌ Kitchen did not approve. Please choose another option.")
    else:
        text = msg or t("Actualización de cocina recibida.",
                        "Kitchen replied.")
    if msg:
        text += f" {msg}"
    ss.conv.append({"role": "assistant", "content": text})
    mark_pending_notified(d["id"])

# UI
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
        st.chat_message("user" if m["role"] ==
                        "user" else "assistant").write(m["content"])

    user_text = st.chat_input(t("Escribe tu mensaje…", "Type your message…"))
    if user_text:
        ut = user_text.strip()
        ss.conv.append({"role": "user", "content": ut})

        # 1) If we are collecting data and we asked a field, capture it DIRECTLY (no regex)
        if ss.collecting_info and ss.last_question_field:
            fld = ss.last_question_field
            val = ut
            # tiny normalizations for some fields
            if fld == "phone":
                val = re.sub(r"\D+", "", val)
            elif fld == "delivery_type":
                low = val.lower()
                if "pick" in low or "recog" in low or "reti" in low:
                    val = "pickup"
                elif "deliver" in low or "domi" in low or "env" in low:
                    val = "delivery"
            elif fld == "pickup_eta_min":
                m = re.search(r"(\d{1,3})", val)
                val = m.group(1) if m else "30"
            elif fld == "payment_method":
                low = val.lower()
                if "efect" in low or "cash" in low:
                    val = "cash"
                elif "tarj" in low or "card" in low:
                    val = "card"
                else:
                    val = "online"
            ss.client_info[fld] = val.strip()
            ss.last_question_field = None

            # Ask next missing (or finish)
            missing_seq = ensure_all_required_present(ss.client_info, lang)

            def q(field: str) -> str:
                prompts = {
                    "name": ("¿Cuál es tu nombre?" if lang == "es" else "What is your name?"),
                    "phone": ("¿Cuál es tu número de teléfono?" if lang == "es" else "What is your phone number?"),
                    "delivery_type": ("¿Será para recoger (pickup) o entrega a domicilio?" if lang == "es" else "Pickup or delivery?"),
                    "address": ("¿Cuál es la dirección para la entrega?" if lang == "es" else "What is the delivery address?"),
                    "pickup_eta_min": ("¿En cuántos minutos pasarías a recoger?" if lang == "es" else "In how many minutes would you pick up?"),
                    "payment_method": ("¿Cuál es tu método de pago (efectivo, tarjeta u online)?" if lang == "es" else "What is your payment method (cash, card, online)?"),
                }
                if (ss.client_info.get("delivery_type") or "").lower() == "delivery" and field == "pickup_eta_min":
                    return ""
                return prompts[field]

            if missing_seq:
                nxt = q(missing_seq[0])
                if nxt:
                    ss.conv.append({"role": "assistant", "content": nxt})
                    ss.last_question_field = missing_seq[0]
            else:
                ss.collecting_info = False
                if not ss.prompted_confirm:
                    ss.conv.append({"role": "assistant", "content": t(
                        "Pedido listo para confirmación. Por favor, presiona el botón **Confirmar**.",
                        "Order ready for confirmation. Please press the **Confirm** button."
                    )})
                    ss.prompted_confirm = True

            st.rerun()

        # 2) Regular assistant reply (suggestions, subtotal, etc.)
        reply = client_assistant_reply(
            ss.conv, menu, cfg, conversation_id=ss.conv_id)
        ss.conv.append({"role": "assistant", "content": reply})

        # Extract info + items for subtotal
        info_auto = extract_client_info(ss.conv, lang)
        ss.client_info.update({k: v for k, v in info_auto.items() if v})
        ss.order_items = parse_items_from_chat(ss.conv, menu, cfg, lang=lang)

        # Ask “anything else?” if we haven't asked yet
        if not ss.collecting_info and not ss.asked_for_data and not ss.awaiting_more_confirmation:
            ss.conv.append({"role": "assistant", "content": t(
                "¿Deseas agregar algo más o eso es todo?", "Would you like anything else, or is that all?")})
            ss.awaiting_more_confirmation = True
            st.rerun()

        # If user says it's all, start data phase (ONLY then)
        if ss.awaiting_more_confirmation:
            low = ut.lower()
            done_tokens = ["eso sería todo", "eso es todo", "nada más", "listo", "no, gracias", "no gracias", "ya no",
                           "that's all", "nothing else", "no thanks", "i'm done", "done"]
            if any(tok in low for tok in done_tokens):
                ss.awaiting_more_confirmation = False
                ss.collecting_info = True
                ss.asked_for_data = True
                pre = t("Perfecto. Ahora necesito unos datos para completar tu pedido. Te los pediré uno a uno.",
                        "Great. I now need a few details to complete your order. I'll ask them one by one.")
                ss.conv.append({"role": "assistant", "content": pre})
                # Start with the first missing
                missing_seq = ensure_all_required_present(ss.client_info, lang)
                order = ["name", "phone", "delivery_type",
                         "address", "pickup_eta_min", "payment_method"]
                for f in order:
                    if f in missing_seq:
                        first_q = {
                            "name": t("¿Cuál es tu nombre?", "What is your name?"),
                            "phone": t("¿Cuál es tu número de teléfono?", "What is your phone number?"),
                            "delivery_type": t("¿Será para recoger (pickup) o entrega a domicilio?", "Pickup or delivery?"),
                            "address": t("¿Cuál es la dirección para la entrega?", "What is the delivery address?"),
                            "pickup_eta_min": t("¿En cuántos minutos pasarías a recoger?", "In how many minutes would you pick up?"),
                            "payment_method": t("¿Cuál es tu método de pago (efectivo, tarjeta u online)?", "What is your payment method (cash, card, online)?"),
                        }[f]
                        # If delivery, skip pickup minutes
                        if (ss.client_info.get("delivery_type") or "").lower() == "delivery" and f == "pickup_eta_min":
                            continue
                        ss.conv.append(
                            {"role": "assistant", "content": first_q})
                        ss.last_question_field = f
                        break
                st.rerun()

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
