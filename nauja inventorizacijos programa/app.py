# app.py
import streamlit as st
import pandas as pd
import os
import json
import sys
import importlib
import numpy as np
from datetime import date, datetime

from models import get_session, Product, Movement, WcProductRaw, WcProductEdit
from backup_utils import create_backup, get_db_path, get_backup_dir, list_backups, restore_backup
from wc_fields import WC_EDIT_FIELDS, get_raw_value


def _load_sync_module():
    try:
        return importlib.import_module("sync_to_wc")
    except KeyError:
        sys.modules.pop("sync_to_wc", None)
        return importlib.import_module("sync_to_wc")


_sync_to_wc = _load_sync_module()
sync_prices_and_stock_to_wc = _sync_to_wc.sync_prices_and_stock_to_wc
pull_products_from_wc = _sync_to_wc.pull_products_from_wc
_normalize_wc_sync_ids = _sync_to_wc._normalize_wc_sync_ids

WC_FIELD_TYPES = {spec["key"]: spec["type"] for spec in WC_EDIT_FIELDS}


def load_products_df(session):
    products = session.query(Product).filter(Product.active == True).all()
    data = []
    for p in products:
        data.append({
            "id": p.id,
            "WC_ID": p.wc_id,
            "Pavadinimas": p.name,
            "Kaina": p.price,
            "Kiekis": p.quantity,
        })
    df = pd.DataFrame(data)
    if not df.empty:
        df = df.set_index("id")
    return df


def load_movements_df(session, limit: int = 50):
    rows = (
        session.query(Movement, Product.name)
        .join(Product, Movement.product_id == Product.id)
        .order_by(Movement.id.desc())
        .limit(limit)
        .all()
    )
    data = []
    for movement, product_name in rows:
        data.append({
            "ID": movement.id,
            "Produktas": product_name,
            "Kiekio pokytis": movement.change,
            "Saltinis": movement.source,
            "Pastaba": movement.note,
        })
    return pd.DataFrame(data)


def load_wc_raw_df(session):
    rows = session.query(WcProductRaw).order_by(WcProductRaw.wc_id).all()
    if not rows:
        return pd.DataFrame()
    data = []
    for r in rows:
        payload = r.raw or {}
        payload = payload.copy()
        payload["wc_id"] = r.wc_id
        data.append(payload)
    df = pd.json_normalize(data)

    def is_scalar_safe(val):
        if isinstance(val, (str, int, float, bool)) or val is None:
            return True
        if isinstance(val, (list, tuple, dict)):
            return False
        if isinstance(val, np.ndarray):
            return False
        try:
            res = pd.isna(val)
            # pd.isna(array) grąžina masyvą; laikom tai ne-scalar
            if isinstance(res, (list, tuple, np.ndarray)):
                return False
            return bool(res)
        except Exception:
            return False

    for col in df.columns:
        if df[col].apply(lambda v: not is_scalar_safe(v)).any():
            df[col] = df[col].apply(
                lambda v: None
                if is_scalar_safe(v) and pd.isna(v)
                else json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v)
            )
    return df


def _is_empty(val) -> bool:
    if val is None:
        return True
    try:
        if pd.isna(val):
            return True
    except Exception:
        pass
    if isinstance(val, str) and not val.strip():
        return True
    return False


def _normalize_text(val):
    if _is_empty(val):
        return None
    return str(val).strip()


def _normalize_bool(val):
    if _is_empty(val):
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(int(val))
    if isinstance(val, str):
        raw = val.strip().lower()
        if raw in {"1", "true", "yes", "taip", "y"}:
            return True
        if raw in {"0", "false", "no", "ne", "n"}:
            return False
    return None


def _normalize_float(val):
    if _is_empty(val):
        return None
    try:
        if isinstance(val, str):
            raw = val.strip().replace(" ", "").replace("\u00a0", "")
            if "," in raw and "." in raw:
                if raw.rfind(",") > raw.rfind("."):
                    raw = raw.replace(".", "").replace(",", ".")
                else:
                    raw = raw.replace(",", "")
            elif "," in raw and "." not in raw:
                raw = raw.replace(",", ".")
            return float(raw)
        return float(val)
    except Exception:
        return None


