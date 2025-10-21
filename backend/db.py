# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import json
import sqlite3
import time
import io
import csv
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from .config import get_db_path, get_config, get_assets_dir


def _conn():
    path = get_db_path()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _col_exists(c: sqlite3.Connection, table: str, col: str) -> bool:
    cur = c.execute(f"PRAGMA table_info({table})")
    return any(r["name"] == col for r in cur.fetchall())


def _ensure_schema_migrations(c: sqlite3.Connection):
    # pendings.conversation_id
    if not _col_exists(c, "pendings", "conversation_id"):
        try:
            c.execute("ALTER TABLE pendings ADD COLUMN conversation_id TEXT")
        except Exception:
            pass
    # orders.phone
    if not _col_exists(c, "orders", "phone"):
        try:
            c.execute("ALTER TABLE orders ADD COLUMN phone TEXT")
        except Exception:
            pass
    # orders.delivery_type
    if not _col_exists(c, "orders", "delivery_type"):
        try:
            c.execute("ALTER TABLE orders ADD COLUMN delivery_type TEXT")
        except Exception:
            pass
    # SLA columns
    if not _col_exists(c, "orders", "sla_deadline"):
        try:
            c.execute("ALTER TABLE orders ADD COLUMN sla_deadline TEXT")
        except Exception:
            pass
    if not _col_exists(c, "orders", "sla_breached"):
        try:
            c.execute(
                "ALTER TABLE orders ADD COLUMN sla_breached INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
    # pendings.notified (para que Client sepa si ya mostró la decisión)
    if not _col_exists(c, "pendings", "notified"):
        try:
            c.execute(
                "ALTER TABLE pendings ADD COLUMN notified INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass


def init_db(seed: bool = True):
    c = _conn()
    cur = c.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS menu_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        description TEXT,
        price REAL NOT NULL DEFAULT 0.0,
        currency TEXT NOT NULL DEFAULT 'USD',
        special_notes TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS menu_images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT,
        created_at TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id TEXT PRIMARY KEY,
        client_name TEXT,
        phone TEXT,
        delivery_type TEXT,
        address TEXT,
        pickup_eta_min INTEGER,
        payment_method TEXT,
        items_json TEXT NOT NULL,
        total REAL NOT NULL,
        currency TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        priority INTEGER NOT NULL DEFAULT 0,
        sla_deadline TEXT,
        sla_breached INTEGER NOT NULL DEFAULT 0
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pendings (
        id TEXT PRIMARY KEY,
        conversation_id TEXT,
        question TEXT NOT NULL,
        language TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        answer TEXT,
        notified INTEGER NOT NULL DEFAULT 0
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tenants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        slug TEXT UNIQUE
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id INTEGER,
        username TEXT,
        pass_hash TEXT,
        salt TEXT,
        role TEXT,
        UNIQUE(tenant_id, username)
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS faqs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id INTEGER,
        language TEXT NOT NULL DEFAULT 'es',
        pattern TEXT NOT NULL,
        answer TEXT NOT NULL
    )""")
    c.commit()
    _ensure_schema_migrations(c)
    if seed:
        cur.execute("SELECT COUNT(*) AS n FROM menu_items")
        if cur.fetchone()["n"] == 0:
            from .config import get_config
            curx = get_config().get("currency", "USD")
            for (nm, desc, pr, notes) in [
                ("Hamburguesa", "Clásica con queso", 5.50, ""),
                ("Agua", "Botella 500 ml", 1.00, ""),
                ("Postre", "Brownie de chocolate", 3.25, "brownie, dulce"),
            ]:
                try:
                    cur.execute("INSERT INTO menu_items(name, description, price, currency, special_notes) VALUES (?,?,?,?,?)",
                                (nm, desc, pr, curx, notes))
                except Exception:
                    pass
        cur.execute("SELECT COUNT(*) AS n FROM tenants")
        if cur.fetchone()["n"] == 0:
            cur.execute("INSERT INTO tenants(name, slug) VALUES (?,?)",
                        ("Demo Restaurant", "demo"))
            tenant_id = cur.lastrowid
            salt = secrets.token_hex(8)
            admin_pass = "admin"
            h = hashlib.sha256((salt + admin_pass).encode()).hexdigest()
            cur.execute("INSERT INTO users(tenant_id, username, pass_hash, salt, role) VALUES (?,?,?,?,?)",
                        (tenant_id, "admin", h, salt, "admin"))
            rest_pass = "rest"
            h2 = hashlib.sha256((salt + rest_pass).encode()).hexdigest()
            cur.execute("INSERT INTO users(tenant_id, username, pass_hash, salt, role) VALUES (?,?,?,?,?)",
                        (tenant_id, "rest", h2, salt, "restaurant"))
        cur.execute("SELECT COUNT(*) AS n FROM faqs")
        if cur.fetchone()["n"] == 0:
            cur.execute("SELECT id FROM tenants WHERE slug='demo'")
            row = cur.fetchone()
            tenant_id = row["id"] if row else None
            faqs = [
                (tenant_id, "es", r"horario|abren|cierran",
                 "Nuestro horario es de 11:00 a 22:00, todos los días."),
                (tenant_id, "es", r"\bdelivery\b|domicilio",
                 "Hacemos delivery en un radio de 5 km. Costo según distancia."),
                (tenant_id, "en", r"hours|open|close",
                 "We open 11:00 to 22:00, every day."),
                (tenant_id, "en", r"delivery",
                 "We deliver within 5 km radius. Cost varies by distance."),
            ]
            cur.executemany(
                "INSERT INTO faqs(tenant_id, language, pattern, answer) VALUES (?,?,?,?)", faqs)
    c.commit()
    c.close()

# Menu


def fetch_menu() -> List[Dict[str, Any]]:
    c = _conn()
    rows = c.execute(
        "SELECT id, name, description, price, currency, special_notes FROM menu_items ORDER BY id ASC").fetchall()
    c.close()
    return [dict(r) for r in rows]


def add_menu_item(name: str, desc: str, price: float, currency: str, notes: str):
    c = _conn()
    c.execute("INSERT OR REPLACE INTO menu_items(name, description, price, currency, special_notes) VALUES (?,?,?,?,?)",
              (name.strip(), desc.strip(), float(price), currency, notes.strip()))
    c.commit()
    c.close()


def delete_menu_item(name: str):
    c = _conn()
    c.execute("DELETE FROM menu_items WHERE name = ?", (name,))
    c.commit()
    c.close()


def add_menu_image(file):
    assets = get_assets_dir()
    import time
    import os
    ts = int(time.time()*1000)
    ext = ""
    try:
        name = getattr(file, "name", "")
        ext = os.path.splitext(name)[1].lower()
    except Exception:
        pass
    if ext not in [".png", ".jpg", ".jpeg"]:
        ext = ".png"  # fallback
    out_path = os.path.join(assets, f"img_{ts}{ext}")
    try:
        file.seek(0)
    except Exception:
        pass
    with open(out_path, "wb") as f:
        f.write(file.read())
    c = _conn()
    c.execute("INSERT INTO menu_images(file_path, created_at) VALUES (?,?)",
              (out_path, datetime.utcnow().isoformat()))
    c.commit()
    c.close()
    return out_path


def fetch_menu_images() -> List[str]:
    c = _conn()
    rows = c.execute(
        "SELECT file_path FROM menu_images ORDER BY id DESC").fetchall()
    c.close()
    return [r["file_path"] for r in rows]

# Orders


def create_order_from_chat_ready(client: Dict[str, Any], items: List[Dict[str, Any]], currency: str) -> Dict[str, Any]:
    if not items:
        raise ValueError("No items to create order.")
    total = 0.0
    for it in items:
        total += float(it.get("unit_price", 0.0)) * int(it.get("qty", 1))
    order_id = f"ord_{int(time.time()*1000)}"
    status = "confirmed"
    created_at = datetime.utcnow().isoformat()
    cfg = get_config()
    sla_deadline = (datetime.utcnow(
    ) + timedelta(minutes=int(cfg.get("sla_minutes", 30)))).isoformat()
    row = {
        "id": order_id,
        "client_name": client.get("name", ""),
        "phone": client.get("phone", ""),
        "delivery_type": client.get("delivery_type", ""),
        "address": client.get("address", ""),
        "pickup_eta_min": int(client.get("pickup_eta_min") or 0),
        "payment_method": client.get("payment_method", ""),
        "items_json": json.dumps(items, ensure_ascii=False),
        "total": round(total, 2),
        "currency": currency,
        "status": status,
        "created_at": created_at,
        "priority": 0,
        "sla_deadline": sla_deadline,
        "sla_breached": 0
    }
    c = _conn()
    c.execute("""INSERT INTO orders
        (id, client_name, phone, delivery_type, address, pickup_eta_min, payment_method,
         items_json, total, currency, status, created_at, priority, sla_deadline, sla_breached)
         VALUES (:id,:client_name,:phone,:delivery_type,:address,:pickup_eta_min,:payment_method,
                 :items_json,:total,:currency,:status,:created_at,:priority,:sla_deadline,:sla_breached)""", row)
    c.commit()
    c.close()
    return row


def fetch_orders_queue() -> List[Dict[str, Any]]:
    c = _conn()
    rows = c.execute("""SELECT * FROM orders
                       ORDER BY sla_breached DESC, priority DESC, created_at ASC""").fetchall()
    c.close()
    return [dict(r) for r in rows]


def update_order_status(order_id: str, new_status: str):
    c = _conn()
    c.execute("UPDATE orders SET status = ? WHERE id = ?",
              (new_status, order_id))
    c.commit()
    c.close()


def bump_priorities_if_sla_missed():
    now = datetime.utcnow().isoformat()
    c = _conn()
    c.execute("""UPDATE orders
                 SET sla_breached = 1, priority = priority + 1
                 WHERE sla_deadline IS NOT NULL AND sla_deadline < ? AND status != 'delivered'""", (now,))
    c.commit()
    c.close()

# Pendings


def create_pending_question(conversation_id: str, question: str, language: str, ttl_seconds: int = 60):
    from uuid import uuid4
    pid = f"pend_{uuid4().hex[:8]}"
    created = datetime.utcnow()
    expires = created + timedelta(seconds=ttl_seconds)
    row = {
        "id": pid,
        "conversation_id": conversation_id,
        "question": question or "",
        "language": language or "es",
        "created_at": created.isoformat(),
        "expires_at": expires.isoformat(),
        "status": "pending",
        "answer": None,
        "notified": 0
    }
    c = _conn()
    c.execute("""INSERT INTO pendings(id, conversation_id, question, language, created_at, expires_at, status, answer, notified)
                 VALUES(:id,:conversation_id,:question,:language,:created_at,:expires_at,:status,:answer,:notified)""", row)
    c.commit()
    c.close()
    return row


def fetch_pending_questions() -> List[Dict[str, Any]]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM pendings WHERE status = 'pending' ORDER BY expires_at ASC").fetchall()
    c.close()
    return [dict(r) for r in rows]


def fetch_unnotified_decisions(conversation_id: str) -> List[Dict[str, Any]]:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM pendings WHERE conversation_id = ? AND status != 'pending' AND notified = 0 ORDER BY created_at ASC",
        (conversation_id,)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def mark_pending_notified(pending_id: str):
    c = _conn()
    c.execute("UPDATE pendings SET notified = 1 WHERE id = ?", (pending_id,))
    c.commit()
    c.close()


def has_pending_for_conversation(conv_id: str) -> bool:
    c = _conn()
    rows = c.execute(
        "SELECT COUNT(*) AS n FROM pendings WHERE conversation_id = ? AND status = 'pending'", (conv_id,)).fetchone()
    c.close()
    return (rows["n"] or 0) > 0


def answer_pending_question(pending_id: str, status: str, answer: str = ""):
    c = _conn()
    c.execute("UPDATE pendings SET status = ?, answer = ? WHERE id = ?",
              (status, answer, pending_id))
    c.commit()
    c.close()


def autoapprove_expired_pendings():
    now = datetime.utcnow().isoformat()
    c = _conn()
    c.execute("""UPDATE pendings SET status = 'approved', answer = 'Auto-aprobado por timeout'
                 WHERE status = 'pending' AND expires_at < ?""", (now,))
    c.commit()
    c.close()

# CSV exports


def export_orders_csv() -> str:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM orders ORDER BY created_at DESC").fetchall()
    c.close()
    output = io.StringIO()
    writer = csv.writer(output)
    if rows:
        writer.writerow(rows[0].keys())
        for r in rows:
            writer.writerow([r[k] for k in rows[0].keys()])
    return output.getvalue()


def export_pendings_csv() -> str:
    c = _conn()
    rows = c.execute(
        "SELECT * FROM pendings ORDER BY created_at DESC").fetchall()
    c.close()
    output = io.StringIO()
    writer = csv.writer(output)
    if rows:
        writer.writerow(rows[0].keys())
        for r in rows:
            writer.writerow([r[k] for k in rows[0].keys()])
    return output.getvalue()

# Auth


def _hash_pw(pw: str, salt: str) -> str:
    return hashlib.sha256((salt + pw).encode()).hexdigest()


def verify_login(username: str, password: str) -> Optional[Dict[str, Any]]:
    c = _conn()
    row = c.execute("SELECT users.*, tenants.name as tenant_name, tenants.slug as tenant_slug FROM users JOIN tenants ON users.tenant_id = tenants.id WHERE username = ?", (username,)).fetchone()
    if not row:
        c.close()
        return None
    if _hash_pw(password, row["salt"]) == row["pass_hash"]:
        out = dict(row)
        c.close()
        return out
    c.close()
    return None

# FAQ CRUD


def list_faqs(tenant_id: Optional[int], lang: str) -> List[Dict[str, Any]]:
    c = _conn()
    if tenant_id:
        rows = c.execute(
            "SELECT * FROM faqs WHERE tenant_id = ? AND language = ? ORDER BY id ASC", (tenant_id, lang)).fetchall()
    else:
        rows = c.execute(
            "SELECT * FROM faqs WHERE tenant_id IS NULL AND language = ? ORDER BY id ASC", (lang,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def add_faq(tenant_id: Optional[int], language: str, pattern: str, answer: str):
    c = _conn()
    c.execute("INSERT INTO faqs(tenant_id, language, pattern, answer) VALUES (?,?,?,?)",
              (tenant_id, language, pattern, answer))
    c.commit()
    c.close()


def delete_faq(faq_id: int):
    c = _conn()
    c.execute("DELETE FROM faqs WHERE id = ?", (faq_id,))
    c.commit()
    c.close()


def get_tenants() -> List[Dict[str, Any]]:
    c = _conn()
    rows = c.execute("SELECT * FROM tenants ORDER BY id ASC").fetchall()
    c.close()
    return [dict(r) for r in rows]


def create_tenant(name: str, slug: str):
    c = _conn()
    c.execute("INSERT INTO tenants(name, slug) VALUES (?,?)", (name, slug))
    c.commit()
    c.close()


def create_user(tenant_id: int, username: str, password: str, role: str):
    c = _conn()
    salt = secrets.token_hex(8)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    c.execute("INSERT INTO users(tenant_id, username, pass_hash, salt, role) VALUES (?,?,?,?,?)",
              (tenant_id, username, h, salt, role))
    c.commit()
    c.close()
