import json
import re
from pathlib import Path

import pytest

from cache_viz import CacheAnalysis, CacheReplayer, EventKind, LogParser
from cache_viz.cli import main
from cache_viz.parser import infer_nlines
from cache_viz.report import short_names

DATA = Path(__file__).parent / "data"
SAMPLE = DATA / "sample.csv"
ICACHE = DATA / "testbench.pe.icache_ctrl.u_debug.csv"
DCACHE = DATA / "testbench.pe.dcache_ctrl.u_debug.csv"


def test_parser_reads_csv():
    log = LogParser().parse_file(SAMPLE)
    assert len(log.events) == 9
    assert log.events[2].kind is EventKind.EVICT and log.events[2].tag == "1"
    assert (log.nlines, log.nlines_inferred) == (2, True)


def test_parser_nlines_override_and_inference():
    assert LogParser(64).parse_file(SAMPLE).nlines == 64
    assert [infer_nlines(n) for n in (0, 1, 47, 63, 64)] == [1, 2, 64, 64, 128]


@pytest.mark.parametrize(
    "text, msg",
    [
        ("t,event,line,tag\n", "missing time"),
        ("time,event,line,tag\n10,FLUSH,0,1\n", "x.csv:2"),
        ("time,event,line,tag\nabc,FILL,0,1\n", "x.csv:2"),
    ],
)
def test_parser_rejects_bad_input(text, msg):
    with pytest.raises(ValueError, match=msg):
        LogParser().parse(text, Path("x.csv"))


def test_log_name_drops_monitor_instance():
    assert LogParser().parse_file(DCACHE).name == "testbench.pe.dcache_ctrl"


def test_short_names():
    assert short_names(["testbench.pe.icache_ctrl", "testbench.pe.dcache_ctrl"]) == ["icache_ctrl", "dcache_ctrl"]
    assert short_names(["t.pe0.dcache_ctrl", "t.pe1.dcache_ctrl", "t.pe0.icache_ctrl"]) == [
        "pe0.dcache_ctrl",
        "pe1.dcache_ctrl",
        "icache_ctrl",
    ]


def test_replay_classifies_events():
    result = CacheReplayer.run(LogParser().parse_file(SAMPLE))
    got = [(a.event.kind.value[0], a.category, a.prev_kind, a.prev_tag) for a in result.events]
    assert got == [
        ("F", "cold", "", ""),
        ("D", "set", "", ""),
        ("E", "wb", "", ""),
        ("F", "cold", "wb", "1"),
        ("F", "cold", "", ""),
        ("F", "cold", "clean", "3"),
        ("F", "conf", "clean", "4"),
        ("D", "set", "", ""),
        ("D", "re", "", ""),
    ]
    assert not result.anomalies
    assert sum(s.open for s in result.segments) == 2


def test_replay_reports_anomalies():
    log = LogParser().parse("time,event,line,tag\n1,DIRTY,0,1\n2,FILL,0,2\n3,EVICT,1,5\n", Path("x.csv"))
    assert CacheReplayer.run(log).anomalies == [
        "t=1: DIRTY on invalid line 0",
        "t=2: FILL on line 0 replaces dirty tag 1 without EVICT",
        "t=3: EVICT on already invalid line 1",
    ]


@pytest.mark.parametrize("path", [ICACHE, DCACHE])
def test_simulator_logs_are_consistent(path):
    assert CacheAnalysis.from_file(path).ok


def test_cli_writes_one_report_for_icache_and_dcache(tmp_path, capsys):
    out = tmp_path / "out.html"
    assert main([str(ICACHE), str(DCACHE), "-o", str(out), "--period", "10"]) == 0
    data = json.loads(re.search(r"const DATA = (.*?);\n", out.read_text(encoding="utf-8")).group(1))
    assert [c["name"] for c in data["caches"]] == ["icache_ctrl", "dcache_ctrl"]
    assert data["params"]["period"] == 10.0
    assert "64 lines (inferred)" in capsys.readouterr().out


def test_cli_reports_bad_file(tmp_path, capsys):
    bad = tmp_path / "bad.csv"
    bad.write_text("nope\n")
    with pytest.raises(SystemExit) as e:
        main([str(bad)])
    assert e.value.code == 2
    assert "expected CSV header" in capsys.readouterr().err


def test_stats_window_counts_and_time_axis():
    from cache_viz.stats import CacheStats, comparison, insights
    from cache_viz.report import ReportParams

    c = CacheStats(CacheAnalysis.from_file(SAMPLE), "sample")
    R = c.full
    assert (R.fills, R.cold, R.conf, R.dirty, R.evicts, R.clean_repl) == (5, 4, 1, 3, 1, 2)
    assert sum(R.bins["cold"]) + sum(R.bins["conf"]) == R.fills
    for linear in (False, True):
        assert all(c.t(c.u(t, linear), linear) == pytest.approx(t) for t in c.times)
    assert c.window(c.t_min, c.times[2]).fills < R.fills
    assert insights(c, R, ReportParams(miss_penalty=10))[-1].startswith("Estimated stall")
    assert all(len(values) == 1 for _, values in comparison([c], ReportParams()))


def test_viewer_smoke():
    tk = pytest.importorskip("tkinter")
    from cache_viz import gui
    from cache_viz.report import ReportParams
    from cache_viz.stats import CacheStats

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    try:
        caches = [CacheStats(CacheAnalysis.from_file(p), p.name) for p in (ICACHE, DCACHE)]
        v = gui.Viewer(root, caches, ReportParams(period=10))
        root.geometry("1400x900")
        root.update()
        v.draw_timeline()
        if v.geom:
            v.zoom(0.5, v.geom[0] + 10)
        v.refresh_stats()
        v.select_line(v.hot_rows[0])
        v.select(1)
        v.sort_lines("conf")
        v.param_vars["miss_penalty"].set("20")
        v.apply_params()
        assert v.cards[5][1].cget("text") == "stall cycles (estimate)"
    finally:
        root.destroy()
