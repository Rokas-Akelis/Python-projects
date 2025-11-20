#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI akcijų analizės demo su paprastu Monte Carlo ir ML pagrindu gauta istorine metine grąža.
- Optional: yfinance, numpy, pandas (jei įdiegta, ML mygtukas aktyvus ir naudoja realius duomenis)
- Jei opcionalių libs nėra, programa vis tiek veikia su demo parametrais.
"""
from __future__ import annotations
import importlib
import math
import os
import random
import statistics
import threading
import tkinter as tk
import sys
from datetime import datetime, timedelta
from tkinter import ttk, messagebox, scrolledtext, filedialog
import tkinter.font as tkfont
from typing import Tuple, Dict, Optional, TYPE_CHECKING, List

# Dynamic import of optional libs to avoid hard failures in environments without them
HAS_PYDATA = False
yf = None
np = None
pd = None
# Import pandas only for type checking to satisfy Pylance without forcing runtime import
if TYPE_CHECKING:
    import pandas as pd
try:
    _yf = importlib.import_module("yfinance")
    _np = importlib.import_module("numpy")
    _pd = importlib.import_module("pandas")
    yf, np, pd = _yf, _np, _pd
    HAS_PYDATA = True
    _import_err = ""
except Exception as exc:
    yf = np = pd = None
    HAS_PYDATA = False
    _import_err = repr(exc)

# new: environment / module info for debugging
PY_INFO = f"Python: {sys.executable}"
if HAS_PYDATA:
    try:
        libs = f"yfinance {getattr(yf,'__version__','?')}, numpy {getattr(np,'__version__','?')}, pandas {getattr(pd,'__version__','?')}"
    except Exception:
        libs = "libs detected"
else:
    libs = f"(yfinance / numpy / pandas nerasta)  import error: {_import_err}"
ENV_INFO = f"{PY_INFO}  |  {libs}"

# Demo parametrai (annual_return, annual_volatility, approx_last_price)
SAMPLE_PARAMS: Dict[str, Tuple[float, float, float]] = {
    "AAPL": (0.12, 0.30, 170.0),
    "MSFT": (0.10, 0.25, 330.0),
    "GOOG": (0.09, 0.28, 150.0),
    "AMZN": (0.08, 0.35, 140.0),
    "TSLA": (0.20, 0.60, 200.0),
}
DEFAULT_PARAMS = (0.07, 0.20, 100.0)
MAX_HISTORY_YEARS = 50


def get_params_for_ticker(ticker: str) -> Tuple[float, float, float]:
    return SAMPLE_PARAMS.get(ticker.upper(), DEFAULT_PARAMS)


def monte_carlo_gbm(amount: float, ann_return: float, ann_vol: float, years: int, sims: int = 2000, seed: Optional[int] = None):
    if seed is not None:
        random.seed(seed)
    results = []
    mu = math.log1p(ann_return)
    drift = (mu - 0.5 * ann_vol * ann_vol) * years
    diffusion_scale = ann_vol * math.sqrt(years)
    for _ in range(sims):
        z = random.gauss(0, 1)
        final = amount * math.exp(drift + diffusion_scale * z)
        results.append(final)
    results.sort()
    mean = statistics.mean(results)
    median = statistics.median(results)
    pct5 = results[max(0, int(0.05 * sims) - 1)]
    pct95 = results[min(sims - 1, int(0.95 * sims) - 1)]
    return {"mean": mean, "median": median, "pct5": pct5, "pct95": pct95, "all": results}


def recommendation_generic(years: int, ann_return: float) -> str:
    if years < 1:
        return "SHORT-TERM: HOLD / AVOID (demo rules)."
    if ann_return >= 0.06:
        return "LONG-TERM: BUY (historical annualized return ≥ 6%)."
    if 0.0 < ann_return < 0.06:
        return "LONG-TERM: HOLD (mild positive returns)."
    return "LONG-TERM: CAUTION / AVOID (historical returns negative)."


def format_currency(x: float) -> str:
    return f"{x:,.2f}"


# ---------------- ML / history helpers ----------------
def fetch_history_yf(ticker: str, years: int = MAX_HISTORY_YEARS):
    if not HAS_PYDATA:
        raise RuntimeError("yfinance / pandas / numpy not available")
    years = max(1, min(int(years), MAX_HISTORY_YEARS))
    t = yf.Ticker(ticker)
    df = t.history(period="max", auto_adjust=True)
    if df.empty:
        raise ValueError("Nerasta istorinių duomenų per yfinance.")
    if "Close" not in df.columns:
        raise ValueError("Istoriniai duomenys neturi 'Close' stulpelio.")
    df = df.copy()
    try:
        df.index = df.index.tz_localize(None)
    except (AttributeError, TypeError, ValueError):
        pass
    cutoff = pd.Timestamp.today() - pd.DateOffset(years=years)
    df = df[df.index >= cutoff]
    if df.empty:
        raise ValueError(f"Duomenų už pask. {years} metų nerasta.")
    return df[["Close"]].copy()


def analyze_history_trend(df_close: "pd.DataFrame"): # type: ignore
    """
    Returns: last_price, annualized return, annualized volatility, linear log-price slope (per year), n_obs
    Robust index -> numeric conversion to support different pandas versions / timezone-aware indexes.
    """
    series = df_close["Close"].dropna()
    if series.empty:
        raise ValueError("Tuščias kainų series.")
    # log returns
    returns = np.log(series / series.shift(1)).dropna()
    mean_daily = float(returns.mean()) if not returns.empty else 0.0
    vol_daily = float(returns.std(ddof=0)) if not returns.empty else 0.0
    ann_return = math.expm1(mean_daily * 252)
    ann_vol = vol_daily * math.sqrt(252)
    last_price = float(series.iloc[-1])

    # robust conversion of datetime index -> int64 nanoseconds
    try:
        idx = pd.DatetimeIndex(series.index)
        x_ns = idx.view("int64")
    except Exception:
        try:
            x_ns = series.index.to_numpy(dtype="datetime64[ns]").astype("int64")
        except Exception:
            # fallback numeric positions
            x_ns = np.arange(len(series), dtype="int64")

    x_secs = (x_ns - int(x_ns[0])) / 1e9
    x_years = x_secs / (3600 * 24 * 365.25)
    y = np.log(series.values.astype(float))

    slope_annual = 0.0
    trend_intercept = math.log(last_price) if last_price > 0 else 0.0
    if len(x_years) >= 2:
        slope, intercept = np.polyfit(x_years, y, 1)
        slope_annual = float(slope)
        trend_intercept = float(intercept)

    return {
        "last_price": last_price,
        "ann_return": float(ann_return),
        "ann_vol": float(ann_vol),
        "slope_annual": slope_annual,
        "trend_intercept": trend_intercept,
        "n_obs": len(series),
    }


# ---------------- GUI ----------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Akcijų analizės demo — GUI + ML")
        self.geometry("980x680")
        self._build_ui()

    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        bg = "#0f172a"
        card_bg = "#111827"
        accent = "#38bdf8"
        text = "#e2e8f0"
        muted = "#94a3b8"

        self.configure(bg=bg)
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(family="Segoe UI", size=10)
        self.option_add("*Font", default_font)

        style.configure("TFrame", background=bg)
        style.configure("Card.TFrame", background=card_bg)
        style.configure("Hero.TFrame", background=card_bg)
        style.configure("Heading.TLabel", background=card_bg, foreground=text, font=("Segoe UI", 12, "bold"))
        style.configure("HeroTitle.TLabel", background=card_bg, foreground=text, font=("Segoe UI", 18, "bold"))
        style.configure("HeroSub.TLabel", background=card_bg, foreground=muted, font=("Segoe UI", 11))
        style.configure("Card.TLabel", background=card_bg, foreground=text)
        style.configure("Muted.TLabel", background=card_bg, foreground=muted)
        style.configure("Warning.TLabel", background=card_bg, foreground="#fbbf24")
        style.configure("Card.TCheckbutton", background=card_bg, foreground=text)
        style.map("Card.TCheckbutton", background=[("active", card_bg)], foreground=[("disabled", "#475569")])
        style.configure("Modern.TEntry", fieldbackground="#0b1120", foreground=text, bordercolor="#1f2937", lightcolor=accent, padding=6)
        style.configure("Accent.TButton", background=accent, foreground="#0f172a", padding=(14, 8), borderwidth=0, focusthickness=1, focuscolor=accent)
        style.map("Accent.TButton", background=[("active", "#0ea5e9"), ("pressed", "#0284c7")], foreground=[("disabled", "#1e293b")])
        style.configure("Ghost.TButton", background="#1f2937", foreground=text, padding=(12, 6), borderwidth=0)
        style.map("Ghost.TButton", background=[("active", "#334155"), ("pressed", "#1f2937")])
        style.configure("Status.TLabel", background="#0b1120", foreground=muted, padding=(12, 4))

        container = ttk.Frame(self, style="TFrame", padding=24)
        container.pack(fill="both", expand=True)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(1, weight=1)

        hero = ttk.Frame(container, style="Hero.TFrame", padding=(20, 16))
        hero.grid(row=0, column=0, columnspan=2, sticky="ew")
        hero.columnconfigure(0, weight=1)
        ttk.Label(hero, text="Akcijų analizės studija", style="HeroTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(hero, text="Monte Carlo + istorinių duomenų įžvalgos viename lange", style="HeroSub.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))

        controls = ttk.Frame(container, style="Card.TFrame", padding=(18, 18))
        controls.grid(row=1, column=0, sticky="ns", padx=(0, 18), pady=(16, 0))
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Įvesties parametrai", style="Heading.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.ticker_var = tk.StringVar(value="AAPL")
        ttk.Label(controls, text="Ticker:", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(controls, textvariable=self.ticker_var, width=16, style="Modern.TEntry").grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(controls, text="Suma (€):", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=4)
        self.amount_var = tk.StringVar(value="1000")
        ttk.Entry(controls, textvariable=self.amount_var, width=16, style="Modern.TEntry").grid(row=2, column=1, sticky="ew", pady=4)

        ttk.Label(controls, text="Laikotarpis (metai):", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=4)
        self.years_var = tk.StringVar(value="3")
        ttk.Entry(controls, textvariable=self.years_var, width=16, style="Modern.TEntry").grid(row=3, column=1, sticky="ew", pady=4)

        ttk.Label(controls, text="Simuliacijų sk.:", style="Card.TLabel").grid(row=4, column=0, sticky="w", pady=4)
        self.sims_var = tk.StringVar(value="2000")
        ttk.Entry(controls, textvariable=self.sims_var, width=16, style="Modern.TEntry").grid(row=4, column=1, sticky="ew", pady=4)

        self.seed_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="Deterministinis (seed=0)", variable=self.seed_var, style="Card.TCheckbutton").grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))

        self.use_live_var = tk.BooleanVar(value=HAS_PYDATA)
        ttk.Checkbutton(controls, text="Naudoti gyvą istoriją (yfinance)", variable=self.use_live_var, style="Card.TCheckbutton").grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        if not HAS_PYDATA:
            ttk.Label(controls, text="(yfinance / numpy / pandas nerasta)", style="Warning.TLabel").grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Separator(controls, orient="horizontal").grid(row=8, column=0, columnspan=2, sticky="ew", pady=(12, 12))

        btns = ttk.Frame(controls, style="Card.TFrame")
        btns.grid(row=9, column=0, columnspan=2, sticky="ew")
        btns.columnconfigure(0, weight=1)
        ttk.Button(btns, text="Paleisti simuliaciją", style="Accent.TButton", command=self.on_run).grid(row=0, column=0, sticky="ew")
        action_bar = ttk.Frame(btns, style="Card.TFrame")
        action_bar.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.ml_btn = ttk.Button(action_bar, text="ML analizė", style="Ghost.TButton", command=self.on_ml)
        self.ml_btn.pack(side="left")
        ttk.Button(action_bar, text="Išvalyti", style="Ghost.TButton", command=self.clear_output).pack(side="left", padx=6)
        ttk.Button(action_bar, text="Išsaugoti", style="Ghost.TButton", command=self.save_report).pack(side="left", padx=6)

        if not HAS_PYDATA:
            self.ml_btn.state(["disabled"])

        right = ttk.Frame(container, style="Card.TFrame", padding=(20, 20))
        right.grid(row=1, column=1, sticky="nsew", pady=(16, 0))
        ttk.Label(right, text="Rezultatai", style="Heading.TLabel").pack(anchor="w")
        self.output = scrolledtext.ScrolledText(right, wrap="word", height=20, borderwidth=0, highlightthickness=0)
        self.output.pack(fill="both", expand=True, pady=(12, 0))
        self.output.configure(font=("Consolas", 10), background="#0b1120", foreground=text, insertbackground=accent)
        ttk.Label(right, text="ML grafikas", style="Heading.TLabel").pack(anchor="w", pady=(16, 4))
        self.chart_canvas = tk.Canvas(right, height=220, background="#020617", highlightthickness=0, bd=0)
        self.chart_canvas.pack(fill="x")
        ttk.Label(right, text="Pelno projekcija", style="Heading.TLabel").pack(anchor="w", pady=(16, 4))
        self.profit_canvas = tk.Canvas(right, height=160, background="#020617", highlightthickness=0, bd=0)
        self.profit_canvas.pack(fill="x")

        self.status_var = tk.StringVar(value=ENV_INFO)
        status = ttk.Label(self, textvariable=self.status_var, anchor="w", style="Status.TLabel")
        status.pack(fill="x", side="bottom")
        self.render_chart()
        self.render_profit_chart()

      

    def _write(self, text: str = ""):
        self.output.insert("end", text + "\n")
        self.output.see("end")

    def clear_output(self):
        self.output.delete("1.0", "end")

    def set_status(self, txt: str):
        self.status_var.set(txt)
        self.update_idletasks()

    def _run_in_thread(self, func, on_success, on_error=None):
        def runner():
            try:
                result = func()
            except Exception as exc:  # pragma: no cover - GUI message routing
                handler = on_error or self._handle_background_error
                self.after(0, lambda: handler(exc))
                return
            self.after(0, lambda: on_success(result))

        threading.Thread(target=runner, daemon=True).start()

    def _handle_background_error(self, exc: Exception):
        self._show_error("Klaida", exc)

    def _show_error(self, title: str, exc: Exception):
        messagebox.showerror(title, str(exc))
        self.set_status("Ready")

    def render_chart(self, price_points: Optional[List[Tuple[float, float]]] = None, trend_points: Optional[List[Tuple[float, float]]] = None):
        canvas = getattr(self, "chart_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        canvas.update_idletasks()
        width = int(canvas.winfo_width() or canvas["width"])
        height = int(canvas.winfo_height() or canvas["height"])
        if not price_points:
            canvas.create_text(width // 2, height // 2, fill="#475569", text="ML grafikas bus parodytas paleidus ML analizę")
            return

        combined = list(price_points)
        if trend_points:
            combined += list(trend_points)
        xs = [p[0] for p in combined]
        ys = [p[1] for p in combined]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        x_pad, y_pad = 30, 24
        span_x = max(max_x - min_x, 1e-9)
        span_y = max(max_y - min_y, 1e-9)

        def to_canvas(point):
            x, y = point
            cx = x_pad + (x - min_x) / span_x * (width - 2 * x_pad)
            cy = y_pad + (max_y - y) / span_y * (height - 2 * y_pad)
            return cx, cy

        # axes and grid
        grid_color = "#1f2937"
        axis_color = "#1e293b"
        canvas.create_line(x_pad, y_pad, x_pad, height - y_pad, fill=axis_color)
        canvas.create_line(x_pad, height - y_pad, width - x_pad, height - y_pad, fill=axis_color)
        for frac in (0.25, 0.5, 0.75):
            y = y_pad + frac * (height - 2 * y_pad)
            canvas.create_line(x_pad, y, width - x_pad, y, fill=grid_color, dash=(2, 4))

        def draw_series(points, color, width_px=2, dash=None):
            coords = []
            for pt in points:
                coords.extend(to_canvas(pt))
            if len(coords) >= 4:
                canvas.create_line(*coords, fill=color, width=width_px, smooth=True, dash=dash)

        draw_series(price_points, "#38bdf8", width_px=2)
        if trend_points:
            draw_series(trend_points, "#f472b6", width_px=2, dash=(4, 2))

        # annotate latest price
        latest = price_points[-1]
        lx, ly = to_canvas(latest)
        canvas.create_oval(lx - 3, ly - 3, lx + 3, ly + 3, fill="#38bdf8", outline="")
        canvas.create_text(lx + 8, ly - 10, anchor="w", fill="#cbd5f5", font=("Segoe UI", 9), text=f"{latest[1]:,.2f} €")

        # axis labels
        label_color = "#94a3b8"
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = y_pad + frac * (height - 2 * y_pad)
            value = max_y - (max_y - min_y) * frac
            canvas.create_text(4, y, anchor="w", fill=label_color, font=("Segoe UI", 9), text=f"{value:,.2f} €")

        start_dt = datetime.fromtimestamp(min_x)
        end_dt = datetime.fromtimestamp(max_x)
        canvas.create_text(x_pad, height - y_pad + 14, anchor="w", fill=label_color, font=("Segoe UI", 9),
                           text=start_dt.strftime("%Y-%m-%d"))
        canvas.create_text(width - x_pad, height - y_pad + 14, anchor="e", fill=label_color, font=("Segoe UI", 9),
                           text=end_dt.strftime("%Y-%m-%d"))

        canvas.create_text(x_pad, y_pad - 8, anchor="w", fill="#94a3b8", font=("Segoe UI", 9), text="Istorinė kaina")
        if trend_points:
            canvas.create_text(x_pad + 180, y_pad - 8, anchor="w", fill="#c084fc", font=("Segoe UI", 9), text="Linijinė log-trend prognozė")

    def render_profit_chart(self, profit_points: Optional[List[Tuple[float, float]]] = None, investment: float = 0.0, years: int = 0):
        canvas = getattr(self, "profit_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        canvas.update_idletasks()
        width = int(canvas.winfo_width() or canvas["width"])
        height = int(canvas.winfo_height() or canvas["height"])
        if not profit_points:
            canvas.create_text(width // 2, height // 2, fill="#475569", text="Pelno grafikas pasirodys paleidus ML analizę su įvesta suma")
            return

        x_pad, y_pad = 40, 24
        xs = [p[0] for p in profit_points]
        ys = [p[1] for p in profit_points]
        min_x, max_x = min(xs), max(xs)
        min_y = min(ys + [0.0])
        max_y = max(ys + [0.0])
        span_x = max(max_x - min_x, 1e-6)
        span_y = max(max_y - min_y, 1e-6)

        def to_canvas(pt):
            x, y = pt
            cx = x_pad + (x - min_x) / span_x * (width - 2 * x_pad)
            cy = y_pad + (max_y - y) / span_y * (height - 2 * y_pad)
            return cx, cy

        axis_color = "#1e293b"
        grid_color = "#1f2937"
        canvas.create_line(x_pad, y_pad, x_pad, height - y_pad, fill=axis_color)
        canvas.create_line(x_pad, height - y_pad, width - x_pad, height - y_pad, fill=axis_color)

        for frac in (0.25, 0.5, 0.75):
            y = y_pad + frac * (height - 2 * y_pad)
            canvas.create_line(x_pad, y, width - x_pad, y, fill=grid_color, dash=(2, 4))

        zero_y = None
        if min_y < 0 < max_y:
            zero_y = to_canvas((min_x, 0))[1]
            canvas.create_line(x_pad, zero_y, width - x_pad, zero_y, fill="#475569", dash=(3, 3))

        coords = []
        for pt in profit_points:
            coords.extend(to_canvas(pt))
        if len(coords) >= 4:
            canvas.create_line(*coords, fill="#34d399", width=2, smooth=True)

        latest = profit_points[-1]
        lx, ly = to_canvas(latest)
        canvas.create_oval(lx - 3, ly - 3, lx + 3, ly + 3, fill="#34d399", outline="")
        canvas.create_text(lx + 8, ly - 10, anchor="w", fill="#bbf7d0", font=("Segoe UI", 9), text=f"{latest[1]:,.2f} €")

        label_color = "#94a3b8"
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = y_pad + frac * (height - 2 * y_pad)
            value = max_y - (max_y - min_y) * frac
            canvas.create_text(4, y, anchor="w", fill=label_color, font=("Segoe UI", 9), text=f"{value:,.2f} €")

        canvas.create_text(x_pad, height - y_pad + 14, anchor="w", fill=label_color, font=("Segoe UI", 9), text=f"0 m.")
        canvas.create_text(width - x_pad, height - y_pad + 14, anchor="e", fill=label_color, font=("Segoe UI", 9), text=f"{years} m.")
        canvas.create_text(x_pad, y_pad - 8, anchor="w", fill=label_color, font=("Segoe UI", 9),
                           text=f"Potencialus pelnas (investicija {format_currency(investment)} €)")

    def on_run(self):
        try:
            ticker = self.ticker_var.get().strip().upper()
            if not ticker:
                raise ValueError("Ticker privalomas.")
            amount = float(self.amount_var.get().strip().replace(",", "") or 0)
            years = int(self.years_var.get().strip() or 0)
            sims = int(self.sims_var.get().strip() or 0)
            if amount <= 0 or years <= 0 or sims <= 0:
                raise ValueError("Suma, metai ir simuliacijų skaičius turi būti > 0.")
        except Exception as e:
            messagebox.showerror("Input klaida", str(e))
            return

        use_live_requested = bool(self.use_live_var.get())
        use_live = use_live_requested and HAS_PYDATA
        history_years = max(1, min(years, MAX_HISTORY_YEARS))
        seed = 0 if self.seed_var.get() else None

        self.set_status("Running simulation...")
        self.clear_output()
        self._write("Simuliacija vykdoma, prašome palaukti...")

        def do_all():
            base_return, base_vol, base_price = get_params_for_ticker(ticker)
            ann_return = base_return
            ann_vol = base_vol
            last_price = base_price
            info_lines = []
            history_info = None
            source = "demo"

            if use_live:
                try:
                    df = fetch_history_yf(ticker, years=history_years)
                    info = analyze_history_trend(df)
                    ann_return = info["ann_return"]
                    ann_vol = info["ann_vol"]
                    last_price = info["last_price"]
                    history_info = {
                        "n_obs": info["n_obs"],
                        "history_years": history_years,
                        "slope": info["slope_annual"],
                        "ann_return": ann_return,
                        "ann_vol": ann_vol,
                    }
                    source = "live"
                except Exception as exc:
                    info_lines.append(f"Live duomenų klaida: {exc}. Naudojami demo parametrai.")
            elif use_live_requested and not HAS_PYDATA:
                info_lines.append("Live istorija nepasiekiama: trūksta yfinance/numpy/pandas.")

            rec = recommendation_generic(years, ann_return)
            sim = monte_carlo_gbm(amount, ann_return, ann_vol, years, sims=sims, seed=seed)
            return {
                "ticker": ticker,
                "amount": amount,
                "years": years,
                "sims": sims,
                "sim": sim,
                "rec": rec,
                "ann_return": ann_return,
                "ann_vol": ann_vol,
                "last_price": last_price,
                "info_lines": info_lines,
                "history_info": history_info,
                "source": source,
            }

        def on_success(payload):
            self.render_chart()
            self.render_profit_chart()
            sim = payload["sim"]
            amount_local = payload["amount"]
            years_local = payload["years"]
            sims_local = payload["sims"]
            last_price = payload["last_price"]
            ann_return_local = payload["ann_return"]
            ann_vol_local = payload["ann_vol"]
            rec_local = payload["rec"]

            self.clear_output()
            self._write("=== Įvestis ===")
            self._write(f"Ticker: {payload['ticker']}")
            self._write(f"Suma: {format_currency(amount_local)} €")
            self._write(f"Laikotarpis: {years_local} metai")
            self._write("")
            if payload["source"] == "live":
                hist = payload["history_info"] or {}
                years_used = hist.get("history_years", history_years)
                self._write(f"--- Istoriniai parametrai (yfinance, {years_used} m. langas) ---")
                self._write(f"Paskutinė kaina: {format_currency(last_price)} €")
                self._write(f"Metinė grąža (hist): {ann_return_local*100:.2f}%")
                self._write(f"Metinė volatilumas (hist): {ann_vol_local*100:.2f}%")
                slope = hist.get("slope")
                if slope is not None:
                    self._write(f"Log-kainos metinė nuolydis: {slope:.6f} (exp-1 ≈ {math.expm1(slope)*100:.2f}%)")
                self._write(f"Istorinių įrašų sk.: {hist.get('n_obs', 'n/a')}")
            else:
                self._write("--- Demo parametrai ---")
                self._write(f"Paskutinė kaina (approx): {format_currency(last_price)} €")
                self._write(f"Metinė grąža (demo): {ann_return_local*100:.2f}%")
                self._write(f"Metinė volatilumas (demo): {ann_vol_local*100:.2f}%")
            self._write(f"\nRekomendacija: {rec_local}\n")

            for line in payload["info_lines"]:
                self._write(line)

            self._write("--- Projekcija (Monte Carlo) ---")
            self._write(f"Simuliacijų sk.: {sims_local}")
            self._write(f"Vidutinė galutinė suma: {format_currency(sim['mean'])} €")
            self._write(f"Mediana (50%): {format_currency(sim['median'])} €")
            self._write(f"5% kvantilis: {format_currency(sim['pct5'])} €")
            self._write(f"95% kvantilis: {format_currency(sim['pct95'])} €")
            profit_mean = sim["mean"] - amount_local
            profit_median = sim["median"] - amount_local
            self._write("\n--- Potencialus uždarbis ---")
            self._write(f"Vidutiniškai (+/-): {format_currency(profit_mean)} €")
            self._write(f"Mediana (+/-): {format_currency(profit_median)} €")
            self._write("\nPastaba: analizė yra edukacinė, tai nėra finansinis patarimas.")
            self.set_status("Simulation finished")

        self._run_in_thread(do_all, on_success, lambda exc: self._show_error("Simuliacijos klaida", exc))

    def on_ml(self):
        if not HAS_PYDATA:
            messagebox.showinfo("ML nepasiekiama", "ML/Live istorija nepasiekiama (reikalauja yfinance, pandas, numpy).")
            return
        if not self.use_live_var.get():
            messagebox.showinfo("ML išjungta", "Pažymėkite 'Naudoti gyvą istoriją (yfinance)' norėdami naudoti ML.")
            return

        try:
            ticker = self.ticker_var.get().strip().upper()
            if not ticker:
                raise ValueError("Ticker privalomas.")
            years = int(self.years_var.get().strip() or 0)
            sims = int(self.sims_var.get().strip() or 1000)
            amount = float(self.amount_var.get().strip().replace(",", "") or 0)
            if years <= 0 or sims <= 0:
                raise ValueError("Metai ir simuliacijų skaičius turi būti > 0.")
        except Exception as e:
            messagebox.showerror("Input klaida", str(e))
            return

        history_years = max(1, min(years, MAX_HISTORY_YEARS))
        seed = 0 if self.seed_var.get() else None
        self.set_status("Running ML analysis...")
        self.clear_output()
        self._write("ML analizė vykdoma, prašome palaukti...")

        def do_ml():
            df = fetch_history_yf(ticker, years=history_years)
            info = analyze_history_trend(df)
            slope = info["slope_annual"]
            last_price = info["last_price"]
            ann_return_hist = info["ann_return"]
            ann_vol_hist = info["ann_vol"]
            predicted_price = last_price * math.exp(slope * years)
            sim_amount = amount if amount > 0 else last_price
            mc = monte_carlo_gbm(sim_amount, ann_return_hist, ann_vol_hist, years, sims=sims, seed=seed)
            chart_points: List[Tuple[float, float]] = []
            trend_points: List[Tuple[float, float]] = []
            if not df.empty:
                series = df["Close"]
                idx = series.index
                base_dt = idx[0].to_pydatetime()
                step = max(1, len(series) // 250)
                sampled_prices = series.iloc[::step] if step > 1 else series
                for ts, price in sampled_prices.items():
                    chart_points.append((ts.timestamp(), float(price)))
                intercept = info.get("trend_intercept", math.log(last_price) if last_price > 0 else 0.0)

                def years_since(ts_obj):
                    return (ts_obj.to_pydatetime() - base_dt).total_seconds() / (3600 * 24 * 365.25)

                sampled_idx = idx[::step] if step > 1 else idx
                for ts in sampled_idx:
                    years_offset = years_since(ts)
                    trend_price = math.exp(intercept + slope * years_offset)
                    trend_points.append((ts.timestamp(), float(trend_price)))
                future_ts = idx[-1] + pd.DateOffset(years=years)
                future_years = years_since(future_ts)
                future_price = math.exp(intercept + slope * future_years)
                trend_points.append((future_ts.timestamp(), float(future_price)))

            profit_points: List[Tuple[float, float]] = []
            invest_amount = amount if amount > 0 else last_price
            if invest_amount > 0 and years > 0:
                steps = max(2, min(240, years * 12))
                growth_base = 1.0 + ann_return_hist
                for i in range(steps + 1):
                    t = years * i / steps
                    if growth_base > 0:
                        value = invest_amount * (growth_base ** t)
                    else:
                        value = invest_amount
                    profit_points.append((t, value - invest_amount))
            return {
                "info": info,
                "predicted_price": predicted_price,
                "mc": mc,
                "sim_amount": sim_amount,
                "history_years": history_years,
                "years": years,
                "ann_return_hist": ann_return_hist,
                "chart_points": chart_points,
                "trend_points": trend_points,
                "profit_points": profit_points,
                "investment_amount": invest_amount,
            }

        def on_success(payload):
            info = payload["info"]
            mc = payload["mc"]
            predicted_price = payload["predicted_price"]
            sim_amount = payload["sim_amount"]
            history_years_used = payload["history_years"]
            ann_return_hist = payload["ann_return_hist"]
            slope = info["slope_annual"]
            last_price = info["last_price"]
            ann_vol_hist = info["ann_vol"]
            n_obs = info["n_obs"]
            target_years = payload["years"]
            investment_amount = payload["investment_amount"]

            self.clear_output()
            self._write("=== ML / History Analysis ===")
            self._write(f"Ticker: {ticker}")
            history_line = f"Istorijos langas: {history_years_used} m."
            if history_years_used != target_years:
                history_line += f" (apribota iki {MAX_HISTORY_YEARS} m.)"
            self._write(history_line)
            self._write(f"Available history observations: {n_obs}")
            self._write(f"Last price: {format_currency(last_price)}")
            self._write("")
            self._write("--- Historical stats (from data) ---")
            self._write(f"Annualized return (hist): {ann_return_hist*100:.2f}%")
            self._write(f"Annualized volatility (hist): {ann_vol_hist*100:.2f}%")
            self._write(f"Log-price linear slope (annual): {slope:.6f} (exp(slope)-1 ≈ {math.expm1(slope)*100:.2f}%)")
            self._write("")
            self._write(f"Predicted price after {target_years} years (linear log-trend): {format_currency(predicted_price)}")
            self._write("")
            self._write("--- Monte Carlo (using historical ann_return/vol) ---")
            self._write(f"Simuliacijų sk.: {sims}")
            self._write(f"Mean final (for amount {format_currency(sim_amount)}): {format_currency(mc['mean'])}")
            self._write(f"Median final: {format_currency(mc['median'])}")
            self._write(f"5% - 95%: {format_currency(mc['pct5'])}  -  {format_currency(mc['pct95'])}")
            self._write("")
            rec = recommendation_generic(target_years, ann_return_hist)
            self._write(f"Rekomendacija (remiantis istorija): {rec}")
            self._write("\nPastaba: ML dalis (lin.regress) yra paprasta aproksimacija; tai nėra finansinis patarimas.")
            self.render_chart(payload["chart_points"], payload["trend_points"])
            self.render_profit_chart(payload["profit_points"], investment_amount, target_years)
            self.set_status("ML analysis finished")

        self._run_in_thread(do_ml, on_success, lambda exc: self._show_error("ML analizės klaida", exc))

    def save_report(self):
        txt = self.output.get("1.0", "end").strip()
        if not txt:
            messagebox.showinfo("Report", "Nėra ką išsaugoti.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(txt)
            messagebox.showinfo("Išsaugota", f"Ataskaita išsaugota: {os.path.abspath(path)}")
        except Exception as e:
            messagebox.showerror("Klaida", str(e))


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
