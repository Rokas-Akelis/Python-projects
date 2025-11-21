#!/usr/bin/env python3
"""
Moderni inventorizacijos programa su SQLAlchemy ir tkinter.
Savybės:
- Įvedimas, redagavimas ir trynimas viename lange.
- Paieška ir išmanesni rodiniai per Treeview.
- Greitas kiekio koregavimas bei barkodo veiksmų palaikymas (+/-).
- Statistikos kortelės su bendra verte ir kiekiu.
- Importas / eksportas į Excel (automatinis stulpelių atpažinimas).
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from sqlalchemy import Column, Date, Float, Integer, String, create_engine, func, text
from sqlalchemy.orm import declarative_base, sessionmaker

try:
    import pandas as pd  # type: ignore
    HAS_PANDAS = True
except Exception:  # pragma: no cover
    HAS_PANDAS = False
    pd = None  # type: ignore

# ------------------ DB ------------------
DB_PATH = "inventory.db"
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)
Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    external_id = Column(String, unique=True)
    name = Column(String, nullable=False)
    dimension = Column(String)
    comment = Column(String, default="")
    barcode = Column(String, unique=True)
    quantity = Column(Integer, default=0)
    price = Column(Float, default=0.0)
    added_at = Column(Date, default=date.today)
    published = Column(String, default="Ne")


Base.metadata.create_all(engine)


def ensure_comment_column() -> None:
    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(products)")}
        if "comment" not in columns:
            conn.exec_driver_sql("ALTER TABLE products ADD COLUMN comment TEXT")


ensure_comment_column()


def ensure_published_column() -> None:
    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(products)")}
        if "published" not in columns:
            conn.exec_driver_sql("ALTER TABLE products ADD COLUMN published TEXT DEFAULT 'Ne'")


ensure_published_column()


def ensure_external_id_column() -> None:
    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(products)")}
        if "external_id" not in columns:
            conn.exec_driver_sql("ALTER TABLE products ADD COLUMN external_id TEXT")


ensure_external_id_column()


# ------------------ Pagalbinės funkcijos ------------------
def parse_int_or_zero(value: str) -> int:
    try:
        return int(float(str(value).strip().replace(",", ".")))
    except Exception:
        return 0


def parse_price(value: str) -> float:
    try:
        value = str(value).strip().replace(",", ".")
        return round(float(value), 2)
    except Exception:
        return 0.0


def normalize_text(value: str) -> str:
    return (value or "").strip()


def normalize_barcode_value(value: str) -> str:
    text = normalize_text(value)
    if text in {"0", "00", "000"}:
        return ""
    return text


def normalize_published_value(value: str) -> str:
    normalized = normalize_text(value).lower()
    if normalized in {"1", "true", "taip", "yes", "y", "published", "aktyvus", "aktyvi", "aktyviu"}:
        return "Taip"
    if normalized in {"0", "false", "ne", "no", "n", "neaktyvus", "neaktyvi"}:
        return "Ne"
    return "Ne"


def parse_date_value(value: str) -> Optional[date]:
    text = normalize_text(value)
    if not text:
        return None
    patterns = ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y", "%Y.%m.%d", "%d-%m-%Y")
    for pattern in patterns:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def is_barcode_unique(session, barcode: str, exclude_id: Optional[int] = None) -> bool:
    if not barcode:
        return True
    query = session.query(Product).filter(Product.barcode == barcode)
    if exclude_id:
        query = query.filter(Product.id != exclude_id)
    return not query.count()


def is_external_id_unique(session, external_id: str, exclude_id: Optional[int] = None) -> bool:
    if not external_id:
        return True
    query = session.query(Product).filter(Product.external_id == external_id)
    if exclude_id:
        query = query.filter(Product.id != exclude_id)
    return not query.count()


# ------------------ GUI ------------------
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Inventoriaus studija")
        self.geometry("1200x760")
        self.minsize(1100, 680)
        self.configure(bg="#0f172a")

        self.session = Session()
        self.active_product_id: Optional[int] = None
        self.status_after: Optional[str] = None

        # spalvos ir stiliai
        self.colors = {
            "bg": "#0f172a",
            "card": "#1f2937",
            "accent": "#38bdf8",
            "muted": "#94a3b8",
            "success": "#22c55e",
            "danger": "#ef4444",
        }

        # StringVar
        self.name_var = tk.StringVar()
        self.external_id_var = tk.StringVar()
        self.dimension_var = tk.StringVar()
        self.published_var = tk.StringVar(value="Ne")
        self.barcode_var = tk.StringVar()
        self.qty_var = tk.StringVar(value="0")
        self.price_var = tk.StringVar(value="0.00")
        self.total_var = tk.StringVar(value="0.00")
        self.search_var = tk.StringVar()
        self.stats_qty_var = tk.StringVar(value="0 vnt.")
        self.stats_value_var = tk.StringVar(value="0.00 EUR")
        self.stats_sku_var = tk.StringVar(value="0 SKU")
        self.view_info_var = tk.StringVar(value="Rodoma: 0")
        self.status_var = tk.StringVar(value="Pasiruošę darbui.")

        self.setup_styles()
        self.build_scrollable_container()
        self.build_layout()
        self.load_products()

    # ---------- UI kūrimas ----------
    def setup_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("App.TFrame", background=self.colors["bg"])
        style.configure("Card.TFrame", background=self.colors["card"])
        style.configure("Hero.TLabel", background=self.colors["card"], foreground="white",
                        font=("Segoe UI", 26, "bold"))
        style.configure("HeroSub.TLabel", background=self.colors["card"], foreground=self.colors["muted"],
                        font=("Segoe UI", 11))
        style.configure("CardHeading.TLabel", background=self.colors["card"], foreground="white",
                        font=("Segoe UI Semibold", 12))
        style.configure("CardBody.TLabel", background=self.colors["card"], foreground=self.colors["muted"],
                        font=("Segoe UI", 10))
        style.configure("Primary.TButton", background=self.colors["accent"], foreground="#0f172a",
                        font=("Segoe UI Semibold", 10), padding=8)
        style.map("Primary.TButton",
                  background=[("active", "#22d3ee"), ("pressed", "#0ea5e9")],
                  foreground=[("pressed", "#0f172a")])
        style.configure("Danger.TButton", background=self.colors["danger"], foreground="white",
                        font=("Segoe UI Semibold", 10), padding=8)
        style.map("Danger.TButton",
                  background=[("active", "#dc2626"), ("pressed", "#b91c1c")])
        style.configure("Ghost.TButton", background=self.colors["card"], foreground=self.colors["muted"],
                        font=("Segoe UI", 9), padding=6)
        style.configure("Status.TLabel", background=self.colors["bg"], foreground=self.colors["muted"],
                        font=("Segoe UI", 10))

        style.configure("Treeview", background=self.colors["card"], foreground="white",
                        rowheight=32, fieldbackground=self.colors["card"], bordercolor=self.colors["bg"])
        style.configure("Treeview.Heading", background=self.colors["card"],
                        foreground=self.colors["muted"], font=("Segoe UI Semibold", 10))
        style.map("Treeview", background=[("selected", "#334155")], foreground=[("selected", "white")])

    def build_scrollable_container(self) -> None:
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=self.colors["bg"])
        self.canvas.pack(side="left", fill="both", expand=True)
        self.v_scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.v_scroll.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=self.v_scroll.set)

        self.container = ttk.Frame(self.canvas, style="App.TFrame")
        self.canvas_window = self.canvas.create_window((0, 0), window=self.container, anchor="nw")

        self.container.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self.canvas_window, width=e.width),
        )

        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", lambda _e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind_all("<Button-5>", lambda _e: self.canvas.yview_scroll(1, "units"))

    def build_layout(self) -> None:
        container = self.container

        # hero
        hero = ttk.Frame(container, style="Card.TFrame", padding=(28, 24))
        hero.pack(fill="x", padx=24, pady=(24, 12))
        hero.columnconfigure(0, weight=1)

        ttk.Label(hero, text="Inventoriaus studija", style="Hero.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(hero, text="Sekite prekes, koreguokite kiekius ir matykite bendrą vertę realiu laiku.",
                  style="HeroSub.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))

        search_box = ttk.Frame(hero, style="Card.TFrame")
        search_box.grid(row=0, column=1, rowspan=2, sticky="e", padx=(16, 0))
        ttk.Entry(search_box, textvariable=self.search_var, width=32, font=("Segoe UI", 11)).grid(
            row=0, column=0, padx=(0, 8))
        ttk.Button(search_box, text="Ieškoti", style="Primary.TButton",
                   command=self.search_products).grid(row=0, column=1)
        ttk.Button(search_box, text="Valyti", style="Ghost.TButton",
                   command=self.reset_search).grid(row=0, column=2, padx=(8, 0))

        # stats
        stats = ttk.Frame(container, style="App.TFrame")
        stats.pack(fill="x", padx=24, pady=(0, 12))
        stats.columnconfigure((0, 1, 2), weight=1, uniform="stat")
        self._create_stat_card(stats, 0, "Bendras kiekis", self.stats_qty_var)
        self._create_stat_card(stats, 1, "Prekių vertė", self.stats_value_var)
        self._create_stat_card(stats, 2, "SKU skaičius", self.stats_sku_var)

        # body
        body = ttk.Frame(container, style="App.TFrame")
        body.pack(fill="both", expand=True, padx=24, pady=(0, 8))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        self._build_form(body)
        self._build_table(body)

        # actions
        actions = ttk.Frame(container, style="App.TFrame")
        actions.pack(fill="x", padx=24, pady=(0, 8))
        ttk.Button(actions, text="Importuoti iš Excel/CSV", style="Primary.TButton",
                   command=self.import_excel).pack(side="left")
        ttk.Button(actions, text="Eksportuoti į Excel/CSV", style="Primary.TButton",
                   command=self.export_excel).pack(side="left", padx=8)
        ttk.Button(actions, text="Visas sąrašas", style="Ghost.TButton",
                   command=self.load_products).pack(side="left", padx=(6, 0))

        status_bar = ttk.Frame(container, style="App.TFrame")
        status_bar.pack(fill="x", padx=24, pady=(0, 24))
        self.status_label = ttk.Label(status_bar, textvariable=self.status_var, style="Status.TLabel")
        self.status_label.pack(anchor="w")

    def _create_stat_card(self, parent: ttk.Frame, column: int, title: str, var: tk.StringVar) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        card.grid(row=0, column=column, sticky="nsew", padx=4)
        ttk.Label(card, text=title, style="CardBody.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=var, font=("Segoe UI", 20, "bold"),
                  background=self.colors["card"], foreground="white").pack(anchor="w", pady=(6, 0))

    def _build_form(self, parent: ttk.Frame) -> None:
        form = ttk.Frame(parent, style="Card.TFrame", padding=20)
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        form.columnconfigure(0, weight=1)

        ttk.Label(form, text="Prekės duomenys", style="CardHeading.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(form, text="Įrašykite informaciją arba pakeiskite pasirinktą įrašą.",
                  style="CardBody.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 12))

        ttk.Label(form, text="Pavadinimas", style="CardBody.TLabel").grid(row=2, column=0, sticky="w")
        self.name_entry = ttk.Entry(form, textvariable=self.name_var, font=("Segoe UI", 11))
        self.name_entry.grid(row=3, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(form, text="Parduotuvės ID", style="CardBody.TLabel").grid(row=4, column=0, sticky="w")
        self.external_id_entry = ttk.Entry(form, textvariable=self.external_id_var, font=("Segoe UI", 11))
        self.external_id_entry.grid(row=5, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(form, text="Matmuo", style="CardBody.TLabel").grid(row=6, column=0, sticky="w")
        self.dimension_entry = ttk.Entry(form, textvariable=self.dimension_var, font=("Segoe UI", 11))
        self.dimension_entry.grid(row=7, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(form, text="Komentaras", style="CardBody.TLabel").grid(row=8, column=0, sticky="w")
        comment_frame = ttk.Frame(form, style="Card.TFrame")
        comment_frame.grid(row=9, column=0, sticky="ew", pady=(0, 8))
        self.comment_text = tk.Text(comment_frame, height=4, wrap="word", font=("Segoe UI", 11), relief="flat")
        self.comment_text.pack(side="left", fill="both", expand=True)
        comment_scroll = ttk.Scrollbar(comment_frame, orient="vertical", command=self.comment_text.yview)
        comment_scroll.pack(side="right", fill="y")
        self.comment_text.configure(yscrollcommand=comment_scroll.set)

        ttk.Label(form, text="Ar paskelbta", style="CardBody.TLabel").grid(row=10, column=0, sticky="w")
        self.published_combo = ttk.Combobox(
            form,
            textvariable=self.published_var,
            values=("Taip", "Ne"),
            state="readonly",
            font=("Segoe UI", 11),
        )
        self.published_combo.grid(row=11, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(form, text="Barkodas (+/- veiksmams)", style="CardBody.TLabel").grid(row=12, column=0, sticky="w")
        self.barcode_entry = ttk.Entry(form, textvariable=self.barcode_var, font=("Segoe UI", 11))
        self.barcode_entry.grid(row=13, column=0, sticky="ew", pady=(0, 8))
        self.barcode_entry.bind("<Return>", lambda _e: self.handle_barcode_input())

        grid = ttk.Frame(form, style="Card.TFrame")
        grid.grid(row=14, column=0, sticky="ew", pady=(10, 0))
        grid.columnconfigure((0, 1), weight=1)

        ttk.Label(grid, text="Kiekis", style="CardBody.TLabel").grid(row=0, column=0, sticky="w")
        self.qty_entry = ttk.Entry(grid, textvariable=self.qty_var, font=("Segoe UI", 11), width=12)
        self.qty_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))

        ttk.Label(grid, text="Kaina (EUR)", style="CardBody.TLabel").grid(row=0, column=1, sticky="w")
        self.price_entry = ttk.Entry(grid, textvariable=self.price_var, font=("Segoe UI", 11), width=12)
        self.price_entry.grid(row=1, column=1, sticky="ew")

        ttk.Label(form, text="Bendra kaina", style="CardBody.TLabel").grid(row=15, column=0, sticky="w", pady=(12, 0))
        ttk.Label(form, textvariable=self.total_var, font=("Segoe UI", 16, "bold"),
                  background=self.colors["card"], foreground=self.colors["accent"]).grid(
            row=16, column=0, sticky="w")

        self.qty_var.trace_add("write", lambda *_: self.update_total())
        self.price_var.trace_add("write", lambda *_: self.update_total())

        buttons = ttk.Frame(form, style="Card.TFrame")
        buttons.grid(row=17, column=0, sticky="ew", pady=(16, 0))
        ttk.Button(buttons, text="Išsaugoti / atnaujinti", style="Primary.TButton",
                   command=self.save_product).pack(side="left", expand=True, fill="x")
        ttk.Button(buttons, text="Šalinti", style="Danger.TButton",
                   command=self.delete_product).pack(side="left", expand=True, fill="x", padx=6)
        ttk.Button(buttons, text="Išvalyti formą", style="Ghost.TButton",
                   command=self.clear_form).pack(side="left", expand=True, fill="x")

        quick = ttk.Frame(form, style="Card.TFrame")
        quick.grid(row=18, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(quick, text="Greiti kiekio veiksmai", style="CardBody.TLabel").pack(anchor="w")
        btn_row = ttk.Frame(quick, style="Card.TFrame")
        btn_row.pack(anchor="w", pady=4)
        ttk.Button(btn_row, text="+1", style="Primary.TButton",
                   command=lambda: self.adjust_quantity(1)).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="+5", style="Primary.TButton",
                   command=lambda: self.adjust_quantity(5)).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="-1", style="Danger.TButton",
                   command=lambda: self.adjust_quantity(-1)).pack(side="left", padx=(0, 6))
        ttk.Label(quick, text="Formatas +2:123456789 padidina kiekį pagal barkodą.",
                  style="CardBody.TLabel").pack(anchor="w", pady=(6, 0))

    def _build_table(self, parent: ttk.Frame) -> None:
        table_card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        table_card.grid(row=0, column=1, sticky="nsew")
        table_card.rowconfigure(1, weight=1)
        table_card.columnconfigure(0, weight=1)

        ttk.Label(table_card, text="Inventoriaus sąrašas", style="CardHeading.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(table_card, textvariable=self.view_info_var, style="CardBody.TLabel").grid(
            row=0, column=0, sticky="e")

        columns = (
            "external_id",
            "name",
            "dimension",
            "comment",
            "published",
            "barcode",
            "qty",
            "price",
            "total",
            "added",
        )
        self.product_tree = ttk.Treeview(table_card, columns=columns, show="headings", selectmode="browse")
        headings = {
            "external_id": "Pard. ID",
            "name": "Pavadinimas",
            "dimension": "Matmuo",
            "comment": "Komentaras",
            "published": "Paskelbta",
            "barcode": "Barkodas",
            "qty": "Kiekis",
            "price": "Kaina",
            "total": "Bendra",
            "added": "Data",
        }
        for key, text in headings.items():
            self.product_tree.heading(key, text=text)
        self.product_tree.column("external_id", width=110, anchor="center")
        self.product_tree.column("name", width=200, anchor="w")
        self.product_tree.column("dimension", width=120, anchor="w")
        self.product_tree.column("comment", width=160, anchor="w")
        self.product_tree.column("published", width=110, anchor="center")
        self.product_tree.column("barcode", width=140, anchor="center")
        self.product_tree.column("qty", width=80, anchor="center")
        self.product_tree.column("price", width=100, anchor="center")
        self.product_tree.column("total", width=120, anchor="center")
        self.product_tree.column("added", width=110, anchor="center")

        scroll_y = ttk.Scrollbar(table_card, orient="vertical", command=self.product_tree.yview)
        self.product_tree.configure(yscrollcommand=scroll_y.set)
        self.product_tree.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        scroll_y.grid(row=1, column=1, sticky="ns", pady=(8, 0))

        self.product_tree.tag_configure("low", foreground=self.colors["danger"])
        self.product_tree.tag_configure("ok", foreground=self.colors["success"])
        self.product_tree.bind("<<TreeviewSelect>>", lambda _e: self.on_select())
        self.product_tree.bind("<Delete>", lambda _e: self.delete_product())

    # ---------- Veiksmai ----------
    def load_products(self, products: Optional[list[Product]] = None) -> None:
        if products is None:
            products = self.session.query(Product).order_by(func.lower(Product.name)).all()

        self.product_tree.delete(*self.product_tree.get_children())
        for product in products:
            qty = product.quantity or 0
            price = product.price or 0.0
            total = qty * price
            published_value = normalize_published_value(product.published or "")
            tags = ()
            if qty == 0:
                tags = ("low",)
            elif qty >= 5:
                tags = ("ok",)
            self.product_tree.insert(
                "",
                "end",
                iid=str(product.id),
                values=(
                    product.external_id or "-",
                    product.name,
                    product.dimension or "-",
                    product.comment or "-",
                    published_value,
                    product.barcode or "-",
                    qty,
                    f"{price:.2f}",
                    f"{total:.2f}",
                    product.added_at.strftime("%Y-%m-%d") if product.added_at else "",
                ),
                tags=tags,
            )

        self.view_info_var.set(f"Rodoma: {len(products)}")
        self.update_stats()

    def get_comment_text(self) -> str:
        if not hasattr(self, "comment_text"):
            return ""
        return normalize_text(self.comment_text.get("1.0", "end").strip())

    def set_comment_text(self, value: str) -> None:
        if not hasattr(self, "comment_text"):
            return
        self.comment_text.delete("1.0", "end")
        if value:
            self.comment_text.insert("1.0", value)

    def get_selected_product(self) -> Optional[Product]:
        selection = self.product_tree.selection()
        if not selection:
            return None
        product_id = int(selection[0])
        self.active_product_id = product_id
        return self.session.get(Product, product_id)

    def save_product(self) -> None:
        name = normalize_text(self.name_var.get())
        external_id = normalize_text(self.external_id_var.get())
        dimension = normalize_text(self.dimension_var.get())
        comment = self.get_comment_text()
        published = normalize_published_value(self.published_var.get())
        barcode = normalize_barcode_value(self.barcode_var.get())
        qty = parse_int_or_zero(self.qty_var.get())
        price = parse_price(self.price_var.get())

        if not name:
            messagebox.showerror("Klaida", "Įveskite prekės pavadinimą.")
            return

        product = None
        if barcode:
            product = self.session.query(Product).filter(Product.barcode == barcode).first()
        if not product and external_id:
            product = self.session.query(Product).filter(Product.external_id == external_id).first()
        if not product and self.active_product_id:
            product = self.session.get(Product, self.active_product_id)
        if not product:
            product = self.session.query(Product).filter(func.lower(Product.name) == name.lower()).first()

        if barcode and not is_barcode_unique(self.session, barcode,
                                             exclude_id=product.id if product else None):
            messagebox.showerror("Klaida", f"Barkodas {barcode} jau naudojamas kitai prekei.")
            return
        if external_id and not is_external_id_unique(self.session, external_id,
                                                     exclude_id=product.id if product else None):
            messagebox.showerror("Klaida", f"Parduotuvės ID {external_id} jau priskirtas kitai prekei.")
            return

        if product:
            product.external_id = external_id or None
            product.name = name
            product.dimension = dimension or None
            product.comment = comment or None
            product.published = published
            product.barcode = barcode or None
            product.quantity = qty
            product.price = price
        else:
            product = Product(
                external_id=external_id or None,
                name=name,
                dimension=dimension or None,
                comment=comment or None,
                published=published,
                barcode=barcode or None,
                quantity=qty,
                price=price,
            )
            self.session.add(product)

        try:
            self.session.commit()
            self.active_product_id = product.id
            self.load_products()
            self.select_tree_row(product.id)
            self.show_status("Prekė išsaugota.", "success")
        except Exception as exc:  # pragma: no cover
            self.session.rollback()
            messagebox.showerror("DB klaida", f"Nepavyko išsaugoti: {exc}")

    def delete_product(self) -> None:
        product = self.get_selected_product()
        if not product:
            messagebox.showinfo("Info", "Pasirinkite įrašą sąraše.")
            return
        if not messagebox.askyesno("Patvirtinimas", f"Ištrinti „{product.name}“?"):
            return
        try:
            self.session.delete(product)
            self.session.commit()
            self.active_product_id = None
            self.load_products()
            self.clear_form()
            self.show_status("Prekė pašalinta.", "danger")
        except Exception as exc:  # pragma: no cover
            self.session.rollback()
            messagebox.showerror("DB klaida", f"Nepavyko ištrinti: {exc}")

    def on_select(self) -> None:
        product = self.get_selected_product()
        if not product:
            return
        self.name_var.set(product.name)
        self.external_id_var.set(product.external_id or "")
        self.dimension_var.set(product.dimension or "")
        self.set_comment_text(product.comment or "")
        self.published_var.set(normalize_published_value(product.published or ""))
        self.barcode_var.set(product.barcode or "")
        self.qty_var.set(str(product.quantity or 0))
        self.price_var.set(f"{(product.price or 0.0):.2f}")
        self.update_total()

    def clear_form(self) -> None:
        self.active_product_id = None
        self.name_var.set("")
        self.external_id_var.set("")
        self.dimension_var.set("")
        self.set_comment_text("")
        self.published_var.set("Ne")
        self.barcode_var.set("")
        self.qty_var.set("0")
        self.price_var.set("0.00")
        self.total_var.set("0.00")
        self.product_tree.selection_remove(self.product_tree.selection())

    def adjust_quantity(self, delta: int) -> None:
        current = parse_int_or_zero(self.qty_var.get())
        new_value = max(0, current + delta)
        self.qty_var.set(str(new_value))
        self.update_total()

    def update_total(self) -> None:
        qty = parse_int_or_zero(self.qty_var.get())
        price = parse_price(self.price_var.get())
        self.total_var.set(f"{qty * price:.2f}")

    def search_products(self) -> None:
        term = normalize_text(self.search_var.get())
        if not term:
            self.load_products()
            self.show_status("Rodomos visos prekės.")
            return
        lowered_term = f"%{term.lower()}%"
        query = self.session.query(Product).filter(
            func.lower(Product.name).like(lowered_term)
            | Product.barcode.like(f"%{term}%")
            | func.lower(func.coalesce(Product.external_id, "")).like(lowered_term)
            | func.lower(func.coalesce(Product.comment, "")).like(lowered_term)
            | func.lower(func.coalesce(Product.dimension, "")).like(lowered_term)
        )
        results = query.order_by(func.lower(Product.name)).all()
        self.load_products(results)
        self.show_status(f'Rasta {len(results)} pagal "{term}".')

    def reset_search(self) -> None:
        self.search_var.set("")
        self.load_products()
        self.show_status("Filtras išvalytas.")

    def select_tree_row(self, product_id: Optional[int]) -> None:
        if not product_id:
            return
        iid = str(product_id)
        if iid in self.product_tree.get_children(""):
            self.product_tree.selection_set(iid)
            self.product_tree.see(iid)

    def _on_mousewheel(self, event) -> None:
        if hasattr(event, "delta") and event.delta:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")

    # ---------- Barcode ----------
    def handle_barcode_input(self) -> None:
        value = self.barcode_var.get().strip()
        if re.match(r"^[+-]\d+:\S+$", value):
            self.process_barcode_action(value)
            self.barcode_var.set("")
        else:
            self.save_product()

    def process_barcode_action(self, barcode_action: str) -> None:
        match = re.match(r"^([+-])(\d+):(\S+)$", barcode_action.strip())
        if not match:
            messagebox.showerror("Klaida", "Netinkamas barkodo formatas (+2:123...).")
            return

        sign, qty_str, barcode = match.groups()
        qty_delta = int(qty_str)
        product = self.session.query(Product).filter(Product.barcode == barcode).first()
        if not product:
            messagebox.showerror("Klaida", f"Nerasta prekė su barkodu {barcode}.")
            return

        if sign == "+":
            product.quantity = (product.quantity or 0) + qty_delta
        else:
            product.quantity = max(0, (product.quantity or 0) - qty_delta)

        try:
            self.session.commit()
            self.load_products()
            self.show_status(f"Kiekis atnaujintas ({product.quantity} vnt.).", "success")
        except Exception as exc:  # pragma: no cover
            self.session.rollback()
            messagebox.showerror("DB klaida", f"Nepavyko atnaujinti kiekio: {exc}")

    # ---------- Importas / eksportas ----------
    def import_excel(self) -> None:
        if not HAS_PANDAS:
            messagebox.showerror("Priklausomybes", "Reikalingas pandas (pip install pandas).")
            return

        path = filedialog.askopenfilename(
            title="Pasirinkite CSV faila",
            filetypes=[("CSV files", "*.csv")],
        )
        if not path:
            return

        ext = os.path.splitext(path)[1].lower()
        if ext not in {".csv"}:
            messagebox.showerror("Formatas", "Palaikomi tik CSV failai.")
            return

        def load_dataframe(file_path: str) -> "pd.DataFrame":
            try:
                df_local = pd.read_csv(
                    file_path,
                    header=0,
                    keep_default_na=False,
                    dtype=str,
                    sep=None,
                    engine="python",
                )
            except Exception as exc:
                raise ValueError(f"Nepavyko perskaityti CSV failo: {exc}") from exc

            df_local = df_local.fillna("")
            df_local = df_local[~df_local.apply(lambda row: all(not normalize_text(str(v)) for v in row), axis=1)]
            if df_local.empty:
                raise ValueError("Faile nerasta duomenu.")
            df_local.reset_index(drop=True, inplace=True)
            return df_local

        try:
            df = load_dataframe(path)
        except ValueError as exc:
            messagebox.showerror("Klaida", str(exc))
            return

        field_definitions = [
            ("external_id", "ID", {"id", "prekės kodas", "prekes kodas", "sku"}, ""),
            ("name", "Pavadinimas", {"pavadinimas", "name", "title"}, ""),
            ("dimension", "Matmuo", {"matmuo", "matmenys", "dimensions", "size", "matmenys (cm)"}, ""),
            (
                "comment",
                "Komentaras",
                {"komentaras", "aprašymas", "aprasymas", "description", "trumpas apibūdinimas", "pirkimo pastaba"},
                "",
            ),
            ("published", "Paskelbtas", {"paskelbtas", "published"}, ""),
            ("barcode", "Barkodas", {"gtin, upc, ean, or isbn", "ean", "barkodas", "barcode"}, ""),
            ("quantity", "Kiekis", {"atsargos", "kiekis", "likutis", "stock", "qty"}, ""),
            ("price", "Kaina", {"kaina", "kaina (eur)", "price", "price eur"}, ""),
            ("total", "Bendra", {"bendra", "bendra (eur)", "total", "suma"}, ""),
            ("date", "Data", {"data", "date"}, ""),
        ]

        def normalize_header(value: str) -> str:
            return normalize_text(value).strip('"').lstrip("﻿").lower()

        header_lookup = {normalize_header(str(column)): str(column) for column in df.columns}
        resolved_columns: dict[str, str] = {}
        default_values = {key: default for key, _, _, default in field_definitions}

        for key, label, aliases, _ in field_definitions:
            normalized_label = normalize_header(label)
            candidates = set(aliases)
            candidates.add(normalized_label)
            for candidate in candidates:
                column = header_lookup.get(candidate)
                if column:
                    resolved_columns[key] = column
                    break

        if "name" not in resolved_columns and len(df.columns) > 0:
            resolved_columns["name"] = df.columns[0]

        missing_fields = [key for key, _, _, _ in field_definitions if key not in resolved_columns and key != "name"]
        if missing_fields:
            preview = ", ".join(label for key, label, _, _ in field_definitions if key in missing_fields[:4])
            suffix = "..." if len(missing_fields) > 4 else ""
            self.show_status(f"Trūksta stulpelių: {preview}{suffix}")

        def pick_field(row: "pd.Series", field: str) -> str:
            column = resolved_columns.get(field)
            if not column or column not in row.index:
                return default_values.get(field, "")
            value = row.get(column, "")
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return default_values.get(field, "")
            return str(value)
        def pick_field(row: "pd.Series", field: str) -> str:
            column = resolved_columns.get(field)
            if not column or column not in row.index:
                return ""
            value = row.get(column, "")
            return "" if value is None else str(value)

        imported, updated, duplicates = 0, 0, 0
        seen: set[tuple[str, str, str, str, str, int, float, str]] = set()
        total_rows = len(df)

        for _, row in df.iterrows():
            name = normalize_text(pick_field(row, "name"))
            if not name:
                continue

            external_id = normalize_text(pick_field(row, "external_id"))
            barcode = normalize_barcode_value(pick_field(row, "barcode"))
            if not barcode:
                barcode = normalize_barcode_value(external_id)

            dimension = normalize_text(pick_field(row, "dimension"))
            comment = normalize_text(pick_field(row, "comment"))

            qty = parse_int_or_zero(pick_field(row, "quantity"))
            price = parse_price(pick_field(row, "price"))
            total_value = parse_price(pick_field(row, "total"))
            if price == 0 and qty > 0 and total_value > 0:
                price = round(total_value / max(qty, 1), 2)

            published = normalize_published_value(pick_field(row, "published"))
            record_date = parse_date_value(pick_field(row, "date"))

            row_key = (
                external_id.lower(),
                barcode.lower(),
                name.lower(),
                dimension.lower(),
                comment.lower(),
                qty,
                price,
                published.lower(),
            )
            if row_key in seen:
                duplicates += 1
                continue
            seen.add(row_key)

            product = None
            if barcode:
                product = self.session.query(Product).filter(Product.barcode == barcode).first()
            if not product and external_id:
                product = self.session.query(Product).filter(Product.external_id == external_id).first()
            if not product:
                product = self.session.query(Product).filter(func.lower(Product.name) == name.lower()).first()

            if product:
                if external_id:
                    product.external_id = external_id
                product.name = name
                product.dimension = dimension or None
                product.comment = comment or None
                product.published = published
                if barcode:
                    product.barcode = barcode
                product.quantity = qty
                product.price = price
                if record_date:
                    product.added_at = record_date
                updated += 1
            else:
                new_product = Product(
                    external_id=external_id or None,
                    name=name,
                    dimension=dimension or None,
                    comment=comment or None,
                    barcode=barcode or None,
                    quantity=qty,
                    price=price,
                    published=published,
                    added_at=record_date or date.today(),
                )
                self.session.add(new_product)
                imported += 1

        try:
            self.session.commit()
        except Exception as exc:  # pragma: no cover
            self.session.rollback()
            messagebox.showerror("DB klaida", f"Nepavyko importuoti: {exc}")
            return

        self.load_products()
        messagebox.showinfo(
            "Importas",
            "Ikelta nauju: {0}\nAtnaujinta: {1}\nPraleista dublikatu: {2}\nApdorota eiluciu: {3}".format(
                imported, updated, duplicates, total_rows
            ),
        )

    def export_excel(self) -> None:
        if not HAS_PANDAS:
            messagebox.showerror("Priklausomybės", "Reikalingas pandas (pip install pandas).")
            return

        today = date.today().strftime("%Y-%m-%d")
        path = filedialog.asksaveasfilename(
            title="Išsaugoti CSV",
            defaultextension=".csv",
            initialfile=f"inventorius_{today}.csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not path:
            return

        if not path.lower().endswith(".csv"):
            path = f"{path}.csv"

        try:
            products = self.session.query(Product).order_by(func.lower(Product.name)).all()
            data = []
            for product in products:
                qty = product.quantity or 0
                price = product.price or 0.0
                data.append({
                    "Parduotuvės ID": product.external_id or "",
                    "Pavadinimas": product.name,
                    "Matmuo": product.dimension or "",
                    "Komentaras": product.comment or "",
                    "Paskelbta": normalize_published_value(product.published or ""),
                    "Barkodas": product.barcode or "",
                    "Kiekis": qty,
                    "Kaina (EUR)": f"{price:.2f}",
                    "Bendra (EUR)": f"{qty * price:.2f}",
                    "Data": product.added_at.strftime("%Y-%m-%d") if product.added_at else today,
                })

            df = pd.DataFrame(data)
            df.to_csv(path, index=False, encoding="utf-8-sig")
            messagebox.showinfo("Eksportas", f"CSV išsaugotas:\n{os.path.abspath(path)}")
        except Exception as exc:  # pragma: no cover
            messagebox.showerror("Klaida", f"Nepavyko eksportuoti: {exc}")

    # ---------- Statistika ir statusai ----------
    def update_stats(self) -> None:
        products = self.session.query(Product).all()
        total_qty = sum(product.quantity or 0 for product in products)
        total_value = sum((product.quantity or 0) * (product.price or 0.0) for product in products)
        self.stats_qty_var.set(f"{total_qty} vnt.")
        self.stats_value_var.set(f"{total_value:.2f} EUR")
        self.stats_sku_var.set(f"{len(products)} SKU")

    def show_status(self, message: str, level: str = "info") -> None:
        palette = {
            "info": self.colors["muted"],
            "success": self.colors["success"],
            "danger": self.colors["danger"],
        }
        color = palette.get(level, self.colors["muted"])
        self.status_var.set(message)
        self.status_label.configure(foreground=color)
        if self.status_after:
            self.after_cancel(self.status_after)

        def clear() -> None:
            self.status_var.set("")
            self.status_label.configure(foreground=self.colors["muted"])
            self.status_after = None

        self.status_after = self.after(4500, clear)


if __name__ == "__main__":
    app = App()
    app.mainloop()
