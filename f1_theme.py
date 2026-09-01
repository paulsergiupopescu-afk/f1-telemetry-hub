"""Shared high-resolution visual system for the redesigned desktop app."""

import tkinter as tk
from tkinter import ttk


BG = "#150407"
BG_DEEP = "#090204"
SIDEBAR = "#5c2b30"
SIDEBAR_DARK = "#310a0f"
PANEL = "#49090f"
PANEL_2 = "#710b14"
PANEL_SOFT = "#98232c"
CARD = "#401016"
CARD_ALT = "#26090d"
EDGE = "#84252e"
TEXT = "#fff7fb"
MUTED = "#d7a9bf"
PINK = "#ff3b52"
HOT = "#e10600"
GOLD = "#ffad18"
GREEN = "#4ce68a"
CYAN = "#53d9ff"
RED = "#ff4f68"
PURPLE = "#c48cff"
YELLOW = "#ffd45d"


def apply_ttk(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("F1.Treeview", background=CARD_ALT, fieldbackground=CARD_ALT,
                    foreground=TEXT, rowheight=30, borderwidth=0,
                    font=("Segoe UI", 10))
    style.configure("F1.Treeview.Heading", background=PANEL_2, foreground=MUTED,
                    relief="flat", font=("Segoe UI", 9, "bold"))
    style.map("F1.Treeview", background=[("selected", PANEL_SOFT)],
              foreground=[("selected", TEXT)])
    style.configure("F1.TCombobox", fieldbackground=CARD_ALT, background=PANEL_2,
                    foreground=TEXT, arrowcolor=GOLD, bordercolor=EDGE,
                    lightcolor=EDGE, darkcolor=EDGE)
    style.map("F1.TCombobox", fieldbackground=[("readonly", CARD_ALT)],
              foreground=[("readonly", TEXT)])
    style.configure("F1.TNotebook", background=BG, borderwidth=0)
    style.configure("F1.TNotebook.Tab", background=PANEL, foreground=MUTED,
                    padding=(20, 10), font=("Segoe UI", 10, "bold"))
    style.map("F1.TNotebook.Tab", background=[("selected", PANEL_2)],
              foreground=[("selected", TEXT)])
    return style


def rounded_rectangle(canvas, x1, y1, x2, y2, radius=18, **kwargs):
    radius = max(2, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
              x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
              x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


def button(parent, text, command, accent=PINK, dark=False, **kwargs):
    bg = CARD_ALT if dark else accent
    fg = TEXT if dark else BG_DEEP
    return tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                     activebackground=GOLD, activeforeground=BG_DEEP,
                     relief="flat", bd=0, cursor="hand2", padx=16, pady=8,
                     font=("Segoe UI", 10, "bold"), **kwargs)


def section_label(parent, text):
    return tk.Label(parent, text=text.upper(), bg=parent.cget("bg"), fg=MUTED,
                    font=("Segoe UI", 9, "bold"), anchor="w")


def card(parent, bg=CARD, edge=EDGE, **kwargs):
    return tk.Frame(parent, bg=bg, highlightbackground=edge,
                    highlightthickness=1, bd=0, **kwargs)
