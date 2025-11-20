from __future__ import annotations

import json
import csv
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import List
from uuid import uuid4
from calendar import monthrange

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    import openpyxl
except ImportError:  # pragma: no cover - optional priklausomybe
    openpyxl = None

DATA_FILE = Path(__file__).with_name("finance_data.json")

SPECIAL_BUDGET_COLUMNS = {
    "alga": {
        "aliases": {"alga"},
        "category": "Alga",
        "kind": "income",
        "description": "Alga (importuota)",
    },
    "nuoma": {
        "aliases": {"nuomamokesciai450nuoma", "nuomamokesciai", "nuoma"},
        "category": "Nuoma ir mokesciai",
        "kind": "expense",
        "description": "Nuoma ir mokesciai",
    },
    "komunaliniai": {
        "aliases": {"mokesciaikomunaliniai", "komunaliniai"},
        "category": "Komunaliniai mokesciai",
        "kind": "expense",
        "description": "Komunaliniai mokesciai",
    },
    "maistas": {
        "aliases": {"maistas"},
        "category": "Maistas",
        "kind": "expense",
        "description": "Maistas",
    },
    "papildomai": {
        "aliases": {"papildomaivisinekomunaliniumokesciai", "papildomai"},
        "category": "Papildomos islaidos",
        "kind": "expense",
        "description": "Papildomos islaidos",
    },
    "lieka": {
        "aliases": {"lieka"},
        "category": "Lieka",
        "kind": "income",
        "description": "Likutis po islaidu",
    },
}


@dataclass
class Transaction:
    uid: str
    date: str
    category: str
    description: str
    amount: float
    kind: str  # "income" arba "expense"

    @staticmethod
    def from_dict(data: dict) -> "Transaction":
        return Transaction(
            uid=data.get("uid") or uuid4().hex,
            date=data.get("date", datetime.now().strftime("%Y-%m-%d")),
            category=data.get("category", "Bendra"),
            description=data.get("description", ""),
            amount=float(data.get("amount", 0)),
            kind=data.get("kind", "expense"),
        )

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["amount"] = round(self.amount, 2)
        return payload

    @property
    def month_key(self) -> str:
        return datetime.fromisoformat(self.date).strftime("%Y-%m")


