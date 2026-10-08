"""Parsing of the ``time,event,line,tag`` CSV logs written by DMDebug."""
from __future__ import annotations

import csv
import io
from pathlib import Path

from .models import CacheLog, Event, EventKind

COLUMNS = ("time", "event", "line", "tag")


def infer_nlines(max_line: int) -> int:
    """Smallest power of two above ``max_line``: a direct-mapped cache has 2**k lines."""
    return 1 << max_line.bit_length()


class LogParser:
    """Turns a CSV cache log into a :class:`CacheLog`.

    ``nlines`` sets the number of cache lines; when ``None`` it is inferred from the
    highest line index seen (see :func:`infer_nlines`).
    """

    def __init__(self, nlines: int | None = None):
        self.nlines = nlines

    def parse_file(self, path: Path) -> CacheLog:
        return self.parse(path.read_text(encoding="utf-8"), path)

    def parse(self, text: str, path: Path) -> CacheLog:
        reader = csv.DictReader(io.StringIO(text))
        missing = set(COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path}: expected CSV header {','.join(COLUMNS)}, missing {', '.join(sorted(missing))}")

        events = []
        for row in reader:
            try:
                events.append(Event(int(row["time"]), EventKind(row["event"].strip().upper()), int(row["line"]), row["tag"].strip()))
            except (ValueError, AttributeError) as e:
                raise ValueError(f"{path}:{reader.line_num}: bad row {row}: {e}") from None
        events.sort(key=lambda e: e.time)  # stable: keeps file order on ties

        if self.nlines is not None:
            return CacheLog(path, self.nlines, events)
        return CacheLog(path, infer_nlines(max((e.line for e in events), default=0)), events, nlines_inferred=True)