def _normalize_int(val):
    if _is_empty(val):
        return None
    try:
        if isinstance(val, str):
            raw = val.strip().replace(" ", "").replace("\u00a0", "")
            if "," in raw and "." in raw:
                if raw.rfind(",") > raw.rfind("."):
                    raw = raw.replace(".", "").replace(",", ".")
                else:
                    raw = raw.replace(",", "")
            elif "," in raw and "." not in raw:
                raw = raw.replace(",", ".")
            return int(float(raw))
        return int(float(val))
    except Exception:
        return None


def _normalize_date(val):
    if _is_empty(val):
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(val, date):
        return f"{val.isoformat()}T00:00:00"
    raw = str(val).strip()
    if not raw:
        return None
    if "T" in raw:
        return raw
    try:
        date.fromisoformat(raw)
        return f"{raw}T00:00:00"
    except Exception:
        return raw


def _display_date(val):
    if _is_empty(val):
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    raw = str(val).strip()
    if not raw:
        return None
    if "T" in raw:
        raw = raw.split("T", 1)[0]
    try:
        return date.fromisoformat(raw)
    except Exception:
        return None


def _display_value(val, field_type: str):
    if field_type == "date":
        return _display_date(val)
    if field_type == "bool":
        return _normalize_bool(val)
    if field_type == "int":
        return _normalize_int(val)
    if field_type in {"float", "price"}:
        return _normalize_float(val)
    return _normalize_text(val)


def _normalize_value(val, field_type: str):
    if field_type == "date":
        return _normalize_date(val)
    if field_type == "bool":
        return _normalize_bool(val)
    if field_type == "int":
        return _normalize_int(val)
    if field_type in {"float", "price"}:
        return _normalize_float(val)
    return _normalize_text(val)


def load_wc_edit_df(session):
    raw_rows = session.query(WcProductRaw).order_by(WcProductRaw.wc_id).all()
    if not raw_rows:
        return pd.DataFrame()

    edits_by_wc = {
        e.wc_id: (e.edits or {})
        for e in session.query(WcProductEdit).all()
        if e.wc_id
    }

    data = []
    for r in raw_rows:
        raw = r.raw if isinstance(r.raw, dict) else {}
        row = {"wc_id": r.wc_id}

        for spec in WC_EDIT_FIELDS:
            key = spec["key"]
            field_type = spec["type"]
            base_val = get_raw_value(raw, key)
            row[key] = _display_value(base_val, field_type)

        price_val = get_raw_value(raw, "price")
        if price_val is not None:
            row["price"] = _display_value(price_val, "price")

        edits = edits_by_wc.get(r.wc_id) or {}
        if isinstance(edits, dict):
            for key, val in edits.items():
                field_type = WC_FIELD_TYPES.get(key)
                row[key] = _display_value(val, field_type) if field_type else val

        data.append(row)

    return pd.DataFrame(data)


def to_int(val, default=None):
    try:
        if pd.isna(val):
            return default
        return int(float(val))
    except Exception:
        return default


def to_float(val, default=None):
    try:
        if pd.isna(val):
            return default
        return float(val)
    except Exception:
        return default


def pick_first_column(df, candidates):
    for col in candidates:
        if col in df.columns:
            return col
    return None


