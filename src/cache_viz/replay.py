"""Rebuilds the state of a direct-mapped, write-back cache from its events."""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import CacheLog, Event, EventKind


@dataclass
class LineState:
    """Block currently valid in a line."""

    tag: str
    dirty: bool
    start: int


@dataclass
class LineCounters:
    fills: int = 0
    evicts: int = 0
    dirty_sets: int = 0


@dataclass
class Segment:
    """Time span during which a line stayed valid with the same tag and dirty bit."""

    line: int
    start: int
    end: int
    tag: str
    dirty: bool
    open: bool = False  # still open at the end of the log

    def to_json(self) -> list:
        return [self.line, self.start, self.end, self.tag, int(self.dirty), int(self.open)]


@dataclass
class AnnotatedEvent:
    """Event plus the classification inferred during the replay.

    ``category``: ``cold``/``conf`` (FILL), ``set``/``re`` (DIRTY), ``wb``/``clean`` (EVICT).
    ``prev_kind``/``prev_tag``: how the previous block left the line before this FILL.
    """

    event: Event
    category: str = ""
    prev_kind: str = ""
    prev_tag: str = ""

    def to_json(self) -> list:
        e = self.event
        return [e.time, e.kind.value[0], e.line, e.tag, self.category, self.prev_kind, self.prev_tag]


@dataclass
class ReplayResult:
    segments: list[Segment] = field(default_factory=list)
    events: list[AnnotatedEvent] = field(default_factory=list)
    counters: list[LineCounters] = field(default_factory=list)
    final_state: list[LineState | None] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)
    t_end: int = 0


class CacheReplayer:
    """Replays the events of a :class:`CacheLog` line by line.

    Assumed semantics:
        FILL  -> the line becomes valid (clean) with the given TAG; if the line was
                 already valid and clean, it is a silent replacement.
        DIRTY -> write to the line: dirty bit = 1.
        EVICT -> write-back of the dirty line; the line stays invalid until the next FILL.
    """

    def __init__(self, nlines: int):
        self.nlines = nlines
        self.state: list[LineState | None] = [None] * nlines
        self.last_writeback: list[str | None] = [None] * nlines  # tag written back and not replaced yet
        self.seen: set[tuple[int, str]] = set()  # (line, tag) blocks brought in at least once
        self.result = ReplayResult(counters=[LineCounters() for _ in range(nlines)], final_state=self.state)

    @classmethod
    def run(cls, log: CacheLog) -> ReplayResult:
        replayer = cls(log.nlines)
        for event in log.events:
            replayer.apply(event)
        return replayer.finish(log.events)

    def apply(self, ev: Event) -> None:
        if ev.line >= self.nlines:
            self._anomaly(ev, f"line {ev.line} out of range 0..{self.nlines - 1}")
            return
        handler = {EventKind.FILL: self._fill, EventKind.DIRTY: self._dirty, EventKind.EVICT: self._evict}[ev.kind]
        annotated = AnnotatedEvent(ev)
        handler(ev, annotated)
        self.result.events.append(annotated)

    def finish(self, events: list[Event]) -> ReplayResult:
        t_first = events[0].time if events else 0
        t_last = events[-1].time if events else 0
        t_end = t_last + max(10, (t_last - t_first) // 100)
        for line in range(self.nlines):
            if self.state[line]:
                self._close(line, t_end).open = True
        self.result.t_end = t_end
        return self.result

    def _fill(self, ev: Event, out: AnnotatedEvent) -> None:
        line, s = ev.line, self.state[ev.line]
        self.result.counters[line].fills += 1
        if s:
            if s.dirty:
                self._anomaly(ev, f"FILL on line {line} replaces dirty tag {s.tag} without EVICT")
            out.prev_kind, out.prev_tag = "clean", s.tag
            self._close(line, ev.time)
        elif self.last_writeback[line] is not None:
            out.prev_kind, out.prev_tag = "wb", self.last_writeback[line]
        out.category = "conf" if (line, ev.tag) in self.seen else "cold"
        self.seen.add((line, ev.tag))
        self.last_writeback[line] = None
        self.state[line] = LineState(ev.tag, False, ev.time)

    def _dirty(self, ev: Event, out: AnnotatedEvent) -> None:
        line, s = ev.line, self.state[ev.line]
        self.result.counters[line].dirty_sets += 1
        if not s:
            self._anomaly(ev, f"DIRTY on invalid line {line}")
            self.state[line] = LineState(ev.tag, True, ev.time)
            out.category = "set"
            return
        if s.tag != ev.tag:
            self._anomaly(ev, f"DIRTY on line {line} with tag {ev.tag}, but the line holds tag {s.tag}")
        if s.dirty:
            out.category = "re"
        else:
            out.category = "set"
            self._close(line, ev.time)
            self.state[line] = LineState(ev.tag, True, ev.time)

    def _evict(self, ev: Event, out: AnnotatedEvent) -> None:
        line, s = ev.line, self.state[ev.line]
        self.result.counters[line].evicts += 1
        if not s:
            self._anomaly(ev, f"EVICT on already invalid line {line}")
            out.category = "wb"
            return
        if s.tag != ev.tag:
            self._anomaly(ev, f"EVICT on line {line} with tag {ev.tag}, but the line holds tag {s.tag}")
        out.category = "wb" if s.dirty else "clean"
        self._close(line, ev.time)
        self.state[line] = None
        self.last_writeback[line] = ev.tag

    def _close(self, line: int, t: int) -> Segment:
        s = self.state[line]
        seg = Segment(line, s.start, t, s.tag, s.dirty)
        self.result.segments.append(seg)
        return seg

    def _anomaly(self, ev: Event, msg: str) -> None:
        self.result.anomalies.append(f"t={ev.time}: {msg}")

