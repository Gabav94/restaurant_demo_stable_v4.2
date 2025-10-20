
# -*- coding: utf-8 -*-
from __future__ import annotations
import re
from typing import Optional
from .db import list_faqs

DEFAULT_FAQ = {
    "es": [
        (r"horario|abren|cierran", "Nuestro horario es de 11:00 a 22:00, todos los días."),
        (r"\bdelivery\b|domicilio", "Hacemos delivery en un radio de 5 km. Costo según distancia."),
    ],
    "en": [
        (r"hours|open|close", "We open 11:00 to 22:00, every day."),
        (r"delivery", "We deliver within 5 km radius. Cost varies by distance."),
    ]
}

def match_faq(user_text: str, language: str = "es", tenant_id: Optional[int] = None) -> str | None:
    text = (user_text or "").lower()
    faqs = []
    try:
        faqs = [(r["pattern"], r["answer"]) for r in list_faqs(tenant_id, language)]
    except Exception:
        pass
    if not faqs:
        faqs = DEFAULT_FAQ.get(language, [])
    for pat, ans in faqs:
        try:
            if re.search(pat, text):
                return ans
        except re.error:
            continue
    return None
