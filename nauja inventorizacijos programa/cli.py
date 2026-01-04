import argparse
import sys

from backup_utils import create_backup
from bootstrap import sync_wc_csv_merge
from sync_to_wc import pull_products_from_wc, sync_prices_and_stock_to_wc


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Lokali inventorizacijos valdymo CLI (be Streamlit)."
    )
    parser.add_argument(
        "--merge-csv",
        action="store_true",
        help="Perskaityti WC CSV (data/...) ir nedestruktyviai sujungti su DB.",
    )
    parser.add_argument(
        "--pull-wc",
        action="store_true",
        help="Importuoti produktus is WooCommerce API i DB.",
    )
    parser.add_argument(
        "--push-wc",
        action="store_true",
        help="Is DB nusiusti kainas/kiekius i WooCommerce API.",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Pries veiksmus sukurti DB atsargine kopija.",
    )

    args = parser.parse_args(argv)

    if args.backup:
        path = create_backup(label="manual_cli")
        print(f"Atsargine kopija sukurta: {path}")

    if args.merge_csv:
        sync_wc_csv_merge()

    if args.pull_wc:
        pull_products_from_wc()

    if args.push_wc:
        sync_prices_and_stock_to_wc()

    if not any([args.merge_csv, args.pull_wc, args.push_wc]):
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
