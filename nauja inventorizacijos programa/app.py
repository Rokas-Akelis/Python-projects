# app.py
import streamlit as st
import pandas as pd
import os
import json
import numpy as np
from datetime import date, datetime

from models import get_session, Product, Movement, WcProductRaw, WcProductEdit
from sync_to_wc import sync_prices_and_stock_to_wc, pull_products_from_wc  # naudosim jau tureta funkcija.
from bootstrap import merge_wc_csv
from backup_utils import create_backup, get_db_path, get_backup_dir, list_backups, restore_backup
from wc_fields import WC_EDIT_FIELDS, get_raw_value

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
        return float(val)
    except Exception:
        return None


def _normalize_int(val):
    if _is_empty(val):
        return None
    try:
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
    st.markdown(
        """
        <style>
        @import url("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;600;700&family=Manrope:wght@300;400;500;600;700&display=swap");

        :root {
          --bg: #f5f6f8;
          --surface: rgba(255, 255, 255, 0.92);
          --surface-strong: #ffffff;
          --text: #0b1220;
          --muted: #5b6473;
          --accent: #0f172a;
          --accent-2: #2563eb;
          --border: rgba(15, 23, 42, 0.12);
          --shadow: 0 20px 50px rgba(15, 23, 42, 0.12);
          --radius: 18px;
        }

        html, body, [class*="css"] {
          font-family: "Manrope", "Segoe UI", "Calibri", sans-serif;
          color: var(--text);
        }

        .stApp, .stApp * {
          color: var(--text);
        }

        .stApp {
          background:
            radial-gradient(800px circle at 90% 10%, rgba(37, 99, 235, 0.12), transparent 60%),
            radial-gradient(700px circle at 5% 0%, rgba(15, 23, 42, 0.08), transparent 55%),
            linear-gradient(180deg, #f7f8fb 0%, var(--bg) 100%);
        }

        .block-container {
          padding-top: 2.2rem;
          max-width: 1280px;
        }

        h1, h2, h3, .hero-title {
          font-family: "Fraunces", "Times New Roman", serif;
          letter-spacing: 0.01em;
        }

        .hero {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1.2rem;
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: 24px;
          padding: 1.8rem 2rem;
          box-shadow: var(--shadow);
          backdrop-filter: blur(6px);
          margin-bottom: 1.4rem;
        }

        .hero-title {
          font-size: 2.1rem;
          margin-bottom: 0.3rem;
        }

        .hero-subtitle {
          color: var(--muted);
        }

        .hero-badges {
          display: flex;
          gap: 0.6rem;
          flex-wrap: wrap;
        }

        .badge {
          padding: 0.35rem 0.8rem;
          border-radius: 999px;
          border: 1px solid rgba(15, 23, 42, 0.14);
          background: rgba(255, 255, 255, 0.9);
          color: var(--accent);
          font-size: 0.72rem;
          text-transform: uppercase;
          letter-spacing: 0.14em;
        }

        .section-title {
          font-size: 0.75rem;
          text-transform: uppercase;
          letter-spacing: 0.18em;
          color: var(--muted);
          margin: 0.3rem 0 0.7rem;
        }

        .stButton button {
          background: linear-gradient(135deg, var(--accent), #1f2937);
          color: #fff;
          border: none;
          padding: 0.65rem 1.2rem;
          border-radius: 999px;
          box-shadow: 0 12px 28px rgba(15, 23, 42, 0.24);
          transition: transform 140ms ease, box-shadow 140ms ease;
        }

        .stButton button:hover {
          transform: translateY(-1px);
          box-shadow: 0 16px 34px rgba(15, 23, 42, 0.28);
        }

        .stButton button:active { transform: translateY(0); }

        div[data-testid="stTextInput"] input,
        div[data-testid="stFileUploader"] input,
        div[data-testid="stTextArea"] textarea,
        div[data-testid="stSelectbox"] select {
          background: var(--surface-strong);
          border: 1px solid var(--border);
          border-radius: 14px;
          padding: 0.6rem 0.8rem;
          color: var(--text);
          box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
        }

        div[data-testid="stDataFrame"],
        div[data-testid="stDataEditor"] {
          border-radius: var(--radius);
          border: 1px solid var(--border);
          background: var(--surface-strong);
          box-shadow: var(--shadow);
        }

        hr {
          border: none;
          height: 1px;
          background: linear-gradient(90deg, transparent, var(--border), transparent);
        }

        @media (max-width: 780px) {
          .block-container { padding-top: 1.2rem; }
          .hero { flex-direction: column; align-items: flex-start; }
          .hero-title { font-size: 1.7rem; }
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
        st.success("Prisijungta")
        if st.button("Atsijungti"):
            st.session_state.authed = False
            st.rerun()

    st.markdown(
        """
        <div class="hero">
          <div>
            <div class="hero-title">Inventorizacijos valdymas</div>
            <div class="hero-subtitle">Moderni ir paprasta sistema kasdieniams WC duomenu veiksmams.</div>
          </div>
          <div class="hero-badges">
            <span class="badge">CSV</span>
            <span class="badge">WC Sync</span>
            <span class="badge">Atsargos</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    session = get_session()

    st.markdown('<div class="section-title">Pagrindiniai veiksmai</div>', unsafe_allow_html=True)
    col_left, col_right = st.columns([1, 2], gap="large")
    with col_left:
        st.markdown("#### Atsargines kopijos")
        st.caption("Rekomenduojama pries importa ar didesnius pakeitimus.")
        db_path = get_db_path()
        backup_dir = get_backup_dir(db_path)
        st.caption(f"DB kelias: {db_path} ({'yra' if db_path.exists() else 'nera'})")
        st.caption(f"Backup aplankas: {backup_dir}")
        if st.button("Sukurti DB atsargine kopija"):
            try:
                backup_path = create_backup(label="manual")
                if backup_path is None:
                    st.warning("DB dar nesukurta - kopija nesukurta.")
                else:
                    st.success(f"Atsargine kopija sukurta: {backup_path.name}")
            except Exception as e:
                st.error(f"Nepavyko sukurti kopijos: {e}")

        st.markdown("##### Atkurti is backup")
        backups = list_backups(db_path)
        if not backups:
            st.caption("Backup failu dar nera.")
        else:
            backup_labels = [b.name for b in backups]
            selected_backup = st.selectbox("Pasirink backup", backup_labels, key="restore_backup_select")
            confirm_restore = st.checkbox("Patvirtinu atkurima", value=False, key="confirm_restore_db")
            if st.button("Atkurti is backup"):
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
                        st.rerun()
                    except Exception as e:
                        st.error(f"Nepavyko atkurti backup: {e}")

    with col_right:
        st.markdown("#### WC CSV importas")
        st.caption("Ikelk naujausi WC CSV ir atnaujink DB.")
        csv_upload = st.file_uploader("Pasirink WC CSV faila", type=["csv"])
        csv_path = st.text_input("Arba WC CSV kelias (lokaliai)", value="")
        if st.button("Importuoti WC CSV"):
            if csv_upload is None and not csv_path.strip():
                st.warning("Pasirink CSV faila arba nurodyk kelia.")
            else:
                try:
                    csv_bytes = csv_upload.getvalue() if csv_upload is not None else None
                    result = merge_wc_csv(csv_path=csv_path.strip() or None, csv_bytes=csv_bytes)
                    st.success(f"CSV importas baigtas. Nauju: {result['new']}, atnaujinta: {result['updated']}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"CSV importo klaida: {e}")

    st.markdown("---")
    st.markdown('<div class="section-title">Duomenu perziura</div>', unsafe_allow_html=True)
    st.markdown("#### WC lauku redagavimas")
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
        )

        backup_on_save = st.checkbox("Pries issaugant sukurti DB kopija", value=True, key="backup_raw")
        if st.button("Issaugoti WC pakeitimus"):
            if backup_on_save:
                try:
                    create_backup(label="before_wc_edit_save")
                except Exception as e:
                    st.error(f"Nepavyko sukurti kopijos: {e}")
                    st.stop()

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

    st.markdown("---")

    st.markdown("---")
    st.markdown('<div class="section-title">WC integracija</div>', unsafe_allow_html=True)
    col_sync, col_pull = st.columns(2, gap="large")
    with col_sync:
        st.markdown("#### Sinchronizacija i WC")
        st.write(
            "Sis mygtukas i WooCommerce issiuncia tik ranka pakeistus laukus is redagavimo lenteles "
            "(tik toms prekems, kurios buvo importuotos is WC)."
        )
        sync_ids_text = st.text_input(
            "WC ID filtras (pvz.: 4117,4140). Palik tuscia, jei nori siusti visus.",
            value=os.getenv("WC_SYNC_IDS", ""),
            key="sync_wc_ids",
        )
        confirm_push = st.checkbox("Patvirtinu siuntima i WC", value=False, key="confirm_push_wc")
        if st.button("Sinchronizuoti su svetaine (WooCommerce)"):
            if not confirm_push:
                st.warning("Patvirtink siuntima checkbox'u.")
            else:
                try:
                    sync_prices_and_stock_to_wc(allowed_wc_ids=sync_ids_text)  # viduje pati susikurs WooClient ir sesija.
                    st.success("OK. Sinchronizacija su WooCommerce baigta (ziurek log'us).")
                except Exception as e:
                    st.error(f"Sinchronizacijos klaida: {e}")

    with col_pull:
        st.markdown("#### Importuoti is WC")
        st.write("Nuskaito produktus is WC API ir atnaujina DB (prideda naujus, atnaujina kainas/kiekius).")
        confirm_pull = st.checkbox("Patvirtinu importa is WC", value=False, key="confirm_pull_wc")
        if st.button("Importuoti is WC"):
            if not confirm_pull:
                st.warning("Patvirtink importa checkbox'u.")
            else:
                try:
                    pull_products_from_wc()
                    st.success("Importas is WC baigtas.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Importo klaida: {e}")

    st.markdown("---")

    st.markdown("---")
    st.markdown('<div class="section-title">Valdymas</div>', unsafe_allow_html=True)
    st.markdown("#### Istrinti produktus")
    products_list = session.query(Product).all()
    options = {f"{p.name} (id={p.id})": p.id for p in products_list}
    selected_labels = st.multiselect("Pasirink produktus istrynimui", list(options.keys()))
    confirm_delete = st.checkbox("Patvirtinu trynima", value=False, key="confirm_delete")
    if st.button("Istrinti pazymetus"):
        selected_ids = [options[label] for label in selected_labels]
        if not selected_ids:
            st.info("Nepasirinktas nei vienas produktas.")
        elif not confirm_delete:
            st.warning("Patvirtink trynima checkbox'u.")
        else:
            try:
                create_backup(label="before_delete")
            except Exception as e:
                st.error(f"Nepavyko sukurti kopijos: {e}")
                st.stop()
            session.query(Movement).filter(Movement.product_id.in_(selected_ids)).delete(synchronize_session=False)
            session.query(Product).filter(Product.id.in_(selected_ids)).delete(synchronize_session=False)
            session.commit()
            st.success("Pasirinkti produktai istrinti.")
            st.rerun()

    st.markdown("#### Judejimu zurnalas (paskutiniai 50)")
    moves_df = load_movements_df(session)
    if moves_df.empty:
        st.info("Judejimu dar nera.")
    else:
        st.dataframe(moves_df, hide_index=True, width="stretch")


if __name__ == "__main__":
    main()
