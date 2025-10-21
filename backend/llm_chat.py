# -*- coding: utf-8 -*-
from __future__ import annotations
import difflib as _difflib2
from typing import List, Dict, Optional
import re
import difflib
import streamlit as st

try:
    from openai import OpenAI
except ImportError as e:
    raise ImportError(
        "Falta el paquete 'openai'. Agrega 'openai==1.51.2' a requirements.txt y redeploy.") from e

try:
    from dotenv import dotenv_values
except Exception:
    dotenv_values = lambda *args, **kwargs: {}

from .config import get_config
from .faq import match_faq
from .db import create_pending_question

NUMWORDS_ES = {"uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
               "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
NUMWORDS_EN = {"one": 1, "a": 1, "two": 2, "three": 3, "four": 4,
               "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _get_client() -> OpenAI:
    import os
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(k, None)
    key = st.secrets.get(
        "OPENAI_API_KEY") or dotenv_values().get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Falta OPENAI_API_KEY en .env / secrets")
    return OpenAI(api_key=key)


def _format_price(p) -> str:
    try:
        return f"{float(p):.2f}"
    except Exception:
        return str(p)


def _format_menu(menu: List[Dict]) -> str:
    lines = []
    for it in (menu or [])[:120]:
        name = (it.get("name", "") or "").strip()
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
    tone = cfg.get("tone") or ("Amable y profesional; breve, guiado." if lang ==
                               "es" else "Friendly and professional; concise, guided.")
    assistant_name = cfg.get(
        "assistant_name", "Asistente" if lang == "es" else "Assistant")
    if lang == "es":
        return (
            f"Eres {
                assistant_name}, un asistente de pedidos para un restaurante. Responde SIEMPRE en español.\n"
            f"Tu tono: {tone}\n\n"
            "Objetivo: ayudar al cliente a armar su pedido basado en el menú y confirmar datos.\n"
            "Si detectas petición fuera de menú o una personalización compleja no contemplada, di 'Consultando con cocina...'\n"
            "y espera ~1 minuto la respuesta del restaurante. Si no hay respuesta, aprueba con un precio estimado similar.\n\n"
            "🍽 Menú disponible:\n" + formatted_menu + "\n\n"
            "📌 Comportamiento:\n"
            "- Cálido, claro, paso a paso. No inventes productos/ingredientes.\n"
            "- Personalizaciones fáciles: sin cebolla, salsa aparte, extra papas, poco picante, sin sal, con hielo, limón, ketchup/mayonesa.\n"
            "- Otras personalizaciones → consultar con cocina.\n"
            "- Usa la FAQ interna si hay respuesta registrada.\n"
            "- Lleva un subtotal mientras propone extras.\n\n"
            "🧾 Datos: pide UNO A UNO tras el total:\n"
            "  1) nombre  2) teléfono  3) pickup o delivery  4) dirección (si delivery)  5) método de pago.\n"
            "Para pickup puedes pedir minutos (default 30). Para delivery NO pidas minutos.\n"
            "NO invites a confirmar hasta tener todos los datos.\n\n"
            "✅ Al final: “Pedido listo para confirmación. Presiona el botón Confirmar Pedido.”"
        )
    else:
        return (
            f"You are {
                assistant_name}, a restaurant ordering assistant. ALWAYS respond in Spanish.\n"
            f"Your tone: {tone}\n\n"
            "Goal: help the customer build their order based on the menu and confirm details.\n"
            "If you detect an off-menu request or a complex, non-standard customization, say 'Checking with the kitchen...'\n"
            "and wait ~1 minute for the restaurant’s response. If there’s no response, approve with a similar estimated price.\n\n"
            "🍽 Available menu:\n" + formatted_menu + "\n\n"
            "📌 Behavior:\n"
            "- Warm, clear, and step-by-step. Do not invent products/ingredients.\n"
            "- Easy customizations: no onions, sauce on the side, extra fries, mild spice, no salt, with ice, lemon, ketchup/mayonnaise.\n"
            "- Other customizations → check with the kitchen.\n"
            "- Use the internal FAQ if there’s a registered answer.\n"
            "- Keep a running subtotal while proposing add-ons.\n\n"
            "🧾 Data: ask ONE BY ONE after the total:\n"
            "  1) name  2) phone  3) pickup or delivery  4) address (if delivery)  5) payment method.\n"
            "For pickup you can ask for minutes (default 30). For delivery DO NOT ask for minutes.\n"
            "Do NOT invite to confirm until you have all the data.\n\n"
            "✅ At the end: “Order ready for confirmation. Please press the Confirm button.”"

        )


