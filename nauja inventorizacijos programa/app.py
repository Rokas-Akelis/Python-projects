# app.py
import streamlit as st
import pandas as pd
import os
import json
import numpy as np

from models import get_session, Product, Movement, WcProductRaw
from movement_utils import record_movement
from sync_to_wc import sync_prices_and_stock_to_wc, pull_products_from_wc  # naudosim jau tureta funkcija.
from bootstrap import merge_wc_csv
from backup_utils import create_backup, get_db_path, get_backup_dir


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
        :root {
          --bg: #f2f5f9;
          --surface: #ffffff;
          --surface-2: #f8fafc;
          --text: #0f172a;
          --muted: #64748b;
          --accent: #1d4ed8;
          --accent-2: #0ea5e9;
          --border: rgba(15, 23, 42, 0.12);
          --shadow: 0 16px 40px rgba(15, 23, 42, 0.08);
          --radius: 16px;
        }

        html, body, [class*="css"] {
          font-family: "Candara", "Tahoma", sans-serif;
          color: #000000;
        }

        .stApp, .stApp * {
          color: #000000;
        }

        .stApp {
          background:
            repeating-linear-gradient(
              135deg,
              rgba(0, 0, 0, 0.08) 0px,
              rgba(0, 0, 0, 0.08) 2px,
              transparent 2px,
              transparent 10px
            ),
            radial-gradient(900px circle at 90% 5%, #e6f0ff 0%, transparent 55%),
            radial-gradient(900px circle at 10% 0%, #e9f7ff 0%, transparent 50%),
            linear-gradient(180deg, #f7f9fc 0%, var(--bg) 100%);
        }

        .block-container {
          padding-top: 2.2rem;
          max-width: 1200px;
        }

        h1, h2, h3 {
          font-family: "Palatino Linotype", "Book Antiqua", serif;
          letter-spacing: 0.02em;
          color: #000000;
        }

        .hero {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 1rem;
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: 20px;
          padding: 1.6rem 1.8rem;
          box-shadow: var(--shadow);
          margin-bottom: 1.2rem;
        }

        .hero-title {
          font-size: 2rem;
          font-family: "Palatino Linotype", "Book Antiqua", serif;
          margin-bottom: 0.2rem;
        }

        .hero-subtitle {
          color: #000000;
        }

        .hero-badges {
          display: flex;
          gap: 0.5rem;
          flex-wrap: wrap;
        }

        .badge {
          padding: 0.25rem 0.6rem;
          border-radius: 999px;
          border: 1px solid var(--border);
          background: var(--surface-2);
          color: #000000;
          font-size: 0.8rem;
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }

        .section-title {
          font-size: 0.8rem;
          text-transform: uppercase;
          letter-spacing: 0.14em;
          color: #000000;
          margin: 0.2rem 0 0.6rem;
        }

        .stButton button {
          background: linear-gradient(135deg, var(--accent), var(--accent-2));
          color: #fff;
          border: none;
          padding: 0.6rem 1.1rem;
          border-radius: 999px;
          box-shadow: 0 10px 20px rgba(29, 78, 216, 0.25);
          transition: transform 120ms ease, box-shadow 120ms ease;
        }

        .stButton button:hover {
          transform: translateY(-1px);
          box-shadow: 0 14px 24px rgba(29, 78, 216, 0.3);
        }

        .stButton button:active { transform: translateY(0); }

        div[data-testid="stTextInput"] input,
        div[data-testid="stFileUploader"] input,
        div[data-testid="stTextArea"] textarea,
        div[data-testid="stSelectbox"] select {
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: 12px;
          padding: 0.6rem 0.8rem;
          color: #000000;
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

        @media (max-width: 780px) {
          .block-container { padding-top: 1.2rem; }
          .hero { flex-direction: column; align-items: flex-start; }
          .hero-title { font-size: 1.6rem; }
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
        pwd = st.text_input("Slaptazodis", type="default")
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
    st.markdown("#### WC CSV pilna lentele")
    raw_df = load_wc_raw_df(session)
    if raw_df.empty:
        st.info("WC zali duomenys negauti. Importuok WC CSV arba WC API.")
    else:
        name_col = pick_first_column(raw_df, ["Pavadinimas", "name"])
        price_col = pick_first_column(raw_df, ["Reguliari kaina", "regular_price", "Kaina"])
        qty_col = pick_first_column(raw_df, ["Atsargos", "stock_quantity"])
        comment_col = pick_first_column(raw_df, ["Komentaras", "Komentarai", "Pastaba", "Pastabos", "comment", "notes"])
        if comment_col is None:
            comment_col = "Komentaras"
            raw_df[comment_col] = None

        editable_cols = [col for col in [name_col, price_col, qty_col, comment_col] if col]
        disabled_cols = [col for col in raw_df.columns if col not in editable_cols]

        edited_raw = st.data_editor(
            raw_df,
            num_rows="fixed",
            hide_index=True,
            disabled=disabled_cols,
            width="stretch",
        )

        backup_on_save = st.checkbox("Pries issaugant sukurti DB kopija", value=True, key="backup_raw")
        if st.button("Issaugoti WC CSV pakeitimus"):
            if backup_on_save:
                try:
                    create_backup(label="before_raw_save")
                except Exception as e:
                    st.error(f"Nepavyko sukurti kopijos: {e}")
                    st.stop()

            raw_rows = session.query(WcProductRaw).all()
            raw_by_wc = {r.wc_id: r for r in raw_rows if r.wc_id}
            products = session.query(Product).all()
            products_by_wc = {p.wc_id: p for p in products if p.wc_id}

            for _, row in edited_raw.iterrows():
                wc_id = to_int(row.get("wc_id"))
                if not wc_id:
                    continue
                raw_obj = raw_by_wc.get(wc_id)
                if raw_obj is None:
                    raw_obj = WcProductRaw(wc_id=wc_id, raw={})
                    session.add(raw_obj)
                    raw_by_wc[wc_id] = raw_obj
                raw = raw_obj.raw if isinstance(raw_obj.raw, dict) else {}

                if name_col and name_col in row:
                    name_val = row.get(name_col)
                    if pd.isna(name_val):
                        name_val = None
                    if isinstance(name_val, str):
                        name_val = name_val.strip() or None
                    raw[name_col] = name_val
                    product = products_by_wc.get(wc_id)
                    if product and name_val:
                        product.name = str(name_val)

                if price_col and price_col in row:
                    price_val = to_float(row.get(price_col))
                    if price_val is not None:
                        raw[price_col] = str(price_val) if price_col == "regular_price" else price_val
                        product = products_by_wc.get(wc_id)
                        if product:
                            product.price = price_val
                    else:
                        raw[price_col] = None

                if qty_col and qty_col in row:
                    qty_val = to_int(row.get(qty_col))
                    raw[qty_col] = qty_val
                    product = products_by_wc.get(wc_id)
                    if product and qty_val is not None:
                        old_qty = product.quantity or 0
                        if qty_val != old_qty:
                            session.add(Movement(
                                product_id=product.id,
                                change=qty_val - old_qty,
                                source="raw_csv_ui",
                                note="Pakeista per raw CSV lentele",
                            ))
                        product.quantity = qty_val

                if comment_col and comment_col in row:
                    comment_val = row.get(comment_col)
                    if pd.isna(comment_val):
                        comment_val = None
                    if isinstance(comment_val, str):
                        comment_val = comment_val.strip() or None
                    raw[comment_col] = comment_val

                raw_obj.raw = raw

            session.commit()
            st.success("WC CSV pakeitimai issaugoti.")

    st.markdown("---")

    st.markdown("---")
    st.markdown('<div class="section-title">WC integracija</div>', unsafe_allow_html=True)
    col_sync, col_pull = st.columns(2, gap="large")
    with col_sync:
        st.markdown("#### Sinchronizacija i WC")
        st.write(
            "Sis mygtukas paima kainas ir kiekius is DB ir issiuncia i WooCommerce per API "
            "(tik toms prekems, kurios turi WC_ID)."
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
