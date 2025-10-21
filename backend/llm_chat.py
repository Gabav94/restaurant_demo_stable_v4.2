
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Optional
import json, re, difflib
import streamlit as st

# Hacer el import de ChatOpenAI amigable (mensaje claro si falta la dependencia)
try:
    from langchain_openai import ChatOpenAI
except ImportError as e:
    raise ImportError(
        "Falta el paquete 'langchain-openai'. Agrega 'langchain-openai==0.1.23' a requirements.txt y vuelve a desplegar."
    ) from e

# En Cloud usamos st.secrets; en local, dotenv si existe
try:
    from dotenv import dotenv_values
except Exception:
    dotenv_values = lambda *args, **kwargs: {}

from .config import get_config
from .faq import match_faq
from .db import create_pending_question

NUMWORDS_ES = {"uno":1,"una":1,"dos":2,"tres":3,"cuatro":4,"cinco":5,"seis":6,"siete":7,"ocho":8,"nueve":9,"diez":10}
NUMWORDS_EN = {"one":1,"a":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10}


def _get_llm(cfg: dict) -> ChatOpenAI:
    key = st.secrets.get("OPENAI_API_KEY") or dotenv_values().get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Falta OPENAI_API_KEY en .env / secrets")
    model = cfg.get("model", "gpt-4o-mini")
    temp = float(cfg.get("temperature", 0.4))
    return ChatOpenAI(api_key=key, model=model, temperature=temp)


def _format_price(p) -> str:
    try:
        return f"{float(p):.2f}"
    except Exception:
        return str(p)


def _format_menu(menu: List[Dict]) -> str:
    lines = []
    for it in (menu or [])[:120]:
        name = (it.get("name","") or "").strip()
        if not name: 
            continue
        desc = (it.get("description") or "").strip()
        price = _format_price(it.get("price", 0))
        cur = it.get("currency", "USD")
        notes = (it.get("special_notes") or "").strip()
        notes_txt = f" — [{notes}]" if notes else ""
        line = f"- {name} ({cur} {price}){notes_txt}"
        if desc: 
            line += f"\n  {desc}"
        lines.append(line)
    return "\n".join(lines)

def _system_prompt(cfg: dict, menu: List[Dict], lang: str) -> str:
    formatted_menu = _format_menu(menu)
    tone = cfg.get("tone") or ("Amable y profesional; breve, guiado." if lang=="es" else "Friendly and professional; concise, guided.")
    assistant_name = cfg.get("assistant_name", "Asistente" if lang=="es" else "Assistant")
    if lang == "es":
        return (
            f"Eres {assistant_name}, un asistente de pedidos para un restaurante. Responde SIEMPRE en español.\n"
            f"Tu tono: {tone}\n\n"
            "Objetivo: ayudar al cliente a armar su pedido basado en el menú y confirmar datos. \n"
            "Sugiere acompañantes y bebidas. Si piden algo fuera del menú, pregunta al restaurante si es posible y espera confirmación.\n\n"
            "🍽 Menú disponible:\n" + formatted_menu + "\n\n"
            "📌 Comportamiento:\n"
            "- Cálido, claro, paso a paso. No inventes productos/ingredientes.\n"
            "- Personalizaciones: acepta sin cebolla, salsa aparte, extra papas, etc. Ajusta precio si aplica o la opción del restaurante cuando tengas que pedir confirmación.\n"
            "- Usa la FAQ interna si hay respuesta registrada.\n"
            "- Lleva un subtotal mientras propone extras, ajustes y adicionales.\n\n"
            "🧾 Cuando tengas el pedido y muestres el total, MENCIONA explícitamente:\n"
            "  "Ahora necesito unos datos para completar tu pedido…" y luego pregunta UNO A UNO:\n"
            "  1) nombre  2) teléfono  3) pickup o delivery  4) dirección (si delivery) o minutos de retiro (si pickup)  5) método de pago.\n"
            "NO invites a confirmar hasta tener todos los datos.\n\n"
            "✅ Cuando todo esté completo: "Pedido listo para confirmación. Por favor, presiona el botón Confirmar Pedido."\n"
            "🛑 Si dice "stop", termina con amabilidad.\n"
            "🎯 Estilo: amable, profesional, breve y guiado."
        )
    else:
        return (
            f"You are {assistant_name}, an order assistant for a restaurant. ALWAYS respond in English.\n"
            f"Your tone: {tone}\n\n"
            "Objective: help the customer place their order based on the menu and confirm details. \n"
            "Suggest side dishes and drinks. If they order something off the menu, ask the restaurant if it's possible and wait for confirmation.\n\n"
            "🍽 Available menu:\n” + formatted_menu + "\n\n"
            "📌 Behavior:\n"
            "- Warm, clear, step by step. Do not invent products/ingredients.\n"
            "- Customizations: accept no onions, sauce on the side, extra potatoes, etc. Adjust the price if applicable or the restaurant's option when you have to ask for confirmation.\n"
            "- Use the internal FAQ if there is a recorded answer.\n"
            "- Keep a subtotal while proposing extras, adjustments, and additions.\n\n"
            "🧾 When you have the order and show the total, explicitly MENTION:\n"
            "  "Now I need some information to complete your order..." and then ask ONE BY ONE:\n"
            "  1) name  2) phone number  3) pickup or delivery  4) address (if delivery) or pickup time (if pickup)  5) payment method."
            "DO NOT ask for confirmation until you have all the information."
            "✅ When everything is complete: ”Order ready for confirmation. Please press the Confirm Order button."\n"
            "🛑 If they say "stop," end the call politely.\n"
            "🎯 Style: kind, professional, concise and guided."
        )