# Broadened intent tokens (covers “¿Puede ser…?”, “¿Podría…?”, “Quisiera…?”)
_ACTION_TOKENS = {
    "quiero", "pedir", "ordena", "ordenar", "agrega", "agregar", "quitar", "sin", "con", "extra",
    "doble", "triple", "cambiar", "sustituir", "reducir", "añadir", "sumar", "puede", "podria", "podría", "quisiera", "seria", "sería"
}
_EASY_INGREDIENTS = {
    "cebolla", "salsa", "papas", "picante", "sal", "azucar", "azúcar", "hielo", "limon", "limón", "mayonesa", "ketchup"
}


def _build_aliases(menu: List[Dict]) -> Dict[str, str]:
    variants: Dict[str, str] = {}

    def add_alias(alias: str, to_name: str):
        if not alias:
            return
        a = alias.strip().lower()
        if len(a) < 3:
            return
        variants[a] = to_name
        if not a.endswith("s"):
            variants[a+"s"] = to_name
    for m in (menu or []):
        nm = (m.get("name") or "").strip()
        if not nm:
            continue
        low = nm.lower()
        variants[low] = nm
        if not low.endswith("s"):
            variants[low+"s"] = nm
        if low.endswith("a"):
            variants[low[:-1]+"as"] = nm
        if low.endswith("o"):
            variants[low[:-1]+"os"] = nm
        desc = (m.get("description") or "").strip().lower()
        if desc:
            first_tok = re.split(r"\W+", desc)[0] if desc else ""
            add_alias(first_tok, nm)
        notes = (m.get("special_notes") or "")
        if notes:
            for tok in re.split(r"[,\|/]+", notes):
                add_alias(tok, nm)
    return variants


def _should_create_pending(user_text: str, menu: List[Dict]) -> bool:
    """
    Create a pending ONLY when:
      A) Explicit ask to check with restaurant (preguntar/consultar/cocina), OR
      B) A complex customization: 'sin|con|extra|doble|triple' + ingredient NOT in EASY set, OR
      C) Clear off-menu hint words (e.g., 'almíbar', 'durazno(s)', 'canela', etc.) AND those terms
         do not map to any menu alias (i.e., it's not recognized from the menu).
    """
    text_low = (user_text or "").lower()
    tokens = set(re.findall(r"[\wáéíóúñ]+", text_low))

    # A) Explicit ask to check
    if re.search(r"(?i)\b(preguntar|consultar|cocina)\b", text_low):
        return True

    aliases = _build_aliases(menu)

    # B) Complex customization (non-easy ingredient after sin/con/extra/doble/triple)
    mods = re.findall(
        r"(?:\b(?:sin|con|extra|doble|triple)\s+)([\wáéíóúñ]+)", text_low)
    for ing in mods:
        if ing.strip().lower() not in _EASY_INGREDIENTS:
            # If the text mentions at least one menu item or is clearly modifying something,
            # treat as complex and escalate.
            return True

    # C) Off-menu hints (conservative list; expand as needed)
    OFFMENU_HINTS = [
        "almibar", "almíbar", "durazn", "melocoton", "melocotón", "canela",
        "sirope", "almendra", "maracuy", "arándano", "arandano", "tamarindo"
    ]
    has_offmenu_word = any(h in text_low for h in OFFMENU_HINTS)

    # Recognized menu tokens?
    mentioned = []
    for tok in tokens:
        if tok in aliases:
            mentioned.append(aliases[tok])
        else:
            cands = difflib.get_close_matches(
                tok, list(aliases.keys()), n=1, cutoff=0.9)
            if cands:
                mentioned.append(aliases[cands[0]])
    mentioned = list(dict.fromkeys(mentioned))

    # Only consider off-menu pending if we saw an off-menu hint and nothing from the menu matched
    if has_offmenu_word and not mentioned:
        return True

    # Otherwise, do NOT create a pending for generic messages like "hola, quiero ordenar"
    return False


