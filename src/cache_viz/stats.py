"""Metrics of one replayed cache over a time range: what the viewer shows."""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property

from .analysis import CacheAnalysis
from .models import EventKind
from .replay import AnnotatedEvent, Segment
from .report import ReportParams

NBINS = 60  # time windows of the per-window charts


def quantile(vals: list[float], q: float) -> float:
    """Linearly interpolated quantile; NaN when empty."""
    if not vals:
        return math.nan
    s = sorted(vals)
    i = (len(s) - 1) * q
    lo = int(i)
    return s[lo] + (s[min(lo + 1, len(s) - 1)] - s[lo]) * (i - lo)


def ratio(a: float, b: float) -> float:
    return a / b if b else math.nan


def fmt_int(n: float | None) -> str:
    return "–" if n is None or math.isnan(n) else f"{round(n):,}"


def fmt_num(n: float) -> str:
    return f"{n:,.2f}".rstrip("0").rstrip(".")


def pct(x: float) -> str:
    return f"{100 * x:.1f}%" if math.isfinite(x) else "–"


def fmt_bytes(b: float) -> str:
    if b >= 1 << 20:
        return f"{b / (1 << 20):.2f} MiB"
    return f"{b / 1024:.1f} KiB" if b >= 1024 else f"{round(b):,} B"


def cycles(t: float, p: ReportParams) -> str:
    return f" ({fmt_int(t / p.period)} cyc)" if p.period > 0 else ""


def describe(ae: AnnotatedEvent) -> str:
    """What the replay inferred about one event, in words."""
    e = ae.event
    if e.kind is EventKind.FILL:
        s = "compulsory miss (first access to the block)" if ae.category == "cold" else "re-fill: the block was in the cache before (conflict)"
        if ae.prev_kind == "clean":
            s += f", replaces tag {ae.prev_tag} (clean, no write-back)"
        elif ae.prev_kind == "wb":
            s += f", after write-back of tag {ae.prev_tag}"
        return s
    if e.kind is EventKind.DIRTY:
        return "write, the line was already dirty" if ae.category == "re" else "write: the line becomes dirty"
    return f"write-back of tag {e.tag} (dirty line evicted)" if ae.category == "wb" else f"evict of a clean line (tag {e.tag})"


def pingpongs(tags: list[str], pair: tuple[str, str] | None = None) -> int:
    """A->B->A patterns in a line's sequence of filled tags (only between ``pair`` when given)."""
    return sum(
        tags[i] == tags[i - 2] != tags[i - 1] and (pair is None or {tags[i], tags[i - 1]} <= set(pair))
        for i in range(2, len(tags))
    )


@dataclass
class LineStats:
    line: int
    fills: int = 0
    cold: int = 0
    conf: int = 0
    evicts: int = 0
    clean_repl: int = 0
    dirty: int = 0
    valid_time: float = 0
    tags: list[str] = field(default_factory=list)  # tags brought in, in order
    lifetimes: list[int] = field(default_factory=list)

    @property
    def used(self) -> bool:
        return bool(self.fills or self.evicts or self.dirty)

    @property
    def pingpong(self) -> int:
        return pingpongs(self.tags)


@dataclass
class RangeStats:
    a: float
    b: float
    lines: list[LineStats]
    bins: dict[str, list[int]]  # per time window: cold / conf FILLs, wb (all EVICTs)
    fills: int = 0
    cold: int = 0
    conf: int = 0
    dirty: int = 0
    evicts: int = 0
    clean_repl: int = 0  # FILLs that silently replaced a clean block
    resident: int = 0  # blocks still in the cache at the end of the range
    gaps: list[int] = field(default_factory=list)  # time between consecutive FILLs
    life_clean: list[int] = field(default_factory=list)
    life_wb: list[int] = field(default_factory=list)
    returns: list[int] = field(default_factory=list)  # time out of the cache of blocks that came back
    pairs: Counter = field(default_factory=Counter)  # (line, tag, tag) -> replacements between the two
    valid_time: float = 0
    dirty_time: float = 0

    @property
    def span(self) -> float:
        return max(1, self.b - self.a)

    @property
    def nbins(self) -> int:
        return len(self.bins["cold"])

    @property
    def util(self) -> float:
        return self.valid_time / (len(self.lines) * self.span)

    @property
    def dirty_util(self) -> float:
        return self.dirty_time / (len(self.lines) * self.span)

    @property
    def used_lines(self) -> int:
        return sum(L.used for L in self.lines)

    @property
    def pingpong(self) -> int:
        return sum(L.pingpong for L in self.lines)