def client_assistant_reply(
    history: List[Dict], 
    menu: List[Dict], 
    cfg: dict | None, 
    conversation_id: str, 
    tenant_id: Optional[int] = None
) -> str:
    cfg = cfg or get_config()
    lang = cfg.get("language", "es")
    last_user = next((m["content"] for m in reversed(history) if m.get("role")=="user"), "")

    # FAQ primero
    if last_user:
        faq_ans = match_faq(last_user, language=lang, tenant_id=tenant_id)
        if faq_ans:
            return faq_ans

    llm = _get_llm(cfg)
    sys = _system_prompt(cfg, menu, lang)
    msgs = [{"role":"system","content":sys}] + history[-12:]
    res = llm.invoke(msgs)
    reply = (res.content or "").strip()

    # Si el asistente indica consulta a cocina → marcar pending
    low = reply.lower()
    if ("consultando con cocina" in low) or ("checking with the kitchen" in low):
        try:
            create_pending_question(
                conversation_id=conversation_id, 
                question=last_user, 
                language=lang, 
                ttl_seconds=60
            )
        except Exception:
            pass

    return reply


def _numbers_in_text(text: str, lang: str) -> Dict[str,int]:
    out = {}
    tokens = re.findall(r"[\wáéíóúñ]+", text.lower())
    m = NUMWORDS_ES if lang=="es" else NUMWORDS_EN
    for tok in tokens:
        if tok.isdigit():
            out[tok] = int(tok)
        elif tok in m:
            out[tok] = m[tok]
    return out


def parse_items_from_chat(history: List[Dict], menu: List[Dict], cfg: dict, lang: str | None = None) -> List[Dict]:
    # 1) keyword + plurales; 2) difflib fuzzy (>0.86); 3) cantidades básicas
    text_low = "\n".join([m.get("content","") for m in history if m.get("role")=="user"]).lower()
    names = [m["name"] for m in (menu or []) if m.get("name")]
    price_map = {m["name"]: float(m.get("price",0.0)) for m in (menu or [])}

    # Variantes simples/plurales
    variants = {}
    for nm in names:
        low = nm.lower()
        variants[low] = nm
        if not low.endswith("s"): variants[low+"s"] = nm
        if low.endswith("a"): variants[low[:-1]+"as"] = nm
        if low.endswith("o"): variants[low[:-1]+"os"] = nm

    # Búsqueda por token
    from collections import defaultdict
    found = defaultdict(int)
    tokens = re.findall(r"[\wáéíóúñ]+", text_low)
    for tok in tokens:
        if tok in variants:
            found[variants[tok]] += 1

    # Fuzzy si no hubo match exacto
    if not found:
        for tok in set(tokens):
            cands = difflib.get_close_matches(tok, list(variants.keys()), n=1, cutoff=0.86)
            if cands:
                found[variants[cands[0]]] += 1

    # Cantidades antes del nombre
    num_map = _numbers_in_text(text_low, (lang or cfg.get("language","es")))

    def qty_before(name_low: str) -> int:
        pat = rf"(\b(\d+|{'|'.join(num_map.keys())})\s+{re.escape(name_low)}(es|s)?)"
        m = re.search(pat, text_low)
        if m:
            val = m.group(2)
            if val.isdigit(): 
                return int(val)
            return num_map.get(val, 1)
        return 1

    items = []
    for nm, count in found.items():
        q = max(qty_before(nm.lower()), count)
        items.append({"name": nm, "qty": q, "unit_price": price_map.get(nm, 0.0)})
    return items