def client_assistant_reply(history: List[Dict], menu: List[Dict], cfg: dict | None, conversation_id: str, tenant_id: Optional[int] = None) -> str:
    cfg = cfg or get_config()
    lang = cfg.get("language", "es")
    last_user = next((m["content"] for m in reversed(
        history) if m.get("role") == "user"), "")

    if last_user and _should_create_pending(last_user, menu):
        try:
            create_pending_question(
                conversation_id=conversation_id, question=last_user, language=lang, ttl_seconds=60)
        except Exception:
            pass
        return ("Entendido, consulto con cocina. Dame ~1 minuto y te confirmo. 🙌"
                if lang == "es" else
                "Got it, checking with the kitchen. Give me ~1 minute and I’ll confirm. 🙌")

    if last_user:
        faq_ans = match_faq(last_user, language=lang, tenant_id=tenant_id)
        if faq_ans:
            return faq_ans

    client = _get_client()
    system = _system_prompt(cfg, menu, lang)
    msgs = [{"role": "system", "content": system}] + history[-12:]
    model = cfg.get("model", "gpt-4o-mini")
    temp = float(cfg.get("temperature", 0.4))
    resp = client.chat.completions.create(
        model=model, temperature=temp, messages=msgs)
    return (resp.choices[0].message.content or "").strip()


# -------- parse_items_from_chat, ensure_all_required_present, extract_client_info (unchanged) --------
def _numbers_in_text(text: str, lang: str) -> Dict[str, int]:
    out = {}
    tokens = re.findall(r"[\wáéíóúñ]+", text.lower())
    m = NUMWORDS_ES if lang == "es" else NUMWORDS_EN
    for tok in tokens:
        if tok.isdigit():
            out[tok] = int(tok)
        elif tok in m:
            out[tok] = m[tok]
    return out


def parse_items_from_chat(history: List[Dict], menu: List[Dict], cfg: dict, lang: str | None = None) -> List[Dict]:
    text_low = "\n".join([m.get("content", "")
                         for m in history if m.get("role") == "user"]).lower()
    names = [m["name"] for m in (menu or []) if m.get("name")]
    price_map = {m["name"]: float(m.get("price", 0.0)) for m in (menu or [])}
    desc_map = {m["name"]: (m.get("description") or "") for m in (menu or [])}
    note_map = {m["name"]: (m.get("special_notes") or "")
                for m in (menu or [])}

    variants = {}

    def add_alias(alias: str, to_name: str):
        if not alias:
            return
        a = alias.strip().lower()
        if len(a) < 3:
            return
        variants[a] = to_name
        if not a.endswith("s"):
            variants[a+"s"] = to_name

    for nm in names:
        low = nm.lower()
        variants[low] = nm
        if not low.endswith("s"):
            variants[low+"s"] = nm
        if low.endswith("a"):
            variants[low[:-1]+"as"] = nm
        if low.endswith("o"):
            variants[low[:-1]+"os"] = nm
        desc = desc_map.get(nm, "")
        if desc:
            first_tok = re.split(r"\W+", desc.lower().strip()
                                 )[0] if desc.strip() else ""
            add_alias(first_tok, nm)
        notes = note_map.get(nm, "")
        if notes:
            for tok in re.split(r"[,\|/]+", notes):
                add_alias(tok, nm)

    from collections import defaultdict
    found = defaultdict(int)
    tokens = re.findall(r"[\wáéíóúñ]+", text_low)
    for tok in tokens:
        if tok in variants:
            found[variants[tok]] += 1

    if not found:
        for tok in set(tokens):
            cands = _difflib2.get_close_matches(
                tok, list(variants.keys()), n=1, cutoff=0.86)
            if cands:
                found[variants[cands[0]]] += 1

    num_map = _numbers_in_text(text_low, (lang or cfg.get("language", "es")))

    def qty_before(name_low: str) -> int:
        pat = rf"(\b(\d+|{'|'.join(num_map.keys())
                          })\s+{re.escape(name_low)}(es|s)?)"
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
        items.append(
            {"name": nm, "qty": q, "unit_price": price_map.get(nm, 0.0)})
    return items