class FinanceTracker(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=20)
        self.master = master
        master.title("Finansu seklys")
        master.geometry("1160x720")
        master.minsize(980, 640)
        master.configure(bg="#0e1117")

        style = ttk.Style(master)
        style.theme_use("clam")
        style.configure("Dark.TFrame", background="#0e1117")
        style.configure("Card.TFrame", background="#151a28", borderwidth=0)
        style.configure("Accent.TButton", font=("Segoe UI Semibold", 10), padding=8)
        style.configure(
            "Treeview",
            background="#111624",
            fieldbackground="#111624",
            foreground="#f7f7fb",
            rowheight=28,
            borderwidth=0,
        )
        style.map("Treeview", background=[("selected", "#1f6feb")])
        style.configure(
            "Treeview.Heading",
            background="#1f2937",
            foreground="#f7f7fb",
            font=("Segoe UI Semibold", 10),
        )
        style.configure("Summary.TLabel", background="#151a28", foreground="#a5b4fc")
        style.configure(
            "SummaryValue.TLabel",
            background="#151a28",
            foreground="#f8fafc",
            font=("Segoe UI Semibold", 18),
        )
        style.configure("Form.TLabelframe", background="#151a28", foreground="#a5b4fc")
        style.configure("Form.TLabelframe.Label", background="#151a28", foreground="#a5b4fc")
        style.configure("TLabel", background="#0e1117", foreground="#f7f7fb", font=("Segoe UI", 11))

        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.grid(column=0, row=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self.amount_var = tk.StringVar()
        self.description_var = tk.StringVar()
        self.category_var = tk.StringVar()
        self.date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.kind_var = tk.StringVar(value="expense")
        self.month_income_var = tk.StringVar(value=self.format_currency(0))
        self.month_expense_var = tk.StringVar(value=self.format_currency(0))
        self.month_balance_var = tk.StringVar(value=self.format_currency(0))
        self.avg_income_var = tk.StringVar(value=self.format_currency(0))
        self.avg_expense_var = tk.StringVar(value=self.format_currency(0))

        self.transactions: List[Transaction] = []
        self.editing_uid: str | None = None

        self._build_layout()
        self.load_transactions()
        self.refresh_all()

    def _build_layout(self) -> None:
        summary_frame = ttk.Frame(self, style="Dark.TFrame")
        summary_frame.grid(column=0, row=0, sticky="ew", pady=(0, 20))
        summary_frame.columnconfigure((0, 1, 2, 3, 4), weight=1)

        summary_cards = [
            ("Menesio pajamos", self.month_income_var, "#22c55e"),
            ("Menesio islaidos", self.month_expense_var, "#ef4444"),
            ("Menesio balansas", self.month_balance_var, "#38bdf8"),
            ("Algos vidurkis", self.avg_income_var, "#86efac"),
            ("Islaidu vidurkis", self.avg_expense_var, "#fca5a5"),
        ]

        for idx, (title, variable, accent) in enumerate(summary_cards):
            card = ttk.Frame(summary_frame, style="Card.TFrame", padding=20)
            card.grid(column=idx, row=0, sticky="nsew", padx=10)
            ttk.Label(card, text=title, style="Summary.TLabel").pack(anchor="w")
            value_label = ttk.Label(card, textvariable=variable, style="SummaryValue.TLabel")
            value_label.pack(anchor="w", pady=(6, 0))
            value_label.configure(foreground=accent)

        content_split = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        content_split.grid(column=0, row=1, sticky="nsew", pady=(0, 10))
        self.rowconfigure(1, weight=1)

        main_area = ttk.Frame(self, style="Dark.TFrame")
        main_area.grid(column=0, row=1, sticky="nsew", pady=(0, 10))
        self.rowconfigure(1, weight=1)
        main_area.columnconfigure(0, weight=0)
        main_area.columnconfigure(1, weight=1)
        main_area.rowconfigure(0, weight=1)

        left_column = ttk.Frame(main_area, style="Dark.TFrame", width=340)
        left_column.grid(column=0, row=0, sticky="nsw", padx=(0, 12))
        left_column.columnconfigure(0, weight=1)
        left_column.rowconfigure(1, weight=1)

        form_frame = ttk.LabelFrame(
            left_column,
            text="Naujas / redaguojamas irasas",
            padding=12,
            style="Form.TLabelframe",
        )
        form_frame.columnconfigure((0, 1, 2, 3), weight=1)
        form_frame.grid(column=0, row=0, sticky="ew", pady=(0, 12))

        table_frame = ttk.LabelFrame(
            left_column,
            text="Visi irasai",
            padding=8,
            style="Form.TLabelframe",
        )
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        table_frame.grid(column=0, row=1, sticky="nsew")

        controls_wrapper = ttk.Frame(table_frame, style="Dark.TFrame", padding=(8, 4))
        controls_wrapper.grid(column=0, row=1, sticky="ew", pady=(10, 0))
        controls_wrapper.columnconfigure(0, weight=1)

        right_column = ttk.Frame(main_area, style="Dark.TFrame")
        right_column.grid(column=1, row=0, sticky="nsew")
        right_column.columnconfigure(0, weight=1)
        right_column.rowconfigure(0, weight=1)

        chart_frame = ttk.LabelFrame(
            right_column,
            text="Menesio dinamika",
            padding=10,
            style="Form.TLabelframe",
        )
        chart_frame.columnconfigure(0, weight=1)
        chart_frame.rowconfigure(0, weight=1)
        chart_frame.grid(column=0, row=0, sticky="nsew")

        ttk.Label(form_frame, text="Data (YYYY-MM-DD)").grid(column=0, row=0, sticky="w")
        ttk.Entry(form_frame, textvariable=self.date_var).grid(column=0, row=1, sticky="ew", padx=(0, 12))

        ttk.Label(form_frame, text="Suma").grid(column=1, row=0, sticky="w")
        ttk.Entry(form_frame, textvariable=self.amount_var).grid(column=1, row=1, sticky="ew", padx=(0, 12))

        ttk.Label(form_frame, text="Kategorija").grid(column=2, row=0, sticky="w")
        ttk.Entry(form_frame, textvariable=self.category_var).grid(column=2, row=1, sticky="ew", padx=(0, 12))

        ttk.Label(form_frame, text="Aprasymas").grid(column=3, row=0, sticky="w")
        ttk.Entry(form_frame, textvariable=self.description_var).grid(column=3, row=1, sticky="ew")

        type_frame = ttk.Frame(form_frame, style="Dark.TFrame")
        type_frame.grid(column=0, row=2, columnspan=4, pady=(16, 0), sticky="w")
        ttk.Radiobutton(
            type_frame,
            text="Islaida",
            value="expense",
            variable=self.kind_var,
        ).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(
            type_frame,
            text="Pajamos",
            value="income",
            variable=self.kind_var,
        ).pack(side="left")

        ttk.Button(
            form_frame,
            text="Importuoti is Excel",
            style="Accent.TButton",
            command=self.import_from_excel,
        ).grid(column=2, row=3, sticky="w", padx=(0, 12), pady=(12, 0))

        self.submit_button = ttk.Button(
            form_frame,
            text="Irasyti",
            style="Accent.TButton",
            command=self.add_transaction,
        )
        self.submit_button.grid(column=3, row=3, sticky="e", pady=(12, 0))

        columns = ("date", "kind", "category", "description", "amount")
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="extended",
            height=14,
        )
        headings = [
            ("date", "Data"),
            ("kind", "Tipas"),
            ("category", "Kategorija"),
            ("description", "Aprasymas"),
            ("amount", "Suma"),
        ]
        for col, text in headings:
            anchor = "center" if col in {"date", "kind", "amount"} else "w"
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, anchor=anchor, stretch=True, width=100)
        self.tree.column("description", width=220)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(column=0, row=0, sticky="nsew")
        vsb.grid(column=1, row=0, sticky="ns")
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Return>", self._on_tree_double_click)
        self.empty_table_label = ttk.Label(
            table_frame,
            text="Nera irasu.\nPridėkite nauja irasa arba importuokite Excel faila.",
            justify="center",
            foreground="#cbd5f5",
            background="#151a28",
        )
        self.empty_table_label.place(relx=0.5, rely=0.45, anchor="center")

        self.table_status_var = tk.StringVar(value="Rodoma 0 irasu")
        ttk.Label(controls_wrapper, textvariable=self.table_status_var).grid(column=0, row=0, sticky="w")
        button_bar = ttk.Frame(controls_wrapper, style="Dark.TFrame")
        button_bar.grid(column=1, row=0, sticky="e")
        ttk.Button(
            button_bar,
            text="Redaguoti pasirinkta",
            command=self.start_edit_selected,
        ).pack(side="left", padx=(0, 12))
        ttk.Button(
            button_bar,
            text="Pasalinti pasirinktus",
            command=self.delete_selected,
        ).pack(side="left")

        self.chart_canvas = tk.Canvas(
            chart_frame,
            background="#151a28",
            highlightthickness=0,
        )
        self.chart_canvas.grid(column=0, row=0, sticky="nsew")
        self.chart_canvas.bind("<Configure>", lambda event: self.update_chart())

    @staticmethod
    def format_currency(value: float) -> str:
        formatted = f"{value:,.2f}"
        integer, _, decimals = formatted.partition(".")
        integer = integer.replace(",", " ")
        return f"{integer},{decimals} EUR"

    def load_transactions(self) -> None:
        if not DATA_FILE.exists():
            self.transactions = []
            return
        try:
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            self.transactions = [Transaction.from_dict(item) for item in raw]
        except Exception as exc:  # pragma: no cover
            messagebox.showwarning(
                "Ispejimas",
                f"Nepavyko nuskaityti esamu duomenu. Pradedama nuo tuscio saraso.\n{exc}",
            )
            self.transactions = []

    def save_transactions(self) -> None:
        data = [txn.to_dict() for txn in self.transactions]
        DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_transaction(self) -> None:
        date_raw = self.date_var.get().strip()
        try:
            date_value = datetime.strptime(date_raw, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Netinkama data", "Data turi buti formatu YYYY-MM-DD.")
            return

        try:
            amount = float(self.amount_var.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Netinkama suma", "Iveskite skaiciu, pvz, 125.90")
            return

        if amount <= 0:
            messagebox.showerror("Netinkama suma", "Suma turi buti didesne nei 0.")
            return

        kind = self.kind_var.get()
        category = self.category_var.get().strip() or ("Pajamos" if kind == "income" else "Islaidos")
        description = self.description_var.get().strip() or (
            "Irasas be aprasymo" if kind == "expense" else "Pajamu irasas"
        )

        if self.editing_uid:
            target = next((item for item in self.transactions if item.uid == self.editing_uid), None)
            if not target:
                messagebox.showerror("Redagavimas", "Nepavyko atnaujinti pasirinkto iraso.")
            else:
                target.date = date_value.strftime("%Y-%m-%d")
                target.category = category
                target.description = description
                target.amount = round(amount, 2)
                target.kind = kind
        else:
            txn = Transaction(
                uid=uuid4().hex,
                date=date_value.strftime("%Y-%m-%d"),
                category=category,
                description=description,
                amount=round(amount, 2),
                kind=kind,
            )
            self.transactions.append(txn)
        self.save_transactions()
        self.clear_form()
        self.refresh_all()

    def clear_form(self) -> None:
        self.amount_var.set("")
        self.description_var.set("")
        self.category_var.set("")
        self.date_var.set(datetime.now().strftime("%Y-%m-%d"))
        self.kind_var.set("expense")
        self.editing_uid = None
        self.submit_button.config(text="Irasyti")

    def refresh_all(self) -> None:
        self.update_summary()
        self.refresh_table()
        self.update_chart()

    def refresh_table(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        sorted_txns = sorted(self.transactions, key=lambda tx: tx.date, reverse=True)
        for txn in sorted_txns:
            pretty_kind = "Pajamos" if txn.kind == "income" else "Islaidos"
            amount_text = ("+" if txn.kind == "income" else "-") + self.format_currency(txn.amount)
            self.tree.insert(
                "",
                "end",
                iid=txn.uid,
                values=(txn.date, pretty_kind, txn.category, txn.description, amount_text),
                tags=(txn.kind,),
            )
        self.tree.tag_configure("income", foreground="#4ade80")
        self.tree.tag_configure("expense", foreground="#fb7185")
        self.table_status_var.set(f"Rodoma {len(sorted_txns)} irasu")
        if sorted_txns:
            self.empty_table_label.place_forget()
        else:
            self.empty_table_label.place(relx=0.5, rely=0.45, anchor="center")

    def update_summary(self) -> None:
        current_month = datetime.now().strftime("%Y-%m")
        income = sum(
            txn.amount for txn in self.transactions if txn.kind == "income" and txn.month_key == current_month
        )
        expense = sum(
            txn.amount for txn in self.transactions if txn.kind == "expense" and txn.month_key == current_month
        )
        balance = income - expense
        self.month_income_var.set(self.format_currency(income))
        self.month_expense_var.set(self.format_currency(expense))
        self.month_balance_var.set(self.format_currency(balance))
        income_entries = [txn.amount for txn in self.transactions if txn.kind == "income"]
        expense_entries = [txn.amount for txn in self.transactions if txn.kind == "expense"]
        avg_income = sum(income_entries) / len(income_entries) if income_entries else 0
        avg_expense = sum(expense_entries) / len(expense_entries) if expense_entries else 0
        self.avg_income_var.set(self.format_currency(avg_income))
        self.avg_expense_var.set(self.format_currency(avg_expense))

    def update_chart(self) -> None:
        canvas = self.chart_canvas
        canvas.delete("all")

        monthly_income: defaultdict[str, float] = defaultdict(float)
        monthly_expense: defaultdict[str, float] = defaultdict(float)
        monthly_entries: defaultdict[str, dict[str, List[Transaction]]] = defaultdict(
            lambda: {"income": [], "expense": []}
        )
        for txn in sorted(self.transactions, key=lambda tx: tx.date):
            if txn.kind == "income":
                monthly_income[txn.month_key] += txn.amount
            else:
                monthly_expense[txn.month_key] += txn.amount
            monthly_entries[txn.month_key][txn.kind].append(txn)

        months = sorted(monthly_entries.keys())

        canvas.update_idletasks()
        width = max(int(canvas.winfo_width()), 200)
        height = max(int(canvas.winfo_height()), 150)

        padding_left = 70
        padding_right = 40
        padding_top = 40
        padding_bottom = 50

        canvas.configure(scrollregion=(0, 0, width, height))
        canvas.create_rectangle(0, 0, width, height, fill="#151a28", outline="")

        if not months:
            canvas.create_text(
                width / 2,
                height / 2,
                text="Pridekite pirma irasa",
                fill="#9ca3c9",
                font=("Segoe UI", 14, "bold"),
            )
            return

        labels = [datetime.strptime(month, "%Y-%m").strftime("%Y %b") for month in months]
        income_totals = [monthly_income.get(month, 0) for month in months]
        expense_totals = [monthly_expense.get(month, 0) for month in months]
        balance_values = [inc - exp for inc, exp in zip(income_totals, expense_totals)]

        usable_width = width - padding_left - padding_right
        usable_height = height - padding_top - padding_bottom
        slot_width = usable_width / max(len(months), 1)

        max_entry_amount = max((txn.amount for txn in self.transactions), default=0)
        max_positive = max(income_totals + [max(max(balance_values + [0]), max_entry_amount), 1])
        max_negative = max(expense_totals + [abs(min(balance_values + [0]))])
        total_range = max_positive + max_negative or 1
        scale = usable_height / total_range
        zero_y = padding_top + max_positive * scale

        canvas.create_line(
            padding_left,
            zero_y,
            width - padding_right,
            zero_y,
            fill="#1f2937",
            width=2,
        )

        for step in range(5):
            amount = max_positive * step / 4
            y = zero_y - amount * scale
            canvas.create_line(padding_left, y, width - padding_right, y, fill="#1f2937", dash=(2, 4))
            canvas.create_text(
                padding_left - 10,
                y,
                text=self.format_currency(amount),
                fill="#9ca3c9",
                anchor="e",
                font=("Segoe UI", 9),
            )

        if max_negative > 0:
            for step in range(1, 5):
                amount = max_negative * step / 4
                y = zero_y + amount * scale
                canvas.create_line(padding_left, y, width - padding_right, y, fill="#1f2937", dash=(2, 4))
                canvas.create_text(
                    padding_left - 10,
                    y,
                    text=f"-{self.format_currency(amount)}",
                    fill="#9ca3c9",
                    anchor="e",
                    font=("Segoe UI", 9),
                )

        group_width = slot_width * 0.8
        spacing_between = slot_width * 0.05
        legend_x = padding_left
        legend_y = padding_top - 20
        legend_items = [
            ("#22c55e", "Pajamos"),
            ("#ef4444", "Islaidos"),
            ("#38bdf8", "Balansas"),
        ]
        for color, label in legend_items:
            canvas.create_rectangle(legend_x, legend_y - 10, legend_x + 14, legend_y + 4, fill=color, outline="")
            canvas.create_text(legend_x + 20, legend_y - 3, text=label, fill="#f8fafc", anchor="w", font=("Segoe UI", 10))
            legend_x += 110

        line_points: List[float] = []
        for idx, month in enumerate(months):
            center_x = padding_left + slot_width * idx + slot_width / 2

            incomes = monthly_entries[month]["income"]
            expenses = monthly_entries[month]["expense"]

            half_group = group_width / 2
            income_start = center_x - half_group
            income_end = center_x - spacing_between * 0.5
            expense_start = center_x + spacing_between * 0.5
            expense_end = center_x + half_group

            self._draw_entry_columns(canvas, incomes, income_start, income_end, zero_y, scale, "#22c55e", above=True)
            self._draw_entry_columns(canvas, expenses, expense_start, expense_end, zero_y, scale, "#ef4444", above=True)

            label_y = zero_y + 18
            canvas.create_text(
                center_x,
                label_y,
                text=labels[idx],
                fill="#cbd5f5",
                anchor="n",
                font=("Segoe UI", 10),
            )

            bal = balance_values[idx]
            line_y = zero_y - bal * scale
            line_points.extend([center_x, line_y])

        if len(line_points) >= 4:
            canvas.create_line(*line_points, fill="#38bdf8", width=2, smooth=True)
        for i in range(0, len(line_points), 2):
            x = line_points[i]
            y = line_points[i + 1]
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill="#38bdf8", outline="#151a28")

    def _draw_entry_columns(
        self,
        canvas: tk.Canvas,
        entries: List[Transaction],
        start_x: float,
        end_x: float,
        zero_y: float,
        scale: float,
        color: str,
        above: bool,
    ) -> None:
        if not entries or end_x <= start_x:
            return
        entries = list(entries)
        count = len(entries)
        available_width = max(end_x - start_x, 10)
        spacing = 6 if count > 1 else 0
        effective_width = max(available_width - spacing * (count - 1), 4)
        bar_width = max(effective_width / count, 4)
        x = start_x
        for txn in entries:
            height = txn.amount * scale
            top = zero_y - height if above else zero_y
            bottom = zero_y if above else zero_y + height
            canvas.create_rectangle(x, top, x + bar_width, bottom, fill=color, outline="")
            canvas.create_text(
                x + bar_width / 2,
                top - 10 if above else bottom + 10,
                text=self.format_currency(txn.amount),
                fill="#cbd5f5",
                font=("Segoe UI", 8),
            )
            x += bar_width + spacing

    def start_edit_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Pasirinkimas", "Pasirinkite irasa kuri norite redaguoti.")
            return
        uid = selection[0]
        txn = next((item for item in self.transactions if item.uid == uid), None)
        if txn is None:
            messagebox.showerror("Redagavimas", "Nepavyko rasti pasirinkto iraso.")
            return
        self.editing_uid = uid
        self.date_var.set(txn.date)
        self.amount_var.set(f"{txn.amount:.2f}")
        self.category_var.set(txn.category)
        self.description_var.set(txn.description)
        self.kind_var.set(txn.kind)
        self.submit_button.config(text="Atnaujinti")

    def _on_tree_double_click(self, event: tk.Event) -> None:
        row_id = self.tree.identify_row(event.y) if hasattr(event, "y") else None
        if row_id or self.tree.selection():
            if row_id:
                self.tree.selection_set(row_id)
            self.start_edit_selected()

    def import_from_excel(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Pasirinkite faila importui",
            filetypes=(
                ("Excel failai", "*.xlsx *.xlsm *.xltx *.xltm"),
                ("CSV failai", "*.csv"),
                ("Visi failai", "*.*"),
            ),
        )
        if not file_path:
            return
        path = Path(file_path)
        extension = path.suffix.lower()

        try:
            if extension in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
                if openpyxl is None:
                    raise RuntimeError("Siai funkcijai reikia bibliotekos 'openpyxl'. Idiekite ja komanda 'pip install openpyxl'.")
                rows = self._read_excel(path)
            elif extension == ".csv":
                rows = self._read_csv(path)
            else:
                raise RuntimeError("Nepalaikomas failo formatas. Naudokite .xlsx arba .csv.")
        except Exception as exc:
            messagebox.showerror("Importo klaida", f"Nepavyko nuskaityti failo:\n{exc}")
            return

        if not rows:
            messagebox.showinfo("Importas", "Failas tuscias.")
            return

        header_row = rows[0]
        if self._row_has_letters(header_row):
            header = [self._normalize_header(value) for value in header_row]
            data_rows = rows[1:]
        else:
            header = [f"column_{idx}" for idx in range(len(header_row))]
            data_rows = rows

        special_mapping = self._detect_special_budget_layout(header)
        if not special_mapping:
            special_mapping = self._detect_special_budget_layout_by_order(len(header), data_rows)
        if special_mapping:
            self._import_special_budget(data_rows, special_mapping)
            return

        amount_idx = self._find_column(header, {"suma", "amount"})
        if amount_idx is None:
            messagebox.showerror("Importo klaida", "Failas turi tureti stulpeli 'Suma' arba 'Amount'.")
            return
        kind_idx = self._find_column(header, {"tipas", "type", "kind", "rusis"})
        category_idx = self._find_column(header, {"kategorija", "category"})
        description_idx = self._find_column(header, {"aprasymas", "aprasas", "description", "desc"})
        date_idx = self._find_column(header, {"data", "date"})

        need_month_prompt = date_idx is None or any(
            not self._get_cell(row, date_idx) for row in data_rows if any(row)
        )
        fallback_month = None
        fallback_days = None
        fallback_counter = 1
        if need_month_prompt:
            fallback_month = self._ask_for_month()
            if not fallback_month:
                return
            fallback_days = monthrange(fallback_month.year, fallback_month.month)[1]

        imported = 0
        skipped = 0
        for raw in data_rows:
            if not any(self._stringify(cell) for cell in raw):
                continue
            try:
                amount = self._parse_amount(self._get_cell(raw, amount_idx))
            except ValueError:
                skipped += 1
                continue
            kind_text = self._get_cell(raw, kind_idx) if kind_idx is not None else "expense"
            kind = self._parse_kind(kind_text)
            date_value = self._parse_date_value(self._get_cell(raw, date_idx)) if date_idx is not None else None
            if date_value is None:
                assert fallback_month is not None and fallback_days is not None
                day = min(fallback_counter, fallback_days)
                fallback_counter = fallback_counter + 1 if fallback_counter < fallback_days else 1
                date_value = fallback_month.replace(day=day)

            category_value = self._get_cell(raw, category_idx) if category_idx is not None else ""
            description_value = self._get_cell(raw, description_idx) if description_idx is not None else ""

            txn = Transaction(
                uid=uuid4().hex,
                date=date_value.strftime("%Y-%m-%d"),
                category=str(category_value).strip() or ("Pajamos" if kind == "income" else "Islaidos"),
                description=str(description_value).strip() or ("Pajamu irasas" if kind == "income" else "Islaida be aprasymo"),
                amount=round(amount, 2),
                kind=kind,
            )
            self.transactions.append(txn)
            imported += 1

        if imported:
            self.save_transactions()
            self.refresh_all()
            info = f"Sekmingai importuota {imported} irasu."
            if skipped:
                info += f" Praleista {skipped} eil. del netinkamu duomenu."
            messagebox.showinfo("Importas", info)
        else:
            messagebox.showinfo("Importas", "Nepavyko importuoti nei vieno iraso.")

    def _import_special_budget(self, rows: List[List[object]], column_map: dict[str, int]) -> None:
        if not rows:
            messagebox.showinfo("Importas", "Failas neturi duomenu.")
            return

        base_month = self._ask_for_month()
        if not base_month:
            return

        sequential_answer = messagebox.askyesnocancel(
            "Menesiu parinkimas",
            "Ar kiekviena lenteles eilute atitinka kita menesi? Pasirinkus Ne bus naudojamas tas pats menuo ir skirtingos dienos.",
        )
        if sequential_answer is None:
            return
        sequential_months = bool(sequential_answer)

        imported = 0
        for idx, raw in enumerate(rows):
            if not any(self._stringify(cell) for cell in raw):
                continue
            txn_date = self._month_for_special_row(base_month, idx, sequential_months)
            for key, spec in SPECIAL_BUDGET_COLUMNS.items():
                column_index = column_map.get(key)
                if column_index is None or column_index >= len(raw):
                    continue
                cell_value = self._get_cell(raw, column_index)
                if self._stringify(cell_value) == "":
                    continue
                try:
                    amount = self._parse_amount(cell_value)
                except ValueError:
                    continue
                if amount == 0:
                    continue
                amount_value = abs(amount)
                kind = spec["kind"]
                txn = Transaction(
                    uid=uuid4().hex,
                    date=txn_date.strftime("%Y-%m-%d"),
                    category=spec["category"],
                    description=spec["description"],
                    amount=round(amount_value, 2),
                    kind=kind if kind != "auto" else ("income" if amount >= 0 else "expense"),
                )
                self.transactions.append(txn)
                imported += 1

        if imported:
            self.save_transactions()
            self.refresh_all()
            messagebox.showinfo("Importas", f"Importuota {imported} irasu pagal specialia lentele.")
        else:
            messagebox.showinfo("Importas", "Nepavyko importuoti irasu is lenteles.")

    def _detect_special_budget_layout(self, header: List[str]) -> dict[str, int] | None:
        mapping: dict[str, int] = {}
        for key, spec in SPECIAL_BUDGET_COLUMNS.items():
            idx = self._find_column(header, spec["aliases"])
            if idx is not None:
                mapping[key] = idx
        return mapping or None

    def _detect_special_budget_layout_by_order(self, column_count: int, rows: List[List[object]]) -> dict[str, int] | None:
        order = ["alga", "nuoma", "komunaliniai", "maistas", "papildomai", "lieka"]
        mapping: dict[str, int] = {}
        column_index = 0
        for key in order:
            while column_index < column_count and not self._column_has_numeric(rows, column_index):
                column_index += 1
            if column_index >= column_count:
                break
            mapping[key] = column_index
            column_index += 1
        return mapping or None

    def _month_for_special_row(self, base: datetime, row_index: int, sequential_months: bool) -> datetime:
        if sequential_months:
            month = base.month - 1 + row_index
            year = base.year + month // 12
            month = month % 12 + 1
            day = min(base.day, monthrange(year, month)[1])
            return datetime(year, month, day)
        day = min(row_index + 1, monthrange(base.year, base.month)[1])
        return base.replace(day=day)

    def _column_has_numeric(self, rows: List[List[object]], index: int) -> bool:
        for row in rows:
            if index >= len(row):
                continue
            cell = self._get_cell(row, index)
            text = self._stringify(cell)
            if not text:
                continue
            try:
                self._parse_amount(cell)
                return True
            except ValueError:
                continue
        return False

    def _read_excel(self, path: Path) -> List[List[object]]:
        workbook = openpyxl.load_workbook(path, data_only=True)
        sheet = workbook.active
        rows: List[List[object]] = []
        for row in sheet.iter_rows(values_only=True):
            normalized = [value if value is not None else "" for value in row]
            rows.append(normalized)
        return rows

    def _read_csv(self, path: Path) -> List[List[object]]:
        with path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.reader(file)
            return [row for row in reader]

    @staticmethod
    def _normalize_header(value: object) -> str:
        text = (str(value) if value is not None else "").strip().lower()
        translation = str.maketrans(
            "\u0105\u010d\u0119\u0117\u012f\u0161\u0173\u016b\u017e\u0104\u010c\u0118\u0116\u012e\u0160\u0172\u016a\u017d",
            "aceeisuuzACEEISUUZ",
        )
        text = text.translate(translation)
        return "".join(ch for ch in text if ch.isalnum())

    @staticmethod
    def _find_column(header: List[str], targets: set[str]) -> int | None:
        for idx, name in enumerate(header):
            if name in targets:
                return idx
        return None

    @staticmethod
    def _get_cell(row: List[object], index: int | None) -> object:
        if index is None or index >= len(row):
            return ""
        return row[index]

    @staticmethod
    def _stringify(value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _parse_amount(value: object) -> float:
        if value is None or str(value).strip() == "":
            raise ValueError("Tuscia suma")
        if isinstance(value, (int, float)):
            return float(value)
        cleaned = str(value).replace("EUR", "").replace(",", ".").strip()
        return float(cleaned)

    @staticmethod
    def _parse_kind(value: object) -> str:
        text = (str(value) if value is not None else "").strip().lower()
        if text in {"pajamos", "income", "in", "pliusas"}:
            return "income"
        if text in {"islaidos", "islaidos", "expense", "out", "minusas"}:
            return "expense"
        return "expense"

    @staticmethod
    def _parse_date_value(value: object) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day)
        if isinstance(value, (int, float)):
            base = datetime(1899, 12, 30)
            return base + timedelta(days=float(value))
        text = str(value).strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%d.%m.%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None

    def _ask_for_month(self) -> datetime | None:
        while True:
            user_input = simpledialog.askstring(
                "Numatytas menuo",
                "Failo irasams nera nurodytos datos. Iveskite menesi formatu YYYY-MM:",
                parent=self.master,
            )
            if user_input is None:
                return None
            try:
                return datetime.strptime(user_input.strip(), "%Y-%m")
            except ValueError:
                messagebox.showerror("Netinkamas formatas", "Menuo turi buti formatu YYYY-MM, pvz, 2024-10.")

    @staticmethod
    def _row_has_letters(row: List[object]) -> bool:
        for cell in row:
            text = str(cell) if cell is not None else ""
            if any(ch.isalpha() for ch in text):
                return True
        return False

    def delete_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Pasirinkimas", "Pasirinkite bent viena irasa.")
            return
        if not messagebox.askyesno("Patvirtinimas", "Ar tikrai norite pasalinti pasirinktus irasus?"):
            return
        selected_ids = set(selected)
        self.transactions = [txn for txn in self.transactions if txn.uid not in selected_ids]
        self.save_transactions()
        self.refresh_all()


def main() -> None:
    root = tk.Tk()
    FinanceTracker(root)
    root.mainloop()


if __name__ == "__main__":
    main()
