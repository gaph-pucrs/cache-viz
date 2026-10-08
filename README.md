# cache-viz

A desktop viewer (tkinter, no extra dependencies) showing how one or more caches behave
over time, from the `FILL` / `DIRTY` / `EVICT` CSV logs written by the `DMDebug`
simulation monitor. It can also write the same analysis as a self-contained HTML report.

The viewer shows a timeline for every cache line, with a misses strip and an occupancy
strip above it, next to plain-language findings and the hottest lines. Every number
(cards, findings, per-line table) follows the timeline's zoom. Load the instruction and
data cache logs together to switch between them and compare them side by side.

## Installation

Requires Python ≥ 3.9 with tkinter (bundled with most Python builds; on Arch/CachyOS it is the
`tk` package). No other runtime dependencies.

```sh
pipx install .            # or: uv tool install .   /   pip install .
```

For development:

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Usage

```sh
cache-viz debug/*.csv                              # open the viewer with icache + dcache
cache-viz debug/testbench.pe.dcache_ctrl.u_debug.csv
cache-viz debug/*.csv --period 10                  # also show time in cycles
cache-viz debug/*.csv --block-bytes 64 --miss-penalty 20 --wb-penalty 20
                                                   # traffic in bytes and stall estimate
cache-viz debug/*.csv -o report.html               # HTML report instead of the viewer
```

In the viewer: mouse wheel zooms, dragging pans, clicking a row pins that line, double-click
or `Esc` fits the whole run. "per event" gives every distinct event time the same width
(good for dense bursts); "real time" is linear. The four parameters can also be edited in
the sidebar while the viewer is open.

It also runs as a module: `python -m cache_viz ...`.

| Option | Default | Description |
|---|---|---|
| `-o`, `--out` | – | write an HTML report instead of opening the viewer |
| `--lines` | inferred | number of cache lines (see below) |
| `--period` | `0` | clock period in `time` units (shows cycles) |
| `--block-bytes` | `0` | block size in bytes (memory traffic) |
| `--miss-penalty` | `0` | FILL penalty in cycles |
| `--wb-penalty` | `0` | write-back penalty in cycles |

For each log, the terminal prints a one-line status plus up to 20 anomalies:

```
testbench.pe.dcache_ctrl.u_debug.csv: 64 lines (inferred), 689 events, 0 anomalies
```

## Log format

`DMDebug` (bound into every `DMCtrl` by the testbench) writes one file per cache,
named after its instance path, e.g. `debug/testbench.pe.dcache_ctrl.u_debug.csv`:

```
time,event,line,tag
2165,FILL,20,14
156485,DIRTY,43,14
313425,EVICT,43,14
```

- **Cache name**: the report drops the monitor instance (`.u_debug`) and keeps the
  shortest dotted suffix that tells the loaded files apart: `icache_ctrl`,
  `dcache_ctrl`, or `pe0.dcache_ctrl` / `pe1.dcache_ctrl` with several PEs.
- **Number of lines**: not in the file. A direct-mapped cache has 2ⁿ lines, so it
  defaults to the smallest power of two above the highest line index seen. If the
  program never touches the upper lines, this guesses too low; pass `--lines`
  (2^(`CACHE_WIDTH` − `OFFSET_WIDTH`)). `--lines` applies to every file given.

Assumed semantics (direct-mapped, write-back cache):

- **FILL**: the line becomes valid (clean) with the given tag. If it was already valid
  and clean, this is a silent replacement.
- **DIRTY**: the first write to a clean line sets the dirty bit.
- **EVICT**: write-back of the dirty line. The line stays invalid until the next FILL.

Events that break these rules (DIRTY/EVICT on an invalid line, tag mismatches, a dirty
line replaced without EVICT) are reported as anomalies.

## Library use

```python
from pathlib import Path
from cache_viz import CacheAnalysis, HtmlReport, ReportParams

caches = [CacheAnalysis.from_file(p, nlines=64) for p in sorted(Path("debug").glob("*.csv"))]
print([c.replay.anomalies for c in caches])
HtmlReport(caches, ReportParams(period=10)).write(Path("out.html"))

from cache_viz.gui import show
show(caches, ReportParams(period=10))   # opens the viewer, blocks until closed
```

## Layout

```
src/cache_viz/
├── models.py      # dataclasses: Event, CacheLog
├── parser.py      # LogParser: CSV -> CacheLog
├── replay.py      # CacheReplayer: rebuilds the state and classifies events
├── analysis.py    # CacheAnalysis: parse + replay
├── stats.py       # CacheStats: metrics over a time range, findings, comparison
├── gui.py         # Viewer: the tkinter window
├── report.py      # HtmlReport: injects the data into the template
├── cli.py         # argparse / `cache-viz` entry point
└── templates/report.html
```