def ensure_all_required_present(info: Dict, lang: str) -> List[str]:
    req = ["name", "phone", "delivery_type", "payment_method"]
    if (info.get("delivery_type") or "").lower() == "delivery":
        req.append("address")
    else:
        req.append("pickup_eta_min")
    missing = [k for k in req if not str(info.get(k, "")).strip()]
    if "pickup_eta_min" in missing and (info.get("delivery_type") or "").lower() == "pickup":
        info["pickup_eta_min"] = 30
        try:
            missing.remove("pickup_eta_min")
        except ValueError:
            pass
    return missing


_NAME_PAT_ES = re.compile(
    r"(?i)(?:me\s+llamo|soy|mi\s+nombre\s*(?:es|:))\s*([A-Za-zÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑ\s]{1,})")
_NAME_PAT_EN = re.compile(
    r"(?i)(?:i\s*am|i'm|my\s+name\s*(?:is|:))\s*([A-Za-z][A-Za-z\s]{1,})")
_PHONE_PAT_HINT = re.compile(r"(?<!\d)(\+?\d[\d\-\s]{6,}\d)(?!\d)")
_PHONE_PAT_LABELED = re.compile(
    r"(?i)(?:tel[eé]fono|phone|cel|cell|m[oó]vil|mobile)\s*(?:es|is|:)?\s*(\+?\d[\d\-\s]{6,}\d)")
_ADDRESS_PAT_ES = re.compile(r"(?i)direcci[oó]n\s*(?:es|:)?\s*(.+)")
_ADDRESS_PAT_EN = re.compile(r"(?i)address\s*(?:is|:)?\s*(.+)")
_MIN_PAT = re.compile(r"(?i)(\d{1,3})\s*(?:min|minute|minutes|minutos)")
_DELIVERY_ES = re.compile(r"(?i)(domicilio|delivery|enviar|entrega)")
_PICKUP_ES = re.compile(r"(?i)(retir|recoger|pickup)")
_DELIVERY_EN = re.compile(r"(?i)(delivery|deliver)")
_PICKUP_EN = re.compile(r"(?i)(pickup|pick up)")


def extract_client_info(history: List[Dict], lang: str) -> Dict:
    text = " \n".join([m.get("content", "")
                      for m in history if m.get("role") == "user"])
    out = {"name": "", "phone": "", "delivery_type": "",
           "address": "", "pickup_eta_min": "", "payment_method": ""}
    m = (_NAME_PAT_ES.search(text) if lang ==
         "es" else _NAME_PAT_EN.search(text))
    if m:
        out["name"] = m.group(1).strip()
    m = _PHONE_PAT_LABELED.search(text) or _PHONE_PAT_HINT.search(text)
    if m:
        import re as _re
        out["phone"] = _re.sub(r"\s+", "", m.group(1)).replace("-", "")
    if (_DELIVERY_ES.search(text) if lang == "es" else _DELIVERY_EN.search(text)):
        out["delivery_type"] = "delivery"
    if (_PICKUP_ES.search(text) if lang == "es" else _PICKUP_EN.search(text)):
        out["delivery_type"] = out["delivery_type"] or "pickup"
    m = (_ADDRESS_PAT_ES.search(text) if lang ==
         "es" else _ADDRESS_PAT_EN.search(text))
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
