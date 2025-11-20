#!/usr/bin/env python3
"""Modernus iprociu seklys su korteliu stiliumi, lentelėmis ir motyvacijos citatomis."""

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk
from typing import Optional

import requests
from bs4 import BeautifulSoup
from sqlalchemy import Column, Date, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

engine = create_engine('sqlite:///habits.db', echo=False)
Session = sessionmaker(bind=engine)
Base = declarative_base()


class Habit(Base):
    """ORM objektas, saugantis iprocio apibūdinimą ir susietus žurnalus."""

    __tablename__ = 'habits'

    id = Column(Integer, primary_key=True)
    category = Column(String, nullable=False)
    desc = Column(String, default='')
    created_at = Column(Date, default=date.today)
    logs = relationship('Log', back_populates='habit', cascade='all, delete-orphan')

    @property
    def summary(self) -> str:
        return f'{self.created_at:%Y-%m-%d} | {self.category}: {self.desc}'


class Log(Base):
    """ORM objektas, registruojantis konkrečios dienos pažangą."""

    __tablename__ = 'logs'

    id = Column(Integer, primary_key=True)
    habit_id = Column(Integer, ForeignKey('habits.id'))
    date = Column(Date, default=date.today)
    status = Column(String)
    note = Column(String, default='')
    habit = relationship('Habit', back_populates='logs')


Base.metadata.create_all(engine)


