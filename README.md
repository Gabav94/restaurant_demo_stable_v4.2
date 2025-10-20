
# InnovaChat para Restaurantes — Demo estable (texto)

**Stack:** Python 3.12 · Streamlit · SQLite · LangChain(OpenAI) · Responsive  
**Páginas:** Client · Restaurant (login) · Admin (login)  
**Persistencia:** `app.db` en un directorio **escribible** (auto-detecta `/mount/src` en Cloud).

## Estructura
```txt
.
├─ streamlit_app.py
├─ pages/
│  ├─ 1_Client.py
│  ├─ 2_Restaurant.py
│  └─ 3_Admin.py
├─ backend/
│  ├─ config.py
│  ├─ db.py
│  ├─ faq.py
│  ├─ llm_chat.py
│  └─ utils.py
├─ assets/
├─ data/
├─ .streamlit/config.toml
├─ .env.example
└─ requirements.txt
```

## Variables y secretos
- Local: `.env` con `OPENAI_API_KEY`.
- Cloud: Secrets → `OPENAI_API_KEY`, y opcionalmente `LANGUAGE`, `MODEL`, `TEMPERATURE`, `ASSISTANT_NAME`, `TONE`, `CURRENCY`, `SLA_MINUTES`.

## Run local
```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
streamlit run streamlit_app.py
```

## Notas funcionales
- Cliente: **no pide nombre/teléfono/dirección/pago** hasta que haya **TOTAL** o cierre de pedido; luego uno a uno.
- Restaurante: CRUD menú, imágenes, órdenes (SLA/alertas), pendientes, CSV export. **Login** necesario.
- Admin: configuración general, **tenants/usuarios**, **FAQ (regex)** por tenant. **Login** necesario.
- Parseo de ítems: exacto + plurales + fuzzy `difflib` + cantidades (e.g., "2 hamburguesas").
- Bandera visual en Client cuando hay *pendings*.
- Botón **Nuevo chat** para reset de conversación.
