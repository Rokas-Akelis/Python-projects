import pandas as pd
import re
import argparse
from pathlib import Path


def extract_code(name: str) -> str | None:
    """
    Iš teksto bando ištraukti prekės kodą, pvz. Q545831, 470023, PJ35056 ir pan.
    Logika:
    - skiria pagal tarpus ir '/'
    - ima tokenus nuo galo
    - ieško tokių, kurie turi bent vieną skaičių ir yra 4+ simbolių
    """
    if not isinstance(name, str):
        return None

    tokens = name.replace("/", " ").split()
    for tok in reversed(tokens):
        tok_clean = tok.strip()
        # Bent vienas skaičius ir bent 4 simboliai, tik raidės / skaičiai / brūkšneliai
        if (
            len(tok_clean) >= 4
            and any(ch.isdigit() for ch in tok_clean)
            and re.fullmatch(r"[A-Z0-9\-]+", tok_clean, flags=re.IGNORECASE)
        ):
            return tok_clean
    return None


def load_wc_export(path: Path) -> pd.DataFrame:
    """Nuskaito wc-product-export CSV."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    return df


def load_stock_file(path: Path) -> pd.DataFrame:
    """
    Nuskaito 'Prekių likučiai...' CSV ir padaro minimalų tvarkymą:
    - numeta pirmas 3 eilutes (antraštės ir tuščia info)
    """
    df_raw = pd.read_csv(path, encoding="utf-8-sig")
    # Pagal tavo failą – realūs duomenys prasideda nuo 4 eilutės (indeksas 3)
    df = df_raw.iloc[3:].reset_index(drop=True)
    return df


def normalize_stock_to_wc_structure(stock_df: pd.DataFrame, wc_cols: list[str]) -> pd.DataFrame:
    """
    Sukuria DataFrame su tokia pačia struktūra kaip wc-product-export
    ir iš 'Prekių likučiai' duomenų užpildo kiek įmanoma daugiau laukų.

    Tikslas: gauti "wc-formato" eilutes likučių duomenims.
    """
    df = pd.DataFrame(columns=wc_cols)

    # Pavadinimas – pilnas tekstas iš 'Likučiai 2023.12.31'
    if "Likučiai 2023.12.31" not in stock_df.columns:
        raise ValueError("Laukų 'Likučiai 2023.12.31' nerasta likučių faile.")

    df["Pavadinimas"] = stock_df["Likučiai 2023.12.31"].astype(str)

    # Prekės kodas – ištraukiamas iš pavadinimo
    df["Prekės kodas"] = stock_df["Likučiai 2023.12.31"].apply(extract_code)

    # Atsargos (kiekis) – iš Unnamed: 2 (ten pas tave 'Kiekis')
    if "Unnamed: 2" in stock_df.columns:
        df["Atsargos"] = pd.to_numeric(stock_df["Unnamed: 2"], errors="coerce")
    else:
        df["Atsargos"] = pd.NA

    # Reguliari kaina – iš Unnamed: 1 (pirkimo kaina)
    if "Unnamed: 1" in stock_df.columns:
        # jei būtų kableliai kaip dešimtainiai – galima būtų daryti .str.replace(",", ".")
        df["Reguliari kaina"] = pd.to_numeric(stock_df["Unnamed: 1"], errors="coerce")
    else:
        df["Reguliari kaina"] = pd.NA

    # Pirkimo pastaba – kad neprarast info apie pirkimą ir sumą
    note_parts = []
    if "Unnamed: 1" in stock_df.columns:
        note_parts.append("Pirkimo kaina: " + stock_df["Unnamed: 1"].astype(str).fillna(""))
    if "Unnamed: 3" in stock_df.columns:
        note_parts.append("Suma: " + stock_df["Unnamed: 3"].astype(str).fillna(""))

    if note_parts:
        df["Pirkimo pastaba"] = ", ".join(note_parts)
    else:
        df["Pirkimo pastaba"] = ""

    # Tipas – pagal nutylėjimą 'simple'
    df["Tipas"] = "simple"

    # Turime? – jei atsargos > 0, tada '1'
    def flag_in_stock(x):
        try:
            return "1" if pd.notna(x) and float(x) > 0 else ""
        except Exception:
            return ""

    df["Turime?"] = df["Atsargos"].apply(flag_in_stock)

    # Paskelbtas – paliekam tuščią (galėsi nuspręsti, ar naujas prekes skelbti)
    if "Paskelbtas" in df.columns:
        df["Paskelbtas"] = df.get("Paskelbtas", "")

    # Užpildom visus kitus trūkstamus stulpelius tuščiomis reikšmėmis, kad struktūra sutaptų
    for col in wc_cols:
        if col not in df.columns:
            df[col] = ""

    # Sulygiuojam stulpelių tvarką su wc export
    df = df[wc_cols]

    return df


def merge_wc_and_stock(
    wc_df: pd.DataFrame, stock_wc_df: pd.DataFrame, prefer_stock_quantity: bool = True
) -> pd.DataFrame:
    """
    Sujungia wc-product-export ir likučius (jau perdirbtus į wc struktūrą).

    Logika:
    - jungiam pagal 'Prekės kodas' (jei yra)
    - jei prekė yra wc ir yra likučiuose:
        - atnaujinam Atsargos (ir prireikus Reguliari kaina, Pirkimo pastaba)
    - jei prekės nėra wc, bet yra likučiuose:
        - pridedam kaip naują eilutę
    """
    wc_df = wc_df.copy()
    stock_wc_df = stock_wc_df.copy()

    if "Prekės kodas" not in wc_df.columns:
        raise ValueError("wc-product-export faile nėra stulpelio 'Prekės kodas'.")

    # Kad būtų lengviau ieškoti pagal kodą, padarom indeksą wc faile pagal Prekės kodą (neprivaloma, bet patogu)
    # NE: indeksą daryt nenaudosim, nes kodai gali kartotis; geriau naudosim boolean mask
    wc_cols = list(wc_df.columns)

    # Suvedam visus kodus iš likučių
    for _, stock_row in stock_wc_df.iterrows():
        code = stock_row.get("Prekės kodas", None)
        if pd.isna(code) or code == "":
            # jei neturi kodo – kol kas praleidžiam arba ateityje galima daryti match per pavadinimą
            continue

        mask = wc_df["Prekės kodas"] == code

        if mask.any():
            # Prekė jau yra wc – atnaujinam
            idx = wc_df.index[mask][0]

            if prefer_stock_quantity:
                wc_df.at[idx, "Atsargos"] = stock_row.get("Atsargos", wc_df.at[idx, "Atsargos"])

            # Jei nori – galim atnaujinti ir Reguliari kaina (tik jei likučių faile ji egzistuoja)
            if not pd.isna(stock_row.get("Reguliari kaina", pd.NA)):
                wc_df.at[idx, "Reguliari kaina"] = stock_row["Reguliari kaina"]

            # Pirkimo pastaba – prirašom arba perrašom
            note = stock_row.get("Pirkimo pastaba", "")
            if isinstance(note, str) and note.strip():
                wc_df.at[idx, "Pirkimo pastaba"] = note

            # Turime? – pagal atsargas
            qty = stock_row.get("Atsargos", None)
            try:
                wc_df.at[idx, "Turime?"] = "1" if pd.notna(qty) and float(qty) > 0 else ""
            except Exception:
                pass

        else:
            # Prekės nėra wc – pridedam ją kaip naują
            new_row = {col: "" for col in wc_cols}
            for col in wc_cols:
                if col in stock_row.index:
                    new_row[col] = stock_row[col]
            wc_df = pd.concat([wc_df, pd.DataFrame([new_row])], ignore_index=True)

    return wc_df


def main():
    parser = argparse.ArgumentParser(
        description="Sujungia wc-product-export ir Prekių likučiai CSV į vieną bendrą wc struktūros failą."
    )
    parser.add_argument(
        "--wc",
        required=True,
        help="Kelias iki wc-product-export CSV (WooCommerce eksportas).",
    )
    parser.add_argument(
        "--stock",
        required=True,
        help="Kelias iki Prekių likučių CSV failo.",
    )
    parser.add_argument(
        "--out",
        default="combined_wc_products.csv",
        help="Išvedamo bendro CSV failo pavadinimas (numatytasis: combined_wc_products.csv).",
    )

    args = parser.parse_args()

    wc_path = Path(args.wc)
    stock_path = Path(args.stock)
    out_path = Path(args.out)

    print(f"👉 Nuskaitau wc-product-export: {wc_path}")
    wc_df = load_wc_export(wc_path)
    wc_cols = list(wc_df.columns)

    print(f"👉 Nuskaitau Prekių likučius: {stock_path}")
    stock_raw_df = load_stock_file(stock_path)

    print("👉 Konvertuoju likučius į wc struktūrą...")
    stock_wc_df = normalize_stock_to_wc_structure(stock_raw_df, wc_cols)

    print("👉 Sujungiu wc produktus su likučiais...")
    combined_df = merge_wc_and_stock(wc_df, stock_wc_df, prefer_stock_quantity=True)

    print(f"👉 Saugau į: {out_path}")
    combined_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print("✅ Baigta. Gali importuoti šį failą į WooCommerce arba toliau apdoroti.")


if __name__ == "__main__":
    main()