class CacheStats:
    """Range-independent data derived from one replay, plus :meth:`window` for a time range."""

    def __init__(self, analysis: CacheAnalysis, name: str):
        self.analysis, self.name = analysis, name
        r = analysis.replay
        self.nlines = analysis.log.nlines
        self.events = r.events
        self.t_end = r.t_end
        # compressed time axis: every distinct event time is one step
        self.times = sorted({ae.event.time for ae in r.events})
        if not self.times or self.t_end > self.times[-1]:
            self.times.append(self.t_end)
        self.t_min = self.times[0]

        self.segs_by_line: list[list[Segment]] = [[] for _ in range(self.nlines)]
        for s in r.segments:
            self.segs_by_line[s.line].append(s)
        for segs in self.segs_by_line:
            segs.sort(key=lambda s: s.start)
        self.seg_starts = [[s.start for s in segs] for segs in self.segs_by_line]
        self.events_by_line: list[list[AnnotatedEvent]] = [[] for _ in range(self.nlines)]
        for ae in r.events:
            self.events_by_line[ae.event.line].append(ae)
        self.event_times = [[ae.event.time for ae in evs] for evs in self.events_by_line]
        self.used_lines = sum(bool(evs) for evs in self.events_by_line)

        self.occupancy = self._occupancy(r.segments)
        self.max_occ = max(v for _, v, _ in self.occupancy)
        self.t90 = next((t for t, v, _ in self.occupancy if v >= 0.9 * self.max_occ), None) if self.max_occ else None
        self.residencies, self.returns = self._residencies()

    def _occupancy(self, segments: list[Segment]) -> list[tuple[int, int, int]]:
        """(time, valid lines, dirty lines) step function."""
        deltas = []
        for s in segments:
            deltas.append((s.start, 1, s.dirty))
            if not s.open:  # an open segment does not empty at the end
                deltas.append((s.end, -1, s.dirty))
        deltas.sort(key=lambda d: (d[0], d[1]))
        occ, v, d = [(self.t_min, 0, 0)], 0, 0
        for t, k, dirty in deltas:
            v += k
            d += k if dirty else 0
            if occ[-1][0] == t:
                occ[-1] = (t, v, d)
            else:
                occ.append((t, v, d))
        return occ

    def _residencies(self):
        """(line, tag, fill time, exit time, clean/wb/open) per block stay, and (out, back) times of re-filled blocks."""
        cur: list[tuple | None] = [None] * self.nlines
        last_out, res, returns = {}, [], []
        for ae in self.events:
            e, r = ae.event, cur[ae.event.line]
            if e.kind is EventKind.FILL:
                if r:
                    res.append((*r, e.time, "clean"))
                    last_out[(e.line, r[1])] = e.time
                if (e.line, e.tag) in last_out:
                    returns.append((last_out[(e.line, e.tag)], e.time))
                cur[e.line] = (e.line, e.tag, e.time)
            elif e.kind is EventKind.EVICT and r:
                res.append((*r, e.time, "wb"))
                last_out[(e.line, r[1])] = e.time
                cur[e.line] = None
        res += [(*r, self.t_end, "open") for r in cur if r]
        return res, returns

    # ---- time axis: t <-> u in 0..1, linear or one step per distinct event time ----
    def u(self, t: float, linear: bool = False) -> float:
        ts, n = self.times, len(self.times)
        if linear:
            return (t - ts[0]) / max(1, ts[-1] - ts[0])
        if n < 2 or t <= ts[0]:
            return 0.0
        if t >= ts[-1]:
            return 1.0
        i = bisect_right(ts, t) - 1
        return (i + (t - ts[i]) / (ts[i + 1] - ts[i])) / (n - 1)

    def t(self, u: float, linear: bool = False) -> float:
        ts, n = self.times, len(self.times)
        u = min(1.0, max(0.0, u))
        if linear or n < 2:
            return ts[0] + u * (ts[-1] - ts[0])
        x = u * (n - 1)
        i = min(n - 2, int(x))
        return ts[i] + (x - i) * (ts[i + 1] - ts[i])

    def segment_at(self, line: int, t: float) -> Segment | None:
        i = bisect_right(self.seg_starts[line], t) - 1
        s = self.segs_by_line[line][i] if i >= 0 else None
        return s if s and t < s.end else None

    def events_around(self, line: int, t: float) -> list[AnnotatedEvent]:
        i = bisect_left(self.event_times[line], t)
        return self.events_by_line[line][max(0, i - 1) : i + 1]

    @cached_property
    def full(self) -> RangeStats:
        return self.window(self.t_min, self.t_end)

    def window(self, a: float, b: float, nbins: int = NBINS) -> RangeStats:
        R = RangeStats(a, b, [LineStats(i) for i in range(self.nlines)], {k: [0] * nbins for k in ("cold", "conf", "wb")})
        w = R.span / nbins
        last_fill = None
        for ae in self.events:
            e = ae.event
            if not a <= e.time <= b:
                continue
            L, k = R.lines[e.line], min(nbins - 1, int((e.time - a) / w))
            if e.kind is EventKind.FILL:
                R.fills += 1
                L.fills += 1
                if ae.category == "conf":
                    R.conf += 1
                    L.conf += 1
                else:
                    R.cold += 1
                    L.cold += 1
                R.bins[ae.category][k] += 1
                if ae.prev_kind == "clean":
                    R.clean_repl += 1
                    L.clean_repl += 1
                if ae.prev_kind:
                    R.pairs[(e.line, *sorted((ae.prev_tag, e.tag)))] += 1
                L.tags.append(e.tag)
                if last_fill is not None:
                    R.gaps.append(e.time - last_fill)
                last_fill = e.time
            elif e.kind is EventKind.DIRTY:
                R.dirty += 1
                L.dirty += 1
            else:
                R.evicts += 1
                L.evicts += 1
                R.bins["wb"][k] += 1
        for segs in self.segs_by_line:
            for s in segs:
                o = min(b, s.end) - max(a, s.start)
                if o > 0:
                    R.lines[s.line].valid_time += o
                    R.valid_time += o
                    R.dirty_time += o if s.dirty else 0
        for line, _, t0, t1, how in self.residencies:
            if t0 <= b < t1 or (how == "open" and t0 <= b):
                R.resident += 1
            elif how != "open" and a <= t1 <= b:
                (R.life_wb if how == "wb" else R.life_clean).append(t1 - t0)
                R.lines[line].lifetimes.append(t1 - t0)
        R.returns = [back - out for out, back in self.returns if a <= back <= b]
        return R


