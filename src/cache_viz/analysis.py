"""Ties together parsing and replay of one CSV log."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import CacheLog
from .parser import LogParser
from .replay import CacheReplayer, ReplayResult


@dataclass
class CacheAnalysis:
    log: CacheLog
    replay: ReplayResult

    @classmethod
    def from_file(cls, path: Path, nlines: int | None = None) -> CacheAnalysis:
        return cls.from_log(LogParser(nlines).parse_file(path))

    @classmethod
    def from_log(cls, log: CacheLog) -> CacheAnalysis:
        return cls(log, CacheReplayer.run(log))

    @property
    def ok(self) -> bool:
        """True when the event sequence is consistent with a direct-mapped, write-back cache."""
        return not self.replay.anomalies

    def to_dict(self, name: str | None = None) -> dict:
        """Shape consumed by the HTML report's JavaScript."""
        return dict(
            name=name or self.log.name,
            file=self.log.path.name,
            nlines=self.log.nlines,
            events=[e.to_json() for e in self.replay.events],
            segs=[s.to_json() for s in self.replay.segments],
            t_end=self.replay.t_end,
            anomalies=self.replay.anomalies,
        )
