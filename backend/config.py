
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json
import streamlit as st

_DEFAULT_CFG = {
    "language": "es",
    "model": "gpt-4o-mini",
    "temperature": 0.4,
    "assistant_name": "RAIVA",
    "tone": "Amable y profesional; breve, guiado.",
    "currency": "USD",
    "sla_minutes": 30
}

def _writable(dir_path: str) -> bool:
    try:
        test_file = os.path.join(dir_path, ".perm_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return True
    except Exception:
        return False

def get_data_dir() -> str:
    candidates = []
    if os.getenv("DATA_DIR"):
        candidates.append(os.getenv("DATA_DIR"))
    candidates.append("/mount/src")
    root = os.getcwd()
    candidates.append(os.path.join(root, "data"))
    candidates.append(root)
    for c in candidates:
        try:
            os.makedirs(c, exist_ok=True)
        except Exception:
            continue
        if _writable(c):
            return c
    fallback = os.path.join(os.getcwd(), "data")
    os.makedirs(fallback, exist_ok=True)
    return fallback

def get_db_path() -> str:
    return os.path.join(get_data_dir(), "app.db")

def get_assets_dir() -> str:
    base = get_data_dir()
    p = os.path.join(base, "assets")
    os.makedirs(p, exist_ok=True)
    return p

def _cfg_path() -> str:
    return os.path.join(get_data_dir(), "config.json")

def get_config() -> dict:
    cfg = dict(_DEFAULT_CFG)
    try:
        s = st.secrets
        if s.get("LANGUAGE"): cfg["language"] = s["LANGUAGE"]
        if s.get("MODEL"): cfg["model"] = s["MODEL"]
        if s.get("TEMPERATURE"): cfg["temperature"] = float(s["TEMPERATURE"])
        if s.get("ASSISTANT_NAME"): cfg["assistant_name"] = s["ASSISTANT_NAME"]
        if s.get("TONE"): cfg["tone"] = s["TONE"]
        if s.get("CURRENCY"): cfg["currency"] = s["CURRENCY"]
        if s.get("SLA_MINUTES"): cfg["sla_minutes"] = int(s["SLA_MINUTES"])
    except Exception:
        pass
    path = _cfg_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                file_cfg = json.load(f)
            cfg.update(file_cfg)
    except Exception:
        pass
    return cfg

def save_config(new_cfg: dict) -> None:
    cfg = get_config()
    cfg.update(new_cfg or {})
    path = _cfg_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