def apply_theme():
    if not hasattr(st, "markdown"):
        return
    st.markdown(
        """
        <style>
        @import url("https://fonts.googleapis.com/css2?family=Fraunces:wght@500;600;700&family=Urbanist:wght@300;400;500;600;700&display=swap");

        :root {
          --bg: #f7f2ec;
          --surface: #fdfbf9;
          --surface-2: #f2ece4;
          --text: #1a1511;
          --muted: #6c6259;
          --accent: #1f1a15;
          --accent-2: #c89f6d;
          --accent-3: #8c6b45;
          --border: rgba(26, 21, 17, 0.12);
          --shadow: 0 24px 60px rgba(26, 21, 17, 0.12);
          --radius: 22px;
        }

        html, body, [class*="css"] {
          font-family: "Urbanist", "Segoe UI", "Calibri", sans-serif;
          color: var(--text);
        }

        .stApp, .stApp * {
          color: var(--text);
        }

        .stApp {
          background:
            radial-gradient(900px circle at 90% 10%, rgba(200, 159, 109, 0.14), transparent 60%),
            radial-gradient(700px circle at 6% 0%, rgba(26, 21, 17, 0.08), transparent 55%),
            linear-gradient(180deg, #fbf7f2 0%, var(--bg) 100%);
        }

        .block-container {
          padding-top: 2.2rem;
          max-width: 1320px;
        }

        h1, h2, h3, .lux-title {
          font-family: "Fraunces", "Times New Roman", serif;
          letter-spacing: 0.02em;
        }

        .lux-header {
          display: grid;
          grid-template-columns: 1fr auto;
          gap: 1.2rem;
          align-items: center;
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: 26px;
          padding: 1.8rem 2rem;
          box-shadow: var(--shadow);
          margin-bottom: 1.6rem;
        }

        .lux-title {
          font-size: 2.1rem;
          margin-bottom: 0.3rem;
        }

        .lux-subtitle {
          color: var(--muted);
          max-width: 640px;
        }

        .lux-metrics {
          display: flex;
          flex-wrap: wrap;
          gap: 0.6rem;
          justify-content: flex-end;
        }

        .metric {
          background: var(--surface-2);
          border: 1px solid rgba(26, 21, 17, 0.12);
          border-radius: 999px;
          padding: 0.4rem 0.9rem;
          display: inline-flex;
          gap: 0.4rem;
          align-items: center;
          font-size: 0.8rem;
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }

        .metric span {
          font-weight: 600;
        }

        .section-title {
          font-size: 0.72rem;
          text-transform: uppercase;
          letter-spacing: 0.22em;
          color: var(--muted);
          margin: 0.5rem 0 0.9rem;
        }

        .lux-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
          gap: 1.3rem;
        }

        .lux-card {
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: var(--radius);
          padding: 1.3rem 1.5rem;
          box-shadow: var(--shadow);
        }

        .lux-card h4 {
          margin: 0 0 0.4rem;
          font-size: 1.1rem;
        }

        .lux-card p {
          color: var(--muted);
          margin: 0 0 0.9rem;
        }

        section[data-testid="stSidebar"] {
          background: #f3ede6;
          border-right: 1px solid var(--border);
        }

        section[data-testid="stSidebar"] > div {
          padding: 1.2rem 1rem;
        }

        section[data-testid="stSidebar"] .lux-card {
          box-shadow: 0 14px 32px rgba(26, 21, 17, 0.14);
        }

        .stButton button {
          background: linear-gradient(135deg, var(--accent), var(--accent-3));
          color: #ffffff !important;
          border: none;
          padding: 0.7rem 1.35rem;
          border-radius: 999px;
          box-shadow: 0 12px 26px rgba(26, 21, 17, 0.26);
          transition: transform 140ms ease, box-shadow 140ms ease;
        }

        .stButton button * {
          color: #ffffff !important;
        }

        .stButton button:hover {
          transform: translateY(-1px);
          box-shadow: 0 18px 34px rgba(26, 21, 17, 0.3);
        }

        div[data-testid="stTextInput"] input,
        div[data-testid="stFileUploader"] input,
        div[data-testid="stTextArea"] textarea,
        div[data-testid="stSelectbox"] select {
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: 14px;
          padding: 0.6rem 0.8rem;
          color: var(--text);
        }

        /* Selectbox dropdown and options */
        section[data-testid="stSidebar"] div[data-baseweb="select"] > div {
          background: var(--surface) !important;
          color: var(--text) !important;
        }

        section[data-testid="stSidebar"] div[data-baseweb="select"] span {
          color: var(--text) !important;
        }

        div[role="listbox"] {
          background: var(--surface) !important;
          color: var(--text) !important;
          border: 1px solid var(--border) !important;
        }

        div[role="option"] {
          color: var(--text) !important;
        }

        div[role="option"][aria-selected="true"] {
          background: var(--surface-2) !important;
        }

        div[data-testid="stDataFrame"],
        div[data-testid="stDataEditor"] {
          border-radius: var(--radius);
          border: 1px solid var(--border);
          background: var(--surface);
          box-shadow: var(--shadow);
        }

        hr {
          border: none;
          height: 1px;
          background: linear-gradient(90deg, transparent, var(--border), transparent);
        }

        @media (max-width: 980px) {
          .lux-header {
            grid-template-columns: 1fr;
          }
          .lux-metrics {
            justify-content: flex-start;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main():
    st.set_page_config(page_title="Inventorizacijos sistema", layout="wide")
    apply_theme()

    # Paprasta slaptazodzio apsauga (env var ADMIN_PASSWORD)
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    if not admin_password:
        st.error("ADMIN_PASSWORD nenurodytas aplinkoje – apsauga isjungta. Nustatyk ir perkrauk.")
        st.stop()

    # jei pasikeicia slaptazodis, reikia naujai prisijungti
    if st.session_state.get("auth_pwd") != admin_password:
        st.session_state.authed = False
        st.session_state.auth_pwd = admin_password

    if not st.session_state.get("authed"):
        pwd = st.text_input("Slaptazodis", type="password")
        if st.button("Prisijungti"):
            if pwd == admin_password:
                st.session_state.authed = True
                st.session_state.auth_pwd = admin_password
                st.rerun()
            else:
                st.error("Neteisingas slaptazodis.")
        st.stop()
    else:
        pass

    if "wc_editor_version" not in st.session_state:
        st.session_state["wc_editor_version"] = 0

    db_path = get_db_path()
    session = get_session(db_path)
    backup_dir = get_backup_dir(db_path)
    backups = list_backups(db_path)
    pending_count = session.query(WcProductEdit).count()
    total_products = session.query(WcProductRaw).count()

    st.markdown(
        f"""
        <div class="lux-header">
          <div>
            <div class="lux-title">Premium Retail Inventory</div>
            <div class="lux-subtitle">
              Profesionali aplinka WooCommerce prekiu redagavimui. Sistema siuncia tik tavo patvirtintus pakeitimus.
            </div>
          </div>
          <div class="lux-metrics">
            <div class="metric">Produktai <span>{total_products}</span></div>
            <div class="metric">Pakeitimai <span>{pending_count}</span></div>
            <div class="metric">DB <span>{"YRA" if db_path.exists() else "NERA"}</span></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    flash_msg = st.session_state.pop("flash_msg", None)
    if flash_msg:
        st.success(flash_msg)

    with st.sidebar:
        st.markdown('<div class="section-title">Sesija</div>', unsafe_allow_html=True)
        st.caption(f"DB: {'yra' if db_path.exists() else 'nera'}")
        if st.button("Atsijungti", key="logout_btn"):
            st.session_state.authed = False
            st.rerun()

        st.markdown('<div class="section-title">Operacijos</div>', unsafe_allow_html=True)

        st.markdown('<h4>Importuoti is WC</h4>', unsafe_allow_html=True)
        st.markdown(
            '<p>Atsiuncia produktus is WooCommerce API ir paruosia redagavimui.</p>',
            unsafe_allow_html=True,
        )
        confirm_pull = st.checkbox("Patvirtinu importa", value=False, key="confirm_pull_wc_primary")
        if st.button("Importuoti is WC", key="btn_pull_wc"):
            if not confirm_pull:
                st.warning("Patvirtink importa checkbox'u.")
            else:
                try:
                    pull_products_from_wc()
                    st.session_state["wc_editor_version"] += 1
                    st.success("Importas is WC baigtas.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Importo klaida: {e}")

        st.markdown('<h4>Siusti pakeitimus</h4>', unsafe_allow_html=True)
        st.markdown(
            '<p>Siunciami tik tavo redaguoti laukai. Tuscios reiksmes nesiunciamos.</p>',
            unsafe_allow_html=True,
        )
        sync_ids_text = st.text_input(
            "WC ID filtras (pvz.: 4117,4140). Palik tuscia, jei nori siusti visus.",
            value=os.getenv("WC_SYNC_IDS", ""),
            key="sync_wc_ids",
        )
        confirm_push = st.checkbox("Patvirtinu siuntima", value=False, key="confirm_push_wc")
        if st.button("Sinchronizuoti su svetaine", key="btn_push_wc"):
            if not confirm_push:
                st.warning("Patvirtink siuntima checkbox'u.")
            else:
                try:
                    allowed_ids = _normalize_wc_sync_ids(sync_ids_text)
                    if allowed_ids:
                        pending_now = (
                            session.query(WcProductEdit)
                            .filter(WcProductEdit.wc_id.in_(allowed_ids))
                            .count()
                        )
                    else:
                        pending_now = session.query(WcProductEdit).count()
                    if pending_now == 0:
                        st.warning("Nera issaugotu pakeitimu siuntimui.")
                    else:
                        result = sync_prices_and_stock_to_wc(allowed_wc_ids=sync_ids_text)
                        errors = result.get("errors") if isinstance(result, dict) else None
                        updated = result.get("updated") if isinstance(result, dict) else None
                        if errors:
                            st.error("WC grazino klaidu. Ziurek detales zemiau.")
                            st.write(errors[:10])
                        elif updated == 0:
                            st.warning("WC nepatvirtino pakeitimu arba nebuvo ka siusti.")
                        else:
                            try:
                                pull_products_from_wc()
                                st.session_state["flash_msg"] = (
                                    "OK. Sinchronizacija baigta, duomenys atnaujinti is WC."
                                )
                            except Exception as e_pull:
                                st.session_state["flash_msg"] = (
                                    "OK. Sinchronizacija baigta, bet WC importas nepavyko: "
                                    f"{e_pull}"
                                )
                            st.session_state["wc_editor_version"] += 1
                            try:
                                session.close()
                            except Exception:
                                pass
                            st.rerun()
                except Exception as e:
                    st.error(f"Sinchronizacijos klaida: {e}")

        st.markdown('<h4>Atsargines kopijos</h4>', unsafe_allow_html=True)
        # DB kelias/backup info paslepta pagal UI pageidavima
        if st.button("Sukurti DB kopija", key="btn_backup_create"):
            try:
                backup_path = create_backup(label="manual")
                if backup_path is None:
                    st.warning("DB dar nesukurta - kopija nesukurta.")
                else:
                    st.success(f"Atsargine kopija sukurta: {backup_path.name}")
                    st.rerun()
            except Exception as e:
                st.error(f"Nepavyko sukurti kopijos: {e}")

        if not backups:
            st.caption("Backup failu dar nera.")
        else:
            backup_labels = [b.name for b in backups]
            selected_backup = st.selectbox("Pasirink backup", backup_labels, key="restore_backup_select")
            confirm_restore = st.checkbox("Patvirtinu atkurima", value=False, key="confirm_restore_db")
            if st.button("Atkurti is backup", key="btn_backup_restore"):
                if not confirm_restore:
                    st.warning("Patvirtink atkurima checkbox'u.")
                else:
                    try:
                        session.close()
                    except Exception:
                        pass
                    try:
                        restore_backup(backup_path=backup_dir / selected_backup, db_path=db_path)
                        st.success("DB atkurta. Programa perkraunama.")
                        st.session_state["wc_editor_version"] += 1
                        st.rerun()
                    except Exception as e:
                        st.error(f"Nepavyko atkurti backup: {e}")

    st.markdown('<div class="lux-card">', unsafe_allow_html=True)
    st.markdown('<h4>WC lauku redagavimas</h4>', unsafe_allow_html=True)
    st.markdown(
        '<p>Tuscios reiksmes = nekeisti. "price" yra tik perziurai.</p>',
        unsafe_allow_html=True,
    )
    edit_df = load_wc_edit_df(session)
    if edit_df.empty:
        st.info("WC duomenys negauti. Pirma importuok is WC API.")
    else:
        pending_count = session.query(WcProductEdit).count()
        st.caption(f"Laukiantys pakeitimai: {pending_count}")
        st.caption("Tuscios reiksmes laikomos kaip 'nekeisti' ir i WC nesiunciamos.")

        editable_keys = [spec["key"] for spec in WC_EDIT_FIELDS]
        ordered_cols = ["wc_id"] + editable_keys
        if "price" in edit_df.columns:
            ordered_cols.append("price")
        remaining_cols = [c for c in edit_df.columns if c not in ordered_cols]
        edit_df = edit_df.reindex(columns=[c for c in ordered_cols if c in edit_df.columns] + remaining_cols)

        column_config = {
            "wc_id": st.column_config.NumberColumn("WC ID"),
        }
        for spec in WC_EDIT_FIELDS:
            key = spec["key"]
            label = spec["label"]
            field_type = spec["type"]
            if field_type == "bool":
                column_config[key] = st.column_config.CheckboxColumn(label)
            elif field_type == "date":
                column_config[key] = st.column_config.DateColumn(label)
            elif field_type == "int":
                column_config[key] = st.column_config.NumberColumn(label, step=1)
            elif field_type in {"float", "price"}:
                column_config[key] = st.column_config.NumberColumn(label, format="%.2f")
            else:
                column_config[key] = st.column_config.TextColumn(label)

        if "price" in edit_df.columns:
            column_config["price"] = st.column_config.NumberColumn("Kaina (read-only)", format="%.2f")

        disabled_cols = [col for col in edit_df.columns if col not in editable_keys]

        edited_raw = st.data_editor(
            edit_df,
            num_rows="fixed",
            hide_index=True,
            disabled=disabled_cols,
            column_config=column_config,
            width="stretch",
            key=f"wc_editor_{st.session_state['wc_editor_version']}",
        )

        backup_on_save = st.checkbox("Pries issaugant sukurti DB kopija", value=True, key="backup_raw")
        if st.button("Issaugoti WC pakeitimus"):
            if backup_on_save:
                try:
                    create_backup(label="before_wc_edit_save")
                except Exception as e:
                    st.error(f"Nepavyko sukurti kopijos: {e}")
                    st.stop()

            invalid_price_rows = []
            stock_manage_rows = []

            raw_rows = session.query(WcProductRaw).all()
            raw_by_wc = {r.wc_id: r for r in raw_rows if r.wc_id}
            edit_rows = session.query(WcProductEdit).all()
            edit_by_wc = {e.wc_id: e for e in edit_rows if e.wc_id}

            for _, row in edited_raw.iterrows():
                wc_id = to_int(row.get("wc_id"))
                if not wc_id:
                    continue
                raw_obj = raw_by_wc.get(wc_id)
                if raw_obj is None:
                    continue

                raw = raw_obj.raw if isinstance(raw_obj.raw, dict) else {}
                edit_obj = edit_by_wc.get(wc_id)
                edits = edit_obj.edits if edit_obj and isinstance(edit_obj.edits, dict) else {}

                for spec in WC_EDIT_FIELDS:
                    key = spec["key"]
                    field_type = spec["type"]
                    new_val = _normalize_value(row.get(key), field_type)
                    base_val = _normalize_value(get_raw_value(raw, key), field_type)

                    if field_type == "bool" and base_val is None and new_val is False:
                        new_val = None

                    if new_val is None or new_val == base_val:
                        edits.pop(key, None)
                    else:
                        edits[key] = new_val

                # Validacija: sale_price negali buti didesne uz regular_price.
                if "regular_price" in edits or "sale_price" in edits:
                    reg_val = edits.get("regular_price")
                    if reg_val is None:
                        reg_val = _normalize_value(get_raw_value(raw, "regular_price"), "price")
                    sale_val = edits.get("sale_price")
                    if sale_val is None:
                        sale_val = _normalize_value(get_raw_value(raw, "sale_price"), "price")
                    if reg_val is not None and sale_val is not None and sale_val > reg_val:
                        for key in ("regular_price", "sale_price", "date_on_sale_from", "date_on_sale_to"):
                            edits.pop(key, None)
                        invalid_price_rows.append(wc_id)

                # Jei bandoma keisti kieki, bet WC manage_stock isjungta, neatnaujinam kiekio.
                if "stock_quantity" in edits and "manage_stock" not in edits:
                    base_manage = _normalize_value(get_raw_value(raw, "manage_stock"), "bool")
                    if base_manage is not True:
                        edits.pop("stock_quantity", None)
                        stock_manage_rows.append(wc_id)

                if edits:
                    if edit_obj is None:
                        edit_obj = WcProductEdit(wc_id=wc_id, edits=edits)
                        session.add(edit_obj)
                        edit_by_wc[wc_id] = edit_obj
                    else:
                        edit_obj.edits = edits
                else:
                    if edit_obj is not None:
                        session.delete(edit_obj)

            session.commit()
            pending_after = session.query(WcProductEdit).count()
            st.success(f"WC pakeitimai issaugoti. Laukiantys: {pending_after}")
            if invalid_price_rows:
                st.warning(
                    "Dalies prekiu kainu keitimas atmestas: sale_price > regular_price. "
                    f"WC_ID: {', '.join(str(i) for i in invalid_price_rows[:10])}"
                )
            if stock_manage_rows:
                st.warning(
                    "Dalies prekiu kiekis nepakeistas, nes manage_stock isjungta. "
                    f"WC_ID: {', '.join(str(i) for i in stock_manage_rows[:10])}"
                )
    st.markdown("</div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
