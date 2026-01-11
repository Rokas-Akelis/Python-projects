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
from backup_utils import create_backup, DB_PATH


def load_products_df(session):
    products = session.query(Product).filter(Product.active == True).all()
    data = []
    for p in products:
        data.append({
            "id": p.id,
            "Pavadinimas": p.name,
            "Kaina": p.price,
            "Kiekis": p.quantity,
            "SKU": p.sku,
            "WC_ID": p.wc_id,
        })
    return pd.DataFrame(data)


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


def main():
    st.set_page_config(page_title="Inventorizacijos sistema", layout="wide")

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

    st.title("Inventorizacijos valdymas")

    session = get_session()

    st.markdown("### Atsargines kopijos")
    if st.button("Sukurti DB atsargine kopija"):
        try:
            backup_path = create_backup(label="manual")
            if backup_path is None:
                st.warning("DB dar nesukurta - kopija nesukurta.")
            else:
                st.success(f"Atsargine kopija sukurta: {backup_path.name}")
        except Exception as e:
            st.error(f"Nepavyko sukurti kopijos: {e}")

    st.subheader("WC CSV importas")
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

    st.subheader("WC CSV pilna lentele")
    raw_df = load_wc_raw_df(session)
    if raw_df.empty:
        st.info("WC zali duomenys negauti. Importuok WC CSV arba WC API.")
        return

    edited_raw = st.data_editor(
        raw_df,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
    )

    backup_on_save = st.checkbox("Pries issaugant sukurti DB kopija", value=True, key="backup_raw")
    if st.button("Issaugoti pilnos lenteles pakeitimus"):
        if backup_on_save:
            try:
                create_backup(label="before_raw_save")
            except Exception as e:
                st.error(f"Nepavyko sukurti kopijos: {e}")
                st.stop()

        rows = edited_raw.to_dict(orient="records")
        # map wc_id -> row
        for row in rows:
            wc_id = row.get("wc_id")
            if wc_id in ("", None):
                continue
            try:
                wc_id = int(wc_id)
            except Exception:
                continue

            clean_raw = {}
            for k, v in row.items():
                if k == "wc_id":
                    continue
                if pd.isna(v):
                    clean_raw[k] = None
                else:
                    clean_raw[k] = v

            raw_obj = session.query(WcProductRaw).filter(WcProductRaw.wc_id == wc_id).one_or_none()
            if not raw_obj:
                raw_obj = WcProductRaw(wc_id=wc_id, raw=clean_raw)
                session.add(raw_obj)
            else:
                raw_obj.raw = clean_raw

            # atnaujinam Product
            name = row.get("Pavadinimas")
            price = to_float(row.get("Reguliari kaina"))
            qty = to_int(row.get("Atsargos"))
            sku = row.get("Prekes kodas") or row.get("Prekės kodas")

            product = session.query(Product).filter(Product.wc_id == wc_id).one_or_none()
            if not product:
                product = Product(
                    name=name.strip() if isinstance(name, str) else f"WC-{wc_id}",
                    wc_id=wc_id,
                    sku=sku if isinstance(sku, str) and sku.strip() else None,
                    price=price,
                    quantity=qty if qty is not None else 0,
                    active=True,
                )
                session.add(product)
            else:
                if isinstance(name, str) and name.strip():
                    product.name = name.strip()
                product.sku = sku if isinstance(sku, str) and sku.strip() else product.sku
                if price is not None:
                    product.price = price
                if qty is not None:
                    old_qty = product.quantity or 0
                    if qty != old_qty:
                        session.add(Movement(
                            product_id=product.id,
                            change=qty - old_qty,
                            source="raw_ui",
                            note="Pakeista per pilna WC lentele",
                        ))
                    product.quantity = qty

        session.commit()
        st.success("Pilnos lenteles pakeitimai issaugoti.")

    st.markdown("---")

    st.subheader("Sinchronizacija su WooCommerce")

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

    st.markdown("---")

    st.subheader("Importuoti is WooCommerce")
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

    st.subheader("Istrinti produktus")
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

    st.subheader("Judejimu zurnalas (paskutiniai 50)")
    moves_df = load_movements_df(session)
    if moves_df.empty:
        st.info("Judejimu dar nera.")
    else:
        st.dataframe(moves_df, hide_index=True, width="stretch")


if __name__ == "__main__":
    main()