def ensure_all_required_present(info: Dict, lang: str) -> List[str]:
    """
    Verifica campos obligatorios para poder confirmar el pedido.
    - Siempre: name, phone, delivery_type, payment_method
    - Si delivery: address
    - Si pickup: pickup_eta_min (si falta, autocompleta 30)
    """
    req = ["name","phone","delivery_type","payment_method"]
    if info.get("delivery_type") == "delivery":
        req.append("address")
    else:
        req.append("pickup_eta_min")
    missing = [k for k in req if not str(info.get(k,"")).strip()]
    if "pickup_eta_min" in missing and info.get("delivery_type") == "pickup":
        info["pickup_eta_min"] = 30
        try:
            missing.remove("pickup_eta_min")
        except ValueError:
            pass
    return missing


# Extracción de datos del cliente desde el historial
_NAME_PAT_ES = re.compile(r"(?i)(?:me\s+llamo|soy|mi\s+nombre\s*(?:es|:))\s*([A-Za-zÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑ\s]{1,})")
_NAME_PAT_EN = re.compile(r"(?i)(?:i\s*am|i'm|my\s+name\s*(?:is|:))\s*([A-Za-z][A-Za-z\s]{1,})")
_PHONE_PAT_HINT = re.compile(r"(?<!\d)(\+?\d[\d\-\s]{6,}\d)(?!\d)")
_PHONE_PAT_LABELED = re.compile(r"(?i)(?:tel[eé]fono|phone|cel|cell|m[oó]vil|mobile)\s*(?:es|is|:)?\s*(\+?\d[\d\-\s]{6,}\d)")
_ADDRESS_PAT_ES = re.compile(r"(?i)direcci[oó]n\s*(?:es|:)?\s*(.+)")
_ADDRESS_PAT_EN = re.compile(r"(?i)address\s*(?:is|:)?\s*(.+)")
_MIN_PAT = re.compile(r"(?i)(\d{1,3})\s*(?:min|minute|minutes|minutos)")
_DELIVERY_ES = re.compile(r"(?i)(domicilio|delivery|enviar|entrega)")
_PICKUP_ES = re.compile(r"(?i)(retir|recoger|pickup)")
_DELIVERY_EN = re.compile(r"(?i)(delivery|deliver)")
_PICKUP_EN = re.compile(r"(?i)(pickup|pick up)")


def extract_client_info(history: List[Dict], lang: str) -> Dict:
    text = " \n".join([m.get("content","") for m in history if m.get("role")=="user"])
    out = {"name":"", "phone":"", "delivery_type":"", "address":"", "pickup_eta_min":"", "payment_method":""}
    m = (_NAME_PAT_ES.search(text) if lang=="es" else _NAME_PAT_EN.search(text))
    if m:
        out["name"] = m.group(1).strip()
    m = _PHONE_PAT_LABELED.search(text) or _PHONE_PAT_HINT.search(text)
    if m:
        import re as _re
        out["phone"] = _re.sub(r"\s+","", m.group(1)).replace("-","")
    if (_DELIVERY_ES.search(text) if lang=="es" else _DELIVERY_EN.search(text)):
        out["delivery_type"] = "delivery"
    if (_PICKUP_ES.search(text) if lang=="es" else _PICKUP_EN.search(text)):
        out["delivery_type"] = out["delivery_type"] or "pickup"
    m = (_ADDRESS_PAT_ES.search(text) if lang=="es" else _ADDRESS_PAT_EN.search(text))
    if m:
        out["address"] = m.group(1).strip()
    m = _MIN_PAT.search(text)
    if m:
        out["pickup_eta_min"] = m.group(1).strip()
    import re as _re2
    if _re2.search(r"(?i)(efectivo|cash)", text):
        out["payment_method"] = "cash"
    elif _re2.search(r"(?i)(tarjeta|card)", text):
        out["payment_method"] = "card"
    elif _re2.search(r"(?i)(online|transfer|transferencia|bank)", text):
        out["payment_method"] = "online"
    return out