def stall(R: RangeStats, p: ReportParams) -> float:
    return R.fills * p.miss_penalty + R.evicts * p.wb_penalty


def amount(n: int, p: ReportParams) -> str:
    return fmt_bytes(n * p.block_bytes) if p.block_bytes else f"{n:,} blocks"


def cards(c: CacheStats, R: RangeStats, p: ReportParams) -> list[tuple[str, str, str]]:
    """(value, label, detail) of the headline numbers."""
    last = (
        (fmt_int(stall(R, p)), "stall cycles (estimate)", f"miss {fmt_num(p.miss_penalty)} · WB {fmt_num(p.wb_penalty)} cycles")
        if p.miss_penalty or p.wb_penalty
        else (f"{R.used_lines}/{c.nlines}", "active lines", "set penalties for a stall estimate")
    )
    return [
        (f"{R.fills:,}", "misses (FILLs)", f"{R.cold:,} compulsory · {R.conf:,} re-fills"),
        (pct(ratio(R.conf, R.fills)), "misses that are re-fills", f"{R.pingpong:,} A→B→A ping-pongs"),
        (f"{R.evicts:,}", "write-backs", f"{R.clean_repl:,} clean replacements"),
        (amount(R.fills + R.evicts, p), "memory traffic", f"{amount(R.fills, p)} in · {amount(R.evicts, p)} out"),
        (pct(R.util), "average occupancy", f"dirty {pct(R.dirty_util)} · max {c.max_occ}/{c.nlines}"),
        last,
    ]