class App(tk.Tk):
    """Pagrindinis tkinter langas su kortelėmis, lentelėmis ir citatomis."""

    def __init__(self) -> None:
        super().__init__()
        self.title('Įpročių studija')
        self.geometry('1100x720')
        self.minsize(980, 620)

        self.colors = {
            'bg': '#0f172a',
            'card': '#1f2937',
            'accent': '#38bdf8',
            'muted': '#94a3b8',
            'success': '#22c55e',
            'danger': '#ef4444',
        }
        self.configure(bg=self.colors['bg'])

        self.session = Session()
        self.categories = [
            'Sportas', 'Mityba', 'Hobis', 'Skaitymas', 'Mokymasis', 'Meditacija', 'Poilsis'
        ]
        self.active_habit_id: Optional[int] = None
        self.status_after: Optional[str] = None

        self.category_var = tk.StringVar()
        self.desc_var = tk.StringVar()
        self.status_field = tk.StringVar(value='padaryta')
        self.note_var = tk.StringVar()
        self.quote_var = tk.StringVar(value='Gaivinkite įkvėpimą nauja citata.')
        self.feedback_var = tk.StringVar(value='Pasiruošę naujam įpročiui.')
        self.habits_title_var = tk.StringVar(value='Visi įpročiai')
        self.logs_title_var = tk.StringVar(value='Žurnalas (0)')

        self.setup_styles()
        self.build_layout()
        self.load_habits()

    def setup_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        style.configure('App.TFrame', background=self.colors['bg'])
        style.configure('Card.TFrame', background=self.colors['card'])
        style.configure('Hero.TLabel', background=self.colors['card'], foreground='white',
                        font=('Segoe UI', 24, 'bold'))
        style.configure('HeroSub.TLabel', background=self.colors['card'], foreground=self.colors['muted'],
                        font=('Segoe UI', 11))
        style.configure('Quote.TLabel', background=self.colors['card'], foreground='#e2e8f0',
                        font=('Segoe UI', 11, 'italic'), wraplength=720, justify='left')
        style.configure('CardHeading.TLabel', background=self.colors['card'], foreground='white',
                        font=('Segoe UI Semibold', 12))
        style.configure('CardBody.TLabel', background=self.colors['card'], foreground=self.colors['muted'],
                        font=('Segoe UI', 10))
        style.configure('Primary.TButton', background=self.colors['accent'], foreground='#0f172a',
                        font=('Segoe UI Semibold', 10), padding=8)
        style.map('Primary.TButton',
                  background=[('active', '#22d3ee'), ('pressed', '#0ea5e9')],
                  foreground=[('pressed', '#0f172a')])
        style.configure('Danger.TButton', background=self.colors['danger'], foreground='white',
                        font=('Segoe UI Semibold', 10), padding=8)
        style.map('Danger.TButton',
                  background=[('active', '#dc2626'), ('pressed', '#b91c1c')])
        style.configure('Ghost.TButton', background=self.colors['card'], foreground=self.colors['muted'],
                        font=('Segoe UI', 9), padding=6)
        style.map('Ghost.TButton', background=[('active', self.colors['bg'])],
                  foreground=[('active', 'white')])
        style.configure('Status.TLabel', background=self.colors['bg'], foreground=self.colors['muted'],
                        font=('Segoe UI', 10))

        style.configure('Modern.Treeview', background=self.colors['card'], foreground='white',
                        fieldbackground=self.colors['card'], bordercolor=self.colors['bg'],
                        borderwidth=0, rowheight=32)
        style.configure('Modern.Treeview.Heading', background=self.colors['card'],
                        foreground=self.colors['muted'], borderwidth=0, font=('Segoe UI Semibold', 10))
        style.map('Modern.Treeview', background=[('selected', '#334155')], foreground=[('selected', 'white')])
        style.layout('Modern.Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])

    def build_layout(self) -> None:
        container = ttk.Frame(self, style='App.TFrame')
        container.pack(fill='both', expand=True)

        hero = ttk.Frame(container, style='Card.TFrame', padding=(28, 24))
        hero.pack(fill='x', padx=24, pady=(24, 12))
        hero.columnconfigure(0, weight=1)

        ttk.Label(hero, text='Įpročių studija', style='Hero.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(hero, text='Matykite savo progresą vienoje vietoje ir gaukite kasdienio įkvėpimo.',
                  style='HeroSub.TLabel').grid(row=1, column=0, sticky='w', pady=(4, 0))

        ttk.Button(hero, text='Gaivinti įkvėpimą', style='Primary.TButton',
                   command=self.fetch_quote).grid(row=0, column=1, rowspan=2, padx=(12, 0))

        ttk.Label(hero, textvariable=self.quote_var, style='Quote.TLabel').grid(
            row=2, column=0, columnspan=2, sticky='we', pady=(16, 0))

        body = ttk.Frame(container, style='App.TFrame')
        body.pack(fill='both', expand=True, padx=24, pady=(0, 8))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        left_column = ttk.Frame(body, style='App.TFrame')
        left_column.grid(row=0, column=0, sticky='nsew', padx=(0, 16))
        left_column.columnconfigure(0, weight=1)

        self.build_habit_form(left_column)
        self.build_log_form(left_column)

        right_column = ttk.Frame(body, style='App.TFrame')
        right_column.grid(row=0, column=1, sticky='nsew')
        right_column.rowconfigure(0, weight=1)
        right_column.rowconfigure(1, weight=1)

        self.build_habit_table(right_column)
        self.build_log_table(right_column)

        status_bar = ttk.Frame(container, style='App.TFrame')
        status_bar.pack(fill='x', padx=24, pady=(0, 24))
        self.feedback_label = ttk.Label(status_bar, textvariable=self.feedback_var, style='Status.TLabel')
        self.feedback_label.pack(anchor='w')

    def build_habit_form(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style='Card.TFrame', padding=20)
        card.grid(row=0, column=0, sticky='nsew')
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text='Kas svarbiausia šiandien?', style='CardHeading.TLabel').grid(
            row=0, column=0, sticky='w')
        ttk.Label(card, text='Pasirinkite kategoriją arba įveskite naują įprotį.',
                  style='CardBody.TLabel').grid(row=1, column=0, sticky='w', pady=(2, 12))

        self.habit_cb = ttk.Combobox(card, textvariable=self.category_var,
                                     values=self.categories, font=('Segoe UI', 11))
        self.habit_cb.grid(row=2, column=0, sticky='ew', pady=(0, 10))

        ttk.Label(card, text='Trumpas aprašas', style='CardBody.TLabel').grid(
            row=3, column=0, sticky='w')
        ttk.Entry(card, textvariable=self.desc_var, font=('Segoe UI', 11)).grid(
            row=4, column=0, sticky='ew', pady=(0, 16))

        buttons = ttk.Frame(card, style='Card.TFrame')
        buttons.grid(row=5, column=0, sticky='ew')
        ttk.Button(buttons, text='Išsaugoti įprotį', style='Primary.TButton',
                   command=self.save_habit).pack(side='left', expand=True, fill='x')
        ttk.Button(buttons, text='Pašalinti', style='Danger.TButton',
                   command=self.delete_habit).pack(side='left', expand=True, fill='x', padx=(8, 0))

    def build_log_form(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style='Card.TFrame', padding=20)
        card.grid(row=1, column=0, sticky='nsew', pady=(16, 0))
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text='Žurnalo įrašai', style='CardHeading.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(card, text='Pagaukite pažangą, kai tik ji įvyksta.', style='CardBody.TLabel').grid(
            row=1, column=0, sticky='w', pady=(2, 12))

        ttk.Label(card, text='Statusas', style='CardBody.TLabel').grid(row=2, column=0, sticky='w')
        self.status_cb = ttk.Combobox(card, textvariable=self.status_field, state='readonly',
                                      values=['padaryta', 'nepadaryta'], font=('Segoe UI', 11))
        self.status_cb.grid(row=3, column=0, sticky='ew', pady=(0, 10))

        ttk.Label(card, text='Pastaba', style='CardBody.TLabel').grid(row=4, column=0, sticky='w')
        ttk.Entry(card, textvariable=self.note_var, font=('Segoe UI', 11)).grid(
            row=5, column=0, sticky='ew', pady=(0, 16))

        buttons = ttk.Frame(card, style='Card.TFrame')
        buttons.grid(row=6, column=0, sticky='ew')
        ttk.Button(buttons, text='Fiksuoti pažangą', style='Primary.TButton',
                   command=self.save_log).pack(side='left', expand=True, fill='x')
        ttk.Button(buttons, text='Trinti įrašą', style='Danger.TButton',
                   command=self.delete_log).pack(side='left', expand=True, fill='x', padx=(8, 0))

    def build_habit_table(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style='Card.TFrame', padding=16)
        panel.grid(row=0, column=0, sticky='nsew', pady=(0, 12))
        panel.rowconfigure(1, weight=1)

        header = ttk.Frame(panel, style='Card.TFrame')
        header.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        ttk.Label(header, textvariable=self.habits_title_var, style='CardHeading.TLabel').pack(side='left')
        ttk.Button(header, text='Naujas įrašas', style='Ghost.TButton',
                   command=self.reset_form).pack(side='right')

        self.habit_tree = ttk.Treeview(panel, columns=('category', 'desc', 'created'),
                                       show='headings', style='Modern.Treeview', selectmode='browse')
        self.habit_tree.heading('category', text='Kategorija')
        self.habit_tree.heading('desc', text='Aprašas')
        self.habit_tree.heading('created', text='Sukurta')
        self.habit_tree.column('category', width=160, minwidth=120, stretch=True)
        self.habit_tree.column('desc', width=240, minwidth=180, stretch=True)
        self.habit_tree.column('created', width=100, anchor='center', stretch=False)

        scroll = ttk.Scrollbar(panel, orient='vertical', command=self.habit_tree.yview)
        self.habit_tree.configure(yscrollcommand=scroll.set)
        self.habit_tree.grid(row=1, column=0, sticky='nsew')
        scroll.grid(row=1, column=1, sticky='ns')

        self.habit_tree.bind('<<TreeviewSelect>>', lambda _e: self.on_habit_select())
        self.habit_tree.bind('<Delete>', lambda _e: self.delete_habit())

    def build_log_table(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style='Card.TFrame', padding=16)
        panel.grid(row=1, column=0, sticky='nsew')
        panel.rowconfigure(1, weight=1)

        header = ttk.Frame(panel, style='Card.TFrame')
        header.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        ttk.Label(header, textvariable=self.logs_title_var, style='CardHeading.TLabel').pack(side='left')

        self.log_tree = ttk.Treeview(panel, columns=('date', 'status', 'note'),
                                     show='headings', style='Modern.Treeview', selectmode='browse')
        self.log_tree.heading('date', text='Data')
        self.log_tree.heading('status', text='Būsena')
        self.log_tree.heading('note', text='Pastaba')
        self.log_tree.column('date', width=110, anchor='center', stretch=False)
        self.log_tree.column('status', width=110, anchor='center', stretch=False)
        self.log_tree.column('note', width=260, stretch=True)

        scroll = ttk.Scrollbar(panel, orient='vertical', command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=scroll.set)
        self.log_tree.grid(row=1, column=0, sticky='nsew')
        scroll.grid(row=1, column=1, sticky='ns')

        self.log_tree.tag_configure('done', foreground=self.colors['success'])
        self.log_tree.tag_configure('missed', foreground=self.colors['danger'])
        self.log_tree.bind('<Delete>', lambda _e: self.delete_log())
        self.log_tree.bind('<<TreeviewSelect>>', lambda _e: self.on_log_select())

    def reset_form(self) -> None:
        self.active_habit_id = None
        self.category_var.set('')
        self.desc_var.set('')
        self.note_var.set('')
        self.habit_tree.selection_remove(self.habit_tree.selection())
        self.log_tree.delete(*self.log_tree.get_children())
        self.logs_title_var.set('Žurnalas (0)')

    def get_active_habit(self) -> Optional[Habit]:
        if self.active_habit_id is None:
            return None
        return self.session.get(Habit, self.active_habit_id)

    def load_habits(self) -> None:
        habits = self.session.query(Habit).order_by(Habit.created_at.desc()).all()
        self.habit_tree.delete(*self.habit_tree.get_children())
        categories = set(self.categories)

        for habit in habits:
            categories.add(habit.category)
            self.habit_tree.insert(
                '',
                'end',
                iid=str(habit.id),
                values=(habit.category, habit.desc or 'Be aprašymo', habit.created_at.strftime('%Y-%m-%d')),
            )

        self.habit_cb['values'] = sorted(categories)
        self.habits_title_var.set(f'Įpročiai ({len(habits)})')

        if self.active_habit_id and str(self.active_habit_id) in self.habit_tree.get_children():
            self.habit_tree.selection_set(str(self.active_habit_id))
            self.habit_tree.see(str(self.active_habit_id))
        else:
            self.active_habit_id = None
            self.logs_title_var.set('Žurnalas (0)')

    def on_habit_select(self) -> None:
        selection = self.habit_tree.selection()
        if not selection:
            self.reset_form()
            return

        habit_id = int(selection[0])
        habit = self.session.get(Habit, habit_id)
        if not habit:
            self.reset_form()
            return

        self.active_habit_id = habit.id
        self.category_var.set(habit.category)
        self.desc_var.set(habit.desc)
        self.load_logs(habit)

    def load_logs(self, habit: Optional[Habit] = None) -> None:
        habit = habit or self.get_active_habit()
        self.log_tree.delete(*self.log_tree.get_children())

        if not habit:
            self.logs_title_var.set('Žurnalas (0)')
            return

        logs = sorted(habit.logs, key=lambda lg: lg.date, reverse=True)
        for log in logs:
            tag = 'done' if log.status == 'padaryta' else 'missed'
            self.log_tree.insert(
                '',
                'end',
                iid=str(log.id),
                values=(
                    log.date.strftime('%Y-%m-%d'),
                    log.status.capitalize(),
                    log.note or 'Be pastabos',
                ),
                tags=(tag,),
            )
        self.logs_title_var.set(f'Žurnalas ({len(logs)})')

    def on_log_select(self) -> None:
        selection = self.log_tree.selection()
        if not selection:
            return
        log_id = int(selection[0])
        log = self.session.get(Log, log_id)
        if log:
            self.status_field.set(log.status)
            self.note_var.set(log.note)

    def save_habit(self) -> None:
        category = self.category_var.get().strip()
        if not category:
            messagebox.showerror('Klaida', 'Įveskite įpročio kategoriją.')
            return
        desc = self.desc_var.get().strip()

        habit = self.get_active_habit()
        if habit:
            habit.category = category
            habit.desc = desc
        else:
            habit = self.session.query(Habit).filter_by(category=category).first()
            if habit:
                habit.desc = desc
            else:
                habit = Habit(category=category, desc=desc)
                self.session.add(habit)

        self.session.commit()
        self.active_habit_id = habit.id
        self.load_habits()
        self.load_logs(habit)
        self.show_status('Įprotis išsaugotas.', 'success')

    def delete_habit(self) -> None:
        habit = self.get_active_habit()
        if not habit:
            messagebox.showinfo('Info', 'Nėra pasirinkto įpročio.')
            return
        if not messagebox.askyesno('Patvirtinimas', f'Ištrinti „{habit.category}“ ir visus įrašus?'):
            return
        self.session.delete(habit)
        self.session.commit()
        self.reset_form()
        self.load_habits()
        self.show_status('Įprotis pašalintas.', 'danger')

    def save_log(self) -> None:
        habit = self.get_active_habit()
        if not habit:
            messagebox.showerror('Klaida', 'Pirma pasirinkite įprotį.')
            return
        status = self.status_field.get().strip() or 'padaryta'
        note = self.note_var.get().strip()

        log = Log(habit=habit, status=status, note=note)
        self.session.add(log)
        self.session.commit()
        self.note_var.set('')
        self.load_logs(habit)
        self.show_status('Pažanga užfiksuota.', 'success')

    def delete_log(self) -> None:
        selection = self.log_tree.selection()
        if not selection:
            return
        log_id = int(selection[0])
        log = self.session.get(Log, log_id)
        if not log:
            return
        if not messagebox.askyesno('Patvirtinimas', 'Ar tikrai pašalinti šį įrašą?'):
            return
        habit = log.habit
        self.session.delete(log)
        self.session.commit()
        self.load_logs(habit)
        self.show_status('Įrašas pašalintas.', 'danger')

    def fetch_quote(self) -> None:
        self.quote_var.set('Kraunama citata...')
        try:
            resp = requests.get('https://quotes.toscrape.com/random', timeout=5)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            text = soup.find('span', class_='text').get_text(strip=True)
            author = soup.find('small', class_='author').get_text(strip=True)
            self.quote_var.set(f'{text} — {author}')
            self.show_status('Nauja citata paruošta.', 'info')
        except Exception:
            self.quote_var.set('Nepavyko gauti citatos. Bandykite vėliau.')
            self.show_status('Citata nepasiekiama.', 'danger')

    def show_status(self, message: str, level: str = 'info') -> None:
        palette = {
            'info': self.colors['accent'],
            'success': self.colors['success'],
            'danger': self.colors['danger'],
        }
        color = palette.get(level, self.colors['muted'])
        self.feedback_var.set(message)
        if self.status_after:
            self.after_cancel(self.status_after)
        self.feedback_label.configure(foreground=color)

        def clear_status() -> None:
            self.feedback_var.set('')
            self.feedback_label.configure(foreground=self.colors['muted'])
            self.status_after = None

        self.status_after = self.after(4500, clear_status)


if __name__ == '__main__':
    App().mainloop()
