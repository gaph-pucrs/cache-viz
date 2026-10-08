"""Interactive HTML report generation."""
from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .analysis import CacheAnalysis


def short_names(names: list[str]) -> list[str]:
    """Shortest dotted suffix that tells each hierarchical name apart.

    ``testbench.pe.icache_ctrl``, ``testbench.pe.dcache_ctrl`` -> ``icache_ctrl``, ``dcache_ctrl``
    """
    parts = [n.split(".") for n in names]
    out = []
    for p in parts:
        for k in range(1, len(p) + 1):
            if sum(q[-k:] == p[-k:] for q in parts) == 1:
                break
        out.append(".".join(p[-k:]))
    return out


@dataclass(frozen=True)
class ReportParams:
    period: float = 0  # clock period in TIME units (0 = no cycles shown)
    block_bytes: int = 0  # block size in bytes (0 = traffic shown in blocks)
    miss_penalty: float = 0  # cycles per FILL
    wb_penalty: float = 0  # cycles per write-back

    def to_dict(self) -> dict:
        return dict(period=self.period, blockBytes=self.block_bytes, missPen=self.miss_penalty, wbPen=self.wb_penalty)


class HtmlReport:
    PLACEHOLDER = "/*__DATA__*/null"

    def __init__(self, caches: list[CacheAnalysis], params: ReportParams | None = None):
        self.caches = caches
        self.params = params or ReportParams()

    @staticmethod
    def template() -> str:
        return files(__package__).joinpath("templates/report.html").read_text(encoding="utf-8")

    def render(self) -> str:
        names = short_names([c.log.name for c in self.caches])
        caches = [c.to_dict(name) for c, name in zip(self.caches, names)]
        payload = dict(caches=caches, params=self.params.to_dict())
        data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
        return self.template().replace(self.PLACEHOLDER, data)

    def write(self, path: Path) -> None:
        path.write_text(self.render(), encoding="utf-8")
