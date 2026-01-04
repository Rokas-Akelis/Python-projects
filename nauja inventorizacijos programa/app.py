# app.py
import streamlit as st
import pandas as pd
import os

from models import get_session, Product, Movement, WcProductRaw
from movement_utils import record_movement
from sync_to_wc import sync_prices_and_stock_to_wc, pull_products_from_wc, DEMO_MODE  # naudosim jau tureta funkcija.
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


def load_wc_raw_df(session, limit: int = 500):
    rows = session.query(WcProductRaw).limit(limit).all()
    if not rows:
        return pd.DataFrame()
    data = []
    for r in rows:
        payload = r.raw or {}
        payload = payload.copy()
        payload["wc_id"] = r.wc_id
        data.append(payload)
    return pd.json_normalize(data)


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
            st.success(f"Atsargine kopija sukurta: {backup_path.name}")
        except Exception as e:
            st.error(f"Nepavyko sukurti kopijos: {e}")

    st.subheader("Prekiu sarasas")

    st.markdown("### Prideti nauja produkta")
    with st.form("add_product_form"):
        col1, col2, col3 = st.columns(3)
        name = col1.text_input("Pavadinimas*", "")
        sku = col2.text_input("SKU", "")
        wc_id_raw = col3.text_input("WC ID (optional)", "")
        price = st.number_input("Kaina", min_value=0.0, step=0.01, value=0.0)
        cost = st.number_input("Savikaina", min_value=0.0, step=0.01, value=0.0)
        quantity_new = st.number_input("Kiekis", min_value=0, step=1, value=0)
        active_new = st.checkbox("Aktyvus", value=True)
        add_submit = st.form_submit_button("Prideti produkta")

        if add_submit:
            if not name.strip():
                st.error("Pavadinimas privalomas.")
            else:
                existing = session.query(Product).filter(Product.name == name.strip()).one_or_none()
                if existing:
                    st.error("Toks produktas jau yra.")
                else:
                    try:
                        wc_id_val = int(wc_id_raw) if wc_id_raw.strip() else None
                    except Exception:
                        wc_id_val = None

                    product = Product(
                        name=name.strip(),
                        sku=sku.strip() or None,
                        wc_id=wc_id_val,
                        cost=cost if cost else None,
                        price=price if price else None,
                        quantity=0,
                        active=active_new,
                    )
                    session.add(product)
                    session.flush()  # kad turetume product.id

                    if quantity_new:
                        record_movement(
                            session=session,
                            product=product,
                            change=int(quantity_new),
                            source="manual_ui_add",
                            note="Prideta nauja preke",
                        )
                    session.commit()
                    st.success("Produktas pridetas.")
                    st.rerun()

    df = load_products_df(session)

    if df.empty:
        st.info("DB nera produktu. Pirma paleisk bootstrap importa.")
        return

    edited_df = st.data_editor(
        df,
        column_config={
            "Pavadinimas": st.column_config.TextColumn("Pavadinimas", disabled=True),
            "Kaina": st.column_config.NumberColumn("Kaina", step=0.01),
            "Kiekis": st.column_config.NumberColumn("Kiekis", step=1),
            "SKU": st.column_config.TextColumn("SKU", disabled=True),
            "WC_ID": st.column_config.NumberColumn("WC_ID", disabled=True),
        },
        disabled=["id"],  # id nelieciam
        hide_index=True,
        width="stretch",
    )

    backup_on_save = st.checkbox("Pries issaugant sukurti DB kopija", value=True, key="backup_on_save")
    if st.button("Issaugoti pakeitimus DB"):
        if backup_on_save:
            try:
                create_backup(label="before_ui_save")
            except Exception as e:
                st.error(f"Nepavyko sukurti kopijos: {e}")
                st.stop()
        products_by_id = {
            p.id: p for p in session.query(Product).filter(Product.active == True).all()
        }

        for _, row in edited_df.iterrows():
            pid = int(row["id"])
            product = products_by_id.get(pid)
            if not product:
                continue

            old_price = product.price
            old_qty = product.quantity or 0

            new_price = row["Kaina"]
            new_qty = int(row["Kiekis"])

            if new_price != old_price:
                product.price = new_price

            if new_qty != old_qty:
                change = new_qty - old_qty
                record_movement(
                    session=session,
                    product=product,
                    change=change,
                    source="manual_ui",
                    note="Pakeista per UI",
                )

        session.commit()
        st.success("OK. Pakeitimai issaugoti DB")

    st.markdown("---")

    st.subheader("Sinchronizacija su WooCommerce")

    if DEMO_MODE:
        st.info("Demo rezimas: WooCommerce API kvietimai praleidziami; log'uose matysi tik 'would sync'.")

    st.write(
        "Sis mygtukas paima kainas ir kiekius is DB ir issiuncia i WooCommerce per API "
        "(tik toms prekems, kurios turi WC_ID)."
    )
    confirm_push = st.checkbox("Patvirtinu siuntima i WC", value=False, key="confirm_push_wc")
    if st.button("Sinchronizuoti su svetaine (WooCommerce)"):
        if DEMO_MODE:
            st.info("Demo rezimas: API nekviestas.")
        elif not confirm_push:
            st.warning("Patvirtink siuntima checkbox'u.")
        else:
            try:
                sync_prices_and_stock_to_wc()  # viduje pati susikurs WooClient ir sesija.
                st.success("OK. Sinchronizacija su WooCommerce baigta (ziurek log'us).")
            except Exception as e:
                st.error(f"Sinchronizacijos klaida: {e}")

    st.markdown("---")

    st.subheader("Importuoti is WooCommerce")
    st.write("Nuskaito produktus is WC API ir atnaujina DB (prideda naujus, atnaujina kainas/kiekius).")
    confirm_pull = st.checkbox("Patvirtinu importa is WC", value=False, key="confirm_pull_wc")
    if st.button("Importuoti is WC"):
        if DEMO_MODE:
            st.warning("Demo rezimas: WC importas isjungtas. Isjunk DEMO_MODE.")
        elif not confirm_pull:
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

    st.markdown("---")
    with st.expander("WC zali duomenys (pilni CSV stulpeliai, pirmi 500)"):
        raw_df = load_wc_raw_df(session, limit=500)
        if raw_df.empty:
            st.info("WC zali duomenys negauti. Paleisk bootstrap arba WC importa.")
        else:
            st.dataframe(raw_df, hide_index=True, width="stretch")


if __name__ == "__main__":
    main()
