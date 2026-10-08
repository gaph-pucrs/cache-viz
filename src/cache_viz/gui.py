"""Desktop viewer: cache timeline and statistics in one tkinter window."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from .analysis import CacheAnalysis
from .models import EventKind
from .report import ReportParams, short_names
from .stats import CacheStats, cards, comparison, cycles, describe, fmt_int, insights, pct, quantile

P = dict(
    side="#0f0f0e", bg="#151514", surface="#1b1b1a", raised="#262624", hover="#30302d", alt="#202020",
    grid="#2c2c2a", border="#363632", fg="#f2f1ec", fg2="#c3c2b7", muted="#898781", accent="#3987e5", sel="#1d3a5c",
    clean="#3987e5", dirty="#d95926", evict="#199e70", cold="#8c8a83", conf="#e0a91f", ok="#3fb950", bad="#e66767",
)
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9", "#e66767", "#8c8a83"]


def blend(fg: str, bg: str, a: float) -> str:
    """``fg`` over ``bg`` with opacity ``a`` (the Tk canvas has no alpha)."""
    f, b = ([int(c[i : i + 2], 16) for i in (1, 3, 5)] for c in (fg, bg))
    return "#%02x%02x%02x" % tuple(round(a * x + (1 - a) * y) for x, y in zip(f, b))


def nice_max(v: float) -> float:
    if v <= 0:
        return 1
    p = 10 ** math.floor(math.log10(v))
    return next(k for k in (1, 2, 5, 10) if v / p <= k) * p


def apply_theme(root: tk.Tk) -> dict:
    """Flat dark ttk theme on top of ``clam``; returns the fonts."""
    fams = set(tkfont.families(root))

    def pick(names, fallback):
        return next((n for n in names if n in fams), tkfont.nametofont(fallback).actual("family"))

    sans = pick(("Inter", "Noto Sans", "Cantarell", "DejaVu Sans"), "TkDefaultFont")
    mono = pick(("JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono"), "TkFixedFont")
    for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont"):
        tkfont.nametofont(name).configure(family=sans, size=10)
    F = dict(ui=(sans, 10), small=(sans, 9), bold=(sans, 10, "bold"), head=(sans, 8, "bold"), title=(sans, 16, "bold"),
             card=(sans, 18, "bold"), brand=(sans, 13, "bold"), mono=(mono, 9), tiny=(mono, 8))
    row_h = tkfont.Font(root, font=F["mono"]).metrics("linespace") + 10

    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=P["bg"], foreground=P["fg"], fieldbackground=P["surface"], bordercolor=P["border"],
                lightcolor=P["bg"], darkcolor=P["bg"], troughcolor=P["surface"], focuscolor=P["bg"],
                selectbackground=P["sel"], selectforeground=P["fg"], insertcolor=P["fg"], font=F["ui"])
    for name, bg, fg, font in (
        ("Side", P["side"], P["muted"], F["head"]), ("SideText", P["side"], P["fg2"], F["small"]),
        ("Brand", P["side"], P["fg"], F["brand"]), ("Title", P["bg"], P["fg"], F["title"]), ("Sub", P["bg"], P["muted"], F["ui"]),
        ("Ok", P["bg"], P["ok"], F["bold"]), ("Bad", P["bg"], P["bad"], F["bold"]),
        ("CardValue", P["surface"], P["fg"], F["card"]), ("CardName", P["surface"], P["fg2"], F["ui"]),
        ("CardHint", P["surface"], P["muted"], F["small"]), ("Panel", P["surface"], P["muted"], F["small"]),
        ("PanelHead", P["surface"], P["muted"], F["head"]),
    ):
        s.configure(f"{name}.TLabel", background=bg, foreground=fg, font=font)
    s.configure("Status.TLabel", background=P["side"], foreground=P["muted"], font=F["small"], padding=(14, 5))
    for name, bg in (("Side", P["side"]), ("Card", P["surface"]), ("Panel", P["surface"])):
        s.configure(f"{name}.TFrame", background=bg)

    # nav list and segmented toggle: radiobuttons drawn as flat buttons, no indicator
    for name in ("Nav", "Seg"):
        s.layout(f"{name}.TRadiobutton", [("Radiobutton.fill", {"sticky": "nswe", "children": [
            ("Radiobutton.padding", {"sticky": "nswe", "children": [("Radiobutton.label", {"sticky": "w"})]})]})])
    s.configure("Nav.TRadiobutton", background=P["side"], foreground=P["fg2"], padding=(18, 8))
    s.map("Nav.TRadiobutton", background=[("selected", P["raised"]), ("active", P["alt"])], foreground=[("selected", P["fg"])])
    s.configure("Seg.TRadiobutton", background=P["bg"], foreground=P["muted"], padding=(12, 4))
    s.map("Seg.TRadiobutton", background=[("selected", P["raised"]), ("active", P["alt"])], foreground=[("selected", P["fg"])])

    s.configure("TButton", background=P["raised"], foreground=P["fg"], bordercolor=P["border"], lightcolor=P["raised"],
                darkcolor=P["raised"], focuscolor=P["raised"], padding=(12, 4))
    s.map("TButton", background=[("pressed", P["grid"]), ("active", P["hover"])], lightcolor=[("active", P["hover"])],
          darkcolor=[("active", P["hover"])], focuscolor=[("active", P["hover"])])
    s.configure("TEntry", fieldbackground=P["surface"], foreground=P["fg"], bordercolor=P["border"], lightcolor=P["surface"],
                darkcolor=P["surface"], padding=(8, 5))
    s.map("TEntry", bordercolor=[("focus", P["accent"])], lightcolor=[("focus", P["accent"])])

    s.configure("TNotebook", background=P["bg"], bordercolor=P["bg"], lightcolor=P["bg"], darkcolor=P["bg"], tabmargins=0)
    s.layout("TNotebook.Tab", [("Notebook.tab", {"sticky": "nswe", "children": [
        ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [("Notebook.label", {"side": "top", "sticky": ""})]})]})])
    s.configure("TNotebook.Tab", background=P["bg"], foreground=P["muted"], bordercolor=P["bg"], lightcolor=P["bg"],
                darkcolor=P["bg"], padding=(18, 7), font=F["bold"])
    s.map("TNotebook.Tab", background=[("selected", P["surface"])], foreground=[("selected", P["fg"]), ("active", P["fg2"])],
          lightcolor=[("selected", P["surface"])], darkcolor=[("selected", P["surface"])],
          bordercolor=[("selected", P["surface"])], expand=[("selected", 0)])
    s.configure("TPanedwindow", background=P["bg"])
    s.configure("Sash", sashthickness=6, gripcount=0, background=P["bg"], lightcolor=P["bg"], darkcolor=P["bg"], bordercolor=P["bg"])

    s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    s.configure("Treeview", background=P["surface"], fieldbackground=P["surface"], foreground=P["fg2"], rowheight=row_h, font=F["mono"])
    s.map("Treeview", background=[("selected", P["sel"])], foreground=[("selected", P["fg"])])
    s.configure("Treeview.Heading", background=P["raised"], foreground=P["fg"], bordercolor=P["raised"], lightcolor=P["raised"],
                darkcolor=P["raised"], padding=(6, 6), font=F["small"])
    s.map("Treeview.Heading", background=[("active", P["hover"])], lightcolor=[("active", P["hover"])], darkcolor=[("active", P["hover"])])
    s.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
        ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    s.configure("Vertical.TScrollbar", background=P["raised"], troughcolor=P["surface"], bordercolor=P["surface"],
                lightcolor=P["raised"], darkcolor=P["raised"], gripcount=0, arrowsize=10)
    s.map("Vertical.TScrollbar", background=[("active", P["hover"])])
    return F


# per-line table: key, heading, width, value(line stats, range stats), text
LINE_COLS = (
    ("line", "line", 60, lambda L, R: L.line, str),
    ("fills", "fills", 70, lambda L, R: L.fills, str),
    ("cold", "compulsory", 95, lambda L, R: L.cold, str),
    ("conf", "re-fills", 80, lambda L, R: L.conf, str),
    ("pp", "ping-pongs", 95, lambda L, R: L.pingpong, str),
    ("evicts", "write-backs", 100, lambda L, R: L.evicts, str),
    ("repl", "clean repl.", 95, lambda L, R: L.clean_repl, str),
    ("dirty", "DIRTY", 70, lambda L, R: L.dirty, str),
    ("blocks", "blocks", 70, lambda L, R: len(set(L.tags)), str),
    ("occ", "occupancy", 90, lambda L, R: L.valid_time / R.span, pct),
    ("life", "median life", 110, lambda L, R: quantile(L.lifetimes, 0.5), fmt_int),
    ("seq", "    tags brought in", 360, lambda L, R: " ".join(L.tags), lambda s: "    " + s[:400]),
)

HINT = "wheel: zoom · drag: pan · click a row: pin the line · double-click / Esc: fit"


class Viewer:
    def __init__(self, root: tk.Tk, caches: list[CacheStats], params: ReportParams):
        self.root, self.caches, self.params = root, caches, params
        self.F = apply_theme(root)
        self.c = caches[0]
        self.u0, self.u1 = 0.0, 1.0  # visible part of the time axis (0..1)
        self.axis = tk.StringVar(value="event")
        self.sel_line: int | None = None  # line pinned in the timeline
        self.R = None  # stats of the visible range
        self.geom = None
        self.sort = ("line", False)
        self.hot_rows: list[int] = []
        self._drag = None
        self._jobs: dict[str, str] = {}

        root.title("cache-viz")
        root.geometry("1500x920")
        root.minsize(1100, 680)
        root.configure(bg=P["bg"])
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        self._sidebar().grid(row=0, column=0, sticky="ns")
        self._main().grid(row=0, column=1, sticky="nsew")
        self.status = ttk.Label(root, style="Status.TLabel", text=HINT)
        self.status.grid(row=1, column=0, columnspan=2, sticky="ew")
        root.bind("<Escape>", lambda e: self.fit())
        self.fill_compare()
        self.select(0)

    @property
    def linear(self) -> bool:
        return self.axis.get() == "time"

    def _later(self, key: str, ms: int, fn) -> None:
        """Run ``fn`` once after ``ms`` of quiet (debounce)."""
        if key in self._jobs:
            self.root.after_cancel(self._jobs[key])
        self._jobs[key] = self.root.after(ms, lambda: (self._jobs.pop(key, None), fn()))

    # ---------------------------------------------------------------- layout
    def _sidebar(self) -> ttk.Frame:
        side = ttk.Frame(self.root, style="Side.TFrame", padding=(0, 18, 0, 18), width=240)
        ttk.Label(side, text="▦  cache-viz", style="Brand.TLabel").pack(anchor="w", padx=18, pady=(0, 22))
        ttk.Label(side, text="CACHES", style="Side.TLabel").pack(anchor="w", padx=18, pady=(0, 6))
        self.cache_var = tk.IntVar(value=0)
        for i, c in enumerate(self.caches):
            ttk.Radiobutton(side, text=c.name, value=i, variable=self.cache_var, style="Nav.TRadiobutton",
                            command=lambda: self.select(self.cache_var.get())).pack(fill="x")
        ttk.Label(side, text="PARAMETERS", style="Side.TLabel").pack(anchor="w", padx=18, pady=(28, 2))
        self.param_vars = {}
        for key, label in (("period", "clock period (t.u. per cycle)"), ("block_bytes", "block size (bytes)"),
                           ("miss_penalty", "miss penalty (cycles)"), ("wb_penalty", "write-back penalty (cycles)")):
            ttk.Label(side, text=label, style="SideText.TLabel").pack(anchor="w", padx=18, pady=(10, 3))
            value = getattr(self.params, key)
            var = tk.StringVar(value=f"{value:g}" if value else "")
            ttk.Entry(side, textvariable=var, width=24).pack(fill="x", padx=18)
            var.trace_add("write", lambda *_: self._later("params", 350, self.apply_params))
            self.param_vars[key] = var
        return side

    def _main(self) -> ttk.Frame:
        m = ttk.Frame(self.root, padding=(22, 16, 22, 14))
        m.columnconfigure(0, weight=1)
        m.rowconfigure(2, weight=1)
        head = ttk.Frame(m)
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        self.title = ttk.Label(head, style="Title.TLabel")
        self.title.grid(row=0, column=0, sticky="w")
        self.badge = ttk.Label(head)
        self.badge.grid(row=0, column=1, sticky="e")
        self.subtitle = ttk.Label(head, style="Sub.TLabel")
        self.subtitle.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        row = ttk.Frame(m)
        row.grid(row=1, column=0, sticky="ew", pady=14)
        self.cards = []
        for i in range(6):
            row.columnconfigure(i, weight=1, uniform="card")
            f = ttk.Frame(row, style="Card.TFrame", padding=(14, 10, 14, 12))
            f.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            labels = [ttk.Label(f, style=f"Card{k}.TLabel") for k in ("Value", "Name", "Hint")]
            for lab in labels:
                lab.pack(anchor="w")
            self.cards.append(labels)

        self.nb = ttk.Notebook(m)
        self.nb.grid(row=2, column=0, sticky="nsew")
        self.nb.add(self._timeline_tab(self.nb), text="Timeline")
        self.nb.add(self._lines_tab(self.nb), text="Per line")
        self.nb.add(self._compare_tab(self.nb), text="Compare caches")
        return m

    def _timeline_tab(self, nb) -> ttk.PanedWindow:
        pw = ttk.PanedWindow(nb, orient="horizontal")
        left = ttk.Frame(pw, style="Panel.TFrame", padding=(12, 10, 12, 8))
        bar = ttk.Frame(left, style="Panel.TFrame")
        bar.pack(fill="x", pady=(0, 6))
        for text, value in (("per event", "event"), ("real time", "time")):
            ttk.Radiobutton(bar, text=text, value=value, variable=self.axis, style="Seg.TRadiobutton",
                            command=self.fit).pack(side="left")
        ttk.Button(bar, text="Fit", command=self.fit, width=4).pack(side="left", padx=(8, 0))
        self.range_lbl = ttk.Label(bar, style="Panel.TLabel")
        self.range_lbl.pack(side="left", padx=12)
        for mark, color, text in reversed((("■", P["clean"], "clean"), ("■", P["dirty"], "dirty"), ("▌", P["conf"], "re-fill"),
                                           ("▌", P["cold"], "compulsory"), ("▶", P["evict"], "write-back"))):
            ttk.Label(bar, text=text, style="Panel.TLabel").pack(side="right", padx=(3, 10))
            ttk.Label(bar, text=mark, foreground=color, background=P["surface"]).pack(side="right")

        self.tl = cv = tk.Canvas(left, bg=P["surface"], highlightthickness=0, cursor="crosshair")
        cv.pack(fill="both", expand=True)
        cv.bind("<Configure>", lambda e: self._later("tl", 20, self.draw_timeline))
        cv.bind("<Motion>", self.on_hover)
        cv.bind("<Leave>", lambda e: cv.delete("hover"))
        cv.bind("<ButtonPress-1>", self.on_press)
        cv.bind("<B1-Motion>", self.on_drag)
        cv.bind("<ButtonRelease-1>", self.on_release)
        cv.bind("<Double-Button-1>", lambda e: self.fit())
        cv.bind("<MouseWheel>", lambda e: self.zoom(0.8 if e.delta > 0 else 1.25, e.x))
        cv.bind("<Button-4>", lambda e: self.zoom(0.8, e.x))
        cv.bind("<Button-5>", lambda e: self.zoom(1.25, e.x))

        right = ttk.Frame(pw, style="Panel.TFrame", padding=(16, 12, 16, 10))
        ttk.Label(right, text="FINDINGS IN THIS RANGE", style="PanelHead.TLabel").pack(anchor="w")
        self.ins = tk.Text(right, wrap="word", height=12, width=44, bg=P["surface"], fg=P["fg2"], bd=0, highlightthickness=0,
                           font=self.F["ui"], spacing1=2, spacing3=7, cursor="arrow", padx=0)
        self.ins.tag_configure("item", lmargin1=0, lmargin2=16)
        self.ins.tag_configure("dot", foreground=P["accent"])
        self.ins.tag_configure("bad", foreground=P["bad"])
        self.ins.pack(fill="both", expand=True, pady=(8, 12))
        ttk.Label(right, text="HOTTEST LINES  ·  click to pin", style="PanelHead.TLabel").pack(anchor="w")
        self.hot = tk.Canvas(right, bg=P["surface"], highlightthickness=0, height=10 * 24, cursor="hand2")
        self.hot.pack(fill="x", pady=(8, 0))
        self.hot.bind("<Configure>", lambda e: self.draw_hot())
        self.hot.bind("<Button-1>", self.on_hot_click)
        pw.add(left, weight=3)
        pw.add(right, weight=1)
        return pw

    def _lines_tab(self, nb) -> ttk.Frame:
        tab = ttk.Frame(nb, style="Panel.TFrame", padding=12)
        self.lines_tv = tv = ttk.Treeview(tab, columns=[c[0] for c in LINE_COLS], show="headings", selectmode="browse")
        for key, head, width, *_ in LINE_COLS:
            tv.heading(key, text=head, anchor="w" if key == "seq" else "e", command=lambda k=key: self.sort_lines(k))
            tv.column(key, width=width, anchor="w" if key == "seq" else "e", stretch=key == "seq")
        tv.tag_configure("odd", background=P["alt"])
        tv.tag_configure("dim", foreground=P["muted"])
        tv.bind("<Double-1>", self.on_line_open)
        sb = ttk.Scrollbar(tab, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tv.pack(fill="both", expand=True)
        ttk.Label(tab, text="Stats follow the timeline's zoom. Click a heading to sort, double-click a row to show the line in the timeline.",
                  style="Panel.TLabel").pack(anchor="w", pady=(8, 0))
        return tab

    def _compare_tab(self, nb) -> ttk.Frame:
        tab = ttk.Frame(nb, style="Panel.TFrame", padding=12)
        cols = ["metric"] + [f"c{i}" for i in range(len(self.caches))]
        self.cmp_tv = tv = ttk.Treeview(tab, columns=cols, show="headings", height=18, selectmode="none")
        tv.heading("metric", text="metric (full run)", anchor="w")
        tv.column("metric", width=200, anchor="w", stretch=False)
        for i, c in enumerate(self.caches):
            tv.heading(f"c{i}", text=c.name, anchor="e")
            tv.column(f"c{i}", width=150, anchor="e", stretch=False)
        tv.tag_configure("odd", background=P["alt"])
        tv.pack(side="left", fill="y")
        self.cmp_cv = tk.Canvas(tab, bg=P["surface"], highlightthickness=0)
        self.cmp_cv.pack(side="left", fill="both", expand=True, padx=(20, 0))
        self.cmp_cv.bind("<Configure>", lambda e: self.draw_compare())
        return tab

    # ---------------------------------------------------------------- state
    def select(self, i: int) -> None:
        self.c, self.u0, self.u1, self.sel_line = self.caches[i], 0.0, 1.0, None
        c, log = self.c, self.caches[i].analysis.log
        last = c.events[-1].event.time if c.events else 0
        self.title.configure(text=c.name)
        self.subtitle.configure(text=f"{log.path.name}  ·  {c.nlines} lines{' (inferred)' if log.nlines_inferred else ''}  ·  "
                                     f"{len(c.events):,} events  ·  t ∈ [{fmt_int(c.t_min)}, {fmt_int(last)}]")
        n = len(c.analysis.replay.anomalies)
        self.badge.configure(text=f"✗  {n} anomalies" if n else "✓  consistent event sequence", style="Bad.TLabel" if n else "Ok.TLabel")
        self.draw_timeline()
        self.refresh_stats()

    def fit(self) -> None:
        self.u0, self.u1 = 0.0, 1.0
        self.draw_timeline()
        self.refresh_stats()

    def apply_params(self) -> None:
        vals = {}
        for key, var in self.param_vars.items():
            try:
                vals[key] = max(0.0, float(var.get() or 0))
            except ValueError:
                return  # half-typed value: keep the last valid parameters
        vals["block_bytes"] = int(vals["block_bytes"])
        self.params = ReportParams(**vals)
        self.refresh_stats()
        self.fill_compare()

    def select_line(self, line: int | None) -> None:
        self.sel_line = None if line == self.sel_line else line
        self.draw_timeline()
        self.draw_hot()

    def refresh_stats(self) -> None:
        c = self.c
        zoomed = self.u0 > 0 or self.u1 < 1
        a, b = (c.t(self.u0, self.linear), c.t(self.u1, self.linear)) if zoomed else (c.t_min, c.t_end)
        self.R = R = c.window(a, b) if zoomed else c.full
        self.range_lbl.configure(text=f"{'zoomed' if zoomed else 'full run'}  ·  [{fmt_int(a)}, {fmt_int(b)}]"
                                      f"  ·  {fmt_int(b - a)} t.u.{cycles(b - a, self.params)}")
        for labels, values in zip(self.cards, cards(c, R, self.params)):
            for lab, v in zip(labels, values):
                lab.configure(text=v)
        t = self.ins
        t.configure(state="normal")
        t.delete("1.0", "end")
        anomalies = c.analysis.replay.anomalies
        for msg in anomalies[:20] + ([f"… {len(anomalies) - 20} more"] if len(anomalies) > 20 else []):
            t.insert("end", "✗  ", ("bad", "item"))
            t.insert("end", msg + "\n", ("bad", "item"))
        for msg in insights(c, R, self.params):
            t.insert("end", "●  ", ("dot", "item"))
            t.insert("end", msg + "\n", "item")
        t.configure(state="disabled")
        self.draw_hot()
        self.fill_lines()

    # ---------------------------------------------------------------- timeline
    def _x(self, t: float) -> float:
        L, _, _, length = self.geom
        return L + (self.c.u(t, self.linear) - self.u0) / (self.u1 - self.u0) * length

    def _t(self, px: float) -> float:
        L, _, _, length = self.geom
        return self.c.t(self.u0 + (px - L) / length * (self.u1 - self.u0), self.linear)

    def draw_timeline(self) -> None:
        # ponytail: redraws every visible item on each pan/zoom; merge sub-pixel segments if logs reach ~100k events
        cv, c, F = self.tl, self.c, self.F
        cv.delete("all")
        W, H = cv.winfo_width(), cv.winfo_height()
        L, miss_y, miss_h, occ_y, occ_h = 56, 22, 34, 62, 22
        top = occ_y + occ_h + 10
        length, rh = W - L - 14, (H - top - 4) / c.nlines
        if length < 50 or rh <= 0:
            return
        self.geom = (L, top, rh, length)
        x_end, span, linear = L + length, self.u1 - self.u0, self.linear
        X = self._x

        # rows and time grid
        step = max(1, math.ceil(13 / rh))
        for line in range(c.nlines):
            y = top + line * rh
            if line % 2 and rh >= 3:
                cv.create_rectangle(L, y, x_end, y + rh, fill=P["alt"], width=0)
            if line % step == 0 or line == self.sel_line:
                cv.create_text(L - 8, y + rh / 2, text=line, anchor="e", font=F["tiny"],
                               fill=P["accent"] if line == self.sel_line else P["muted"])
        nt = max(2, int(length // 140))
        for i in range(nt + 1):
            px = L + length * i / nt
            cv.create_line(px, 16, px, H, fill=P["grid"])
            cv.create_text(px, 2, text=fmt_int(c.t(self.u0 + span * i / nt, linear)), font=F["tiny"], fill=P["muted"],
                           anchor="nw" if i == 0 else "ne" if i == nt else "n")

        # misses strip: FILLs per few pixels, re-fills at the bottom
        nb = max(1, int(length // 4))
        cold, conf = [0] * nb, [0] * nb
        for ae in c.events:
            if ae.event.kind is EventKind.FILL:
                u = (c.u(ae.event.time, linear) - self.u0) / span
                if 0 <= u <= 1:
                    (conf if ae.category == "conf" else cold)[min(nb - 1, int(u * nb))] += 1
        top_count = max(1, max(a + b for a, b in zip(cold, conf)))
        bw = length / nb
        cv.create_rectangle(L, miss_y, x_end, miss_y + miss_h, fill=P["surface"], outline=P["grid"])
        for k in range(nb):
            base = miss_y + miss_h
            for n, color in ((conf[k], P["conf"]), (cold[k], P["cold"])):
                if n:
                    h = n / top_count * (miss_h - 2)
                    cv.create_rectangle(L + k * bw, base - h, L + (k + 1) * bw - (bw > 2), base, fill=color, width=0)
                    base -= h
        cv.create_text(L - 8, miss_y + miss_h / 2 - 6, text="misses", anchor="e", font=F["tiny"], fill=P["muted"])
        cv.create_text(L - 8, miss_y + miss_h / 2 + 6, text=f"≤{top_count}", anchor="e", font=F["tiny"], fill=P["muted"])

        # occupancy strip: valid / dirty lines
        cv.create_rectangle(L, occ_y, x_end, occ_y + occ_h, fill=P["surface"], outline=P["grid"])
        for idx, color in ((1, blend(P["clean"], P["surface"], 0.45)), (2, blend(P["dirty"], P["surface"], 0.8))):
            pts, prev = [L, occ_y + occ_h], occ_y + occ_h
            for o in c.occupancy:
                px, py = min(x_end, max(L, X(o[0]))), occ_y + occ_h - o[idx] / c.nlines * occ_h
                pts += [px, prev, px, py]
                prev = py
            cv.create_polygon(pts + [x_end, prev, x_end, occ_y + occ_h], fill=color, width=0)
        cv.create_text(L - 8, occ_y + occ_h / 2, text="valid", anchor="e", font=F["tiny"], fill=P["muted"])

        # blocks resident in each line
        pad = 1 if rh >= 4 else 0
        for line, segs in enumerate(c.segs_by_line):
            y0, y1 = top + line * rh + pad, top + (line + 1) * rh - pad
            for s in segs:
                x0, x1 = X(s.start), X(s.end)
                if x1 < L or x0 > x_end:
                    continue
                x0, x1 = max(L, x0), min(x_end, x1)
                cv.create_rectangle(x0, y0, max(x1, x0 + 1), y1, fill=P["dirty"] if s.dirty else P["clean"], width=0)
                if rh >= 14 and x1 - x0 > 8 * len(s.tag) + 10:
                    cv.create_text(x0 + 5, (y0 + y1) / 2, text=s.tag, anchor="w", fill="#ffffff", font=F["tiny"])

        # FILL ticks (re-fills highlighted) and write-back arrows
        for ae in c.events:
            e = ae.event
            if e.kind is EventKind.DIRTY:
                continue
            px = X(e.time)
            if px < L - 2 or px > x_end + 2:
                continue
            y = top + e.line * rh
            if e.kind is EventKind.FILL:
                if ae.category == "conf":
                    cv.create_rectangle(px, y, px + 2, y + rh, fill=P["conf"], width=0)
                elif rh >= 4:
                    cv.create_line(px, y + 1, px, y + rh - 1, fill=P["surface"], width=2)
            else:
                s, cy = min(5, rh / 2), y + rh / 2
                cv.create_polygon(px, cy - s, px + s * 1.2, cy, px, cy + s, fill=P["evict"], width=0)

        if self.sel_line is not None:
            y = top + self.sel_line * rh
            cv.create_rectangle(L - 1, y - 1, x_end + 1, y + rh + 1, outline=P["accent"], width=2)

    def on_hover(self, ev) -> None:
        cv, c = self.tl, self.c
        cv.delete("hover")
        if not self.geom or self._drag:
            return
        L, top, rh, length = self.geom
        if not L <= ev.x <= L + length or ev.y < 22 or ev.y >= top + c.nlines * rh:
            return
        t = self._t(ev.x)
        cv.create_line(ev.x, 16, ev.x, top + c.nlines * rh, fill=P["fg2"], dash=(2, 3), tags="hover")
        lines = [f"t = {fmt_int(t)}{cycles(t, self.params)}"]
        if ev.y < top:
            i = max(0, next((k for k, o in enumerate(c.occupancy) if o[0] > t), len(c.occupancy)) - 1)
            _, valid, dirty = c.occupancy[i]
            lines.append(f"{valid}/{c.nlines} lines valid, {dirty} dirty")
        else:
            line = int((ev.y - top) // rh)
            cv.create_rectangle(L, top + line * rh, L + length, top + (line + 1) * rh, outline=P["fg2"], tags="hover")
            seg = c.segment_at(line, t)
            Ls = self.R.lines[line]
            lines[0] = f"line {line}   ·   " + lines[0]
            lines.append(f"tag {seg.tag}, {'dirty' if seg.dirty else 'clean'}, resident since {fmt_int(seg.start)}" if seg else "invalid")
            near = [ae for ae in c.events_around(line, t) if abs(self._x(ae.event.time) - ev.x) <= 6]
            if near:
                ae = min(near, key=lambda ae: abs(self._x(ae.event.time) - ev.x))
                lines += ["", f"{ae.event.kind.value} at {fmt_int(ae.event.time)}{cycles(ae.event.time, self.params)}", describe(ae)]
            lines += ["", f"in range: {Ls.fills} fills ({Ls.conf} re-fills), {Ls.evicts} write-backs, {len(set(Ls.tags))} blocks"]
        self._tip(cv, ev.x, ev.y, lines)

    def _tip(self, cv: tk.Canvas, x: int, y: int, lines: list[str]) -> None:
        W, H = cv.winfo_width(), cv.winfo_height()
        t = cv.create_text(0, 0, text="\n".join(lines), anchor="nw", fill=P["fg"], font=self.F["small"], tags="hover")
        x0, y0, x1, y1 = cv.bbox(t)
        w, h = x1 - x0 + 20, y1 - y0 + 14
        tx = x + 16 if x + 16 + w < W else x - 16 - w
        ty = min(max(4, y + 16), H - h - 4)
        cv.coords(t, tx + 10, ty + 7)
        cv.tag_lower(cv.create_rectangle(tx, ty, tx + w, ty + h, fill=P["raised"], outline=P["border"], tags="hover"), t)

    def on_press(self, ev) -> None:
        self._drag = (ev.x, ev.y, self.u0, self.u1, False)

    def on_drag(self, ev) -> None:
        if not self._drag or not self.geom:
            return
        x0, y0, u0, u1, _ = self._drag
        if abs(ev.x - x0) < 3 and not self._drag[4]:
            return
        self._drag = (x0, y0, u0, u1, True)
        self.tl.configure(cursor="fleur")
        d = -(ev.x - x0) / self.geom[3] * (u1 - u0)
        d = max(-u0, min(1 - u1, d))
        self.u0, self.u1 = u0 + d, u1 + d
        self.draw_timeline()
        self._later("stats", 150, self.refresh_stats)

    def on_release(self, ev) -> None:
        drag, self._drag = self._drag, None
        self.tl.configure(cursor="crosshair")
        if drag and not drag[4] and self.geom:  # a click, not a drag: pin the line under the cursor
            L, top, rh, length = self.geom
            if L <= ev.x <= L + length and top <= ev.y < top + self.c.nlines * rh:
                self.select_line(int((ev.y - top) // rh))

    def zoom(self, factor: float, px: float) -> None:
        if not self.geom:
            return
        L, _, _, length = self.geom
        f = min(1.0, max(0.0, (px - L) / length))
        span = self.u1 - self.u0
        at, new = self.u0 + f * span, min(1.0, max(1e-6, span * factor))
        self.u0 = min(1 - new, max(0.0, at - f * new))
        self.u1 = self.u0 + new
        self.draw_timeline()
        self._later("stats", 150, self.refresh_stats)

    # ---------------------------------------------------------------- side panels
    def draw_hot(self) -> None:
        cv, R, F = self.hot, self.R, self.F
        cv.delete("all")
        if not R:
            return
        W, rh, lx = cv.winfo_width(), 24, 40
        top = sorted((L for L in R.lines if L.fills), key=lambda L: (-L.conf, -L.fills, L.line))[:10]
        self.hot_rows = [L.line for L in top]
        if not top:
            cv.create_text(0, 10, text="no misses in this range", anchor="w", fill=P["muted"], font=F["small"])
            return
        pair = {}
        for (line, a, b), n in R.pairs.most_common():
            pair.setdefault(line, f"{a} ↔ {b}  ×{n}")
        mx, bar_w = max(L.fills for L in top), max(40, W - lx - 190)
        for i, L in enumerate(top):
            y = i * rh
            if L.line == self.sel_line:
                cv.create_rectangle(0, y, W, y + rh, fill=P["raised"], width=0)
            cv.create_text(lx - 10, y + rh / 2, text=L.line, anchor="e", font=F["mono"],
                           fill=P["accent"] if L.line == self.sel_line else P["fg2"])
            x = lx
            for n, color in ((L.conf, P["conf"]), (L.cold, P["cold"])):
                w = n / mx * bar_w
                if w:
                    cv.create_rectangle(x, y + 6, x + w, y + rh - 6, fill=color, width=0)
                x += w
            cv.create_text(x + 6, y + rh / 2, text=f"{L.conf}/{L.fills}", anchor="w", font=F["tiny"], fill=P["fg2"])
            cv.create_text(W - 2, y + rh / 2, text=pair.get(L.line, ""), anchor="e", font=F["tiny"], fill=P["muted"])

    def on_hot_click(self, ev) -> None:
        i = ev.y // 24
        if i < len(self.hot_rows):
            self.select_line(self.hot_rows[i])

    def fill_lines(self) -> None:
        tv, R = self.lines_tv, self.R
        key, desc = self.sort
        col = next(c for c in LINE_COLS if c[0] == key)

        def sort_key(L):
            v = col[3](L, R)
            return len(v) if isinstance(v, str) else -1 if v != v else v  # v != v: NaN

        tv.delete(*tv.get_children())
        for i, L in enumerate(sorted(R.lines, key=sort_key, reverse=desc)):
            tags = (("odd",) if i % 2 else ()) + (() if L.used else ("dim",))
            tv.insert("", "end", iid=str(L.line), values=[c[4](c[3](L, R)) for c in LINE_COLS], tags=tags)
        for k, head, *_ in LINE_COLS:
            tv.heading(k, text=head + ((" ▾" if desc else " ▴") if k == key else ""))

    def sort_lines(self, key: str) -> None:
        self.sort = (key, not self.sort[1] if key == self.sort[0] else key != "line")
        self.fill_lines()

    def on_line_open(self, ev) -> None:
        row = self.lines_tv.identify_row(ev.y)
        if row:
            self.sel_line = None
            self.select_line(int(row))
            self.nb.select(0)

    def fill_compare(self) -> None:
        tv = self.cmp_tv
        tv.delete(*tv.get_children())
        for i, (label, values) in enumerate(comparison(self.caches, self.params)):
            tv.insert("", "end", values=[label, *values], tags=("odd",) if i % 2 else ())

    def draw_compare(self) -> None:
        cv, F = self.cmp_cv, self.F
        cv.delete("all")
        W, H = cv.winfo_width(), cv.winfo_height()
        L, T, B, Rm = 52, 34, 24, 170
        if W - L - Rm < 50 or H - T - B < 50:
            return
        cv.create_text(0, 4, text="CUMULATIVE MISSES (FILLs)", anchor="nw", fill=P["muted"], font=F["head"])
        a, b = min(c.t_min for c in self.caches), max(c.t_end for c in self.caches)
        ymax = nice_max(max(c.full.fills for c in self.caches))
        x0, x1, y0, y1 = L, W - Rm, T, H - B

        def X(t):
            return x0 + (t - a) / max(1, b - a) * (x1 - x0)

        def Y(v):
            return y1 - v / ymax * (y1 - y0)

        for k in range(5):
            v = ymax * k / 4
            cv.create_line(x0, Y(v), x1, Y(v), fill=P["grid"])
            cv.create_text(x0 - 8, Y(v), text=fmt_int(v), anchor="e", font=F["tiny"], fill=P["muted"])
        for k in range(5):
            cv.create_text(x0 + (x1 - x0) * k / 4, y1 + 6, text=fmt_int(a + (b - a) * k / 4), font=F["tiny"], fill=P["muted"],
                           anchor="nw" if k == 0 else "ne" if k == 4 else "n")
        for i, c in enumerate(self.caches):
            color, n, pts = SERIES[i % len(SERIES)], 0, [X(c.t_min), Y(0)]
            for ae in c.events:
                if ae.event.kind is EventKind.FILL:
                    px = X(ae.event.time)
                    n += 1
                    pts += [px, Y(n - 1), px, Y(n)]
            pts += [X(c.t_end), Y(n)]
            cv.create_line(pts, fill=color, width=2)
            cv.create_text(X(c.t_end) + 8, Y(n), text=f"{c.name}  {n:,}", anchor="w", fill=color, font=F["small"])


def show(analyses: list[CacheAnalysis], params: ReportParams | None = None) -> None:
    """Open the viewer window and block until it is closed."""
    try:
        root = tk.Tk(className="cache-viz")
    except tk.TclError as e:
        raise SystemExit(f"cache-viz: cannot open a window ({e}); use -o FILE.html for the HTML report") from None
    names = short_names([a.log.name for a in analyses])
    Viewer(root, [CacheStats(a, n) for a, n in zip(analyses, names)], params or ReportParams())
    root.mainloop()