def insights(c: CacheStats, R: RangeStats, p: ReportParams) -> list[str]:
    """Plain-language findings about the range."""
    F = R.fills
    if not F and not R.evicts:
        return ["No events in this range."]
    out = [f"{F:,} misses (FILLs): {pct(ratio(R.cold, F))} compulsory, {pct(ratio(R.conf, F))} re-fills of blocks that had been in the cache before."]
    if R.conf:
        top = sorted((L for L in R.lines if L.conf), key=lambda L: -L.conf)[:3]
        out.append(
            f"Re-fills concentrate on lines {', '.join(str(L.line) for L in top)}: {pct(sum(L.conf for L in top) / R.conf)} of them"
            f" (line {top[0].line} alone: {top[0].conf})."
        )
        if R.pairs:
            (line, x, y), n = R.pairs.most_common(1)[0]
            pp = pingpongs(R.lines[line].tags, (x, y))
            out.append(f"Most intense contention: tags {x} ↔ {y} on line {line}, {n} replacements" + (f" and {pp} A→B→A ping-pongs." if pp else "."))
        unused = c.nlines - c.used_lines
        if unused > 0:
            out.append(
                f"There are re-fills while {unused} of {c.nlines} lines were never used (max occupancy {c.max_occ}/{c.nlines}): "
                "the repeated misses come from mapping conflicts (blocks with the same index), not lack of capacity. "
                "Associativity (2-way) or moving the contested data usually removes them."
            )
        else:
            out.append("All cache lines were used: some re-fills may be capacity misses (working set larger than the cache), not only conflicts.")
    elif F:
        out.append("No re-fills: every miss is compulsory (the working set fits in the cache).")
    tot = [x + y for x, y in zip(R.bins["cold"], R.bins["conf"])]
    k, avg, w = tot.index(max(tot)), F / R.nbins, R.span / R.nbins
    if F and tot[k] > 1.5 * avg:
        out.append(f"Miss peak in [{fmt_int(R.a + w * k)}, {fmt_int(R.a + w * (k + 1))}): {tot[k]} FILLs, {fmt_num(tot[k] / avg)}× the average window ({fmt_num(avg)}).")
    if c.t90 is not None:
        after = [ae for ae in c.events if ae.event.kind is EventKind.FILL and ae.event.time > c.t90]
        cold = sum(ae.category == "cold" for ae in after)
        out.append(
            f"Warm-up: occupancy reaches 90% of its maximum ({c.max_occ} lines) at t={fmt_int(c.t90)}{cycles(c.t90, p)}. "
            f"After that: {len(after)} misses, {pct(ratio(cold, len(after)))} compulsory."
        )
    if R.returns:
        m = quantile(R.returns, 0.5)
        out.append(f"Half of the evicted blocks came back within {fmt_int(m)} t.u.{cycles(m, p)} (p90 {fmt_int(quantile(R.returns, 0.9))}): they were evicted while still in use.")
    exits = len(R.life_clean) + len(R.life_wb)
    if exits:
        out.append(
            f"{pct(len(R.life_wb) / exits)} of block exits needed a write-back, {pct(len(R.life_clean) / exits)} were clean replacements. "
            f"Median block lifetime: {fmt_int(quantile(R.life_clean + R.life_wb, 0.5))} t.u."
        )
    if R.dirty:
        out.append(f"{R.dirty:,} DIRTY events (first write of each stay): write-through would need at least {R.dirty:,} memory writes, versus {R.evicts:,} write-backs here.")
    if p.miss_penalty or p.wb_penalty:
        st = stall(R, p)
        s = f"Estimated stall: {fmt_int(st)} cycles ({F:,} × {fmt_num(p.miss_penalty)} + {R.evicts:,} × {fmt_num(p.wb_penalty)})"
        if p.period > 0:
            s += f", {pct(st / (R.span / p.period))} of the {fmt_int(R.span / p.period)} cycles in the range"
        out.append(s + ".")
    return out


def comparison(caches: list[CacheStats], p: ReportParams) -> list[tuple[str, list[str]]]:
    """(metric, value per cache) over each cache's full run."""
    rows = [
        ("lines", lambda c, R: f"{c.nlines:,}"),
        ("events", lambda c, R: f"{len(c.events):,}"),
        ("used lines", lambda c, R: f"{c.used_lines} ({pct(c.used_lines / c.nlines)})"),
        ("misses (FILLs)", lambda c, R: f"{R.fills:,}"),
        ("compulsory", lambda c, R: f"{R.cold:,}"),
        ("re-fills", lambda c, R: f"{R.conf:,} ({pct(ratio(R.conf, R.fills))})"),
        ("ping-pongs", lambda c, R: f"{R.pingpong:,}"),
        ("write-backs", lambda c, R: f"{R.evicts:,}"),
        ("clean replacements", lambda c, R: f"{R.clean_repl:,}"),
        ("DIRTY events", lambda c, R: f"{R.dirty:,}"),
        ("average occupancy", lambda c, R: pct(R.util)),
        ("max occupancy", lambda c, R: f"{c.max_occ}/{c.nlines}"),
        ("warm-up (90%)", lambda c, R: fmt_int(c.t90)),
        ("median lifetime (t.u.)", lambda c, R: fmt_int(quantile(R.life_clean + R.life_wb, 0.5))),
        ("median time out (t.u.)", lambda c, R: fmt_int(quantile(R.returns, 0.5))),
        ("memory traffic", lambda c, R: amount(R.fills + R.evicts, p)),
        ("stall estimate (cycles)", lambda c, R: fmt_int(stall(R, p)) if p.miss_penalty or p.wb_penalty else "–"),
        ("anomalies", lambda c, R: f"{len(c.analysis.replay.anomalies):,}"),
    ]
    return [(label, [f(c, c.full) for c in caches]) for label, f in rows]
