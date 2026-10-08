"""Data structures shared by the parser, the replay and the report."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# DMDebug writes to ./debug/<its instance path>.csv; the testbench binds it as `u_debug`
MONITOR_SUFFIX = ".u_debug"


class EventKind(str, Enum):
    FILL = "FILL"
    DIRTY = "DIRTY"
    EVICT = "EVICT"


@dataclass(frozen=True)
class Event:
    """One CSV row: ``time,event,line,tag``."""

    time: int
    kind: EventKind
    line: int
    tag: str


@dataclass
class CacheLog:
    """Parsed contents of one CSV log."""

    path: Path
    nlines: int
    events: list[Event] = field(default_factory=list)
    nlines_inferred: bool = False

    @property
    def name(self) -> str:
        """Hierarchical path of the cache controller, e.g. ``testbench.pe.dcache_ctrl``."""
        return self.path.stem.removesuffix(MONITOR_SUFFIX)
