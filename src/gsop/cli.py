"""Single CLI: `uv run gsop ...`. Same commands on Windows and macOS."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import psutil
import typer
from rich.table import Table

from . import __version__
from . import golden as GD
from . import pipeline as P
from . import tools as T
from .checks import Report, console
from .config import data_dir, load_all, results_dir
from .montecarlo import memory_plan
from .provenance import ROOT, package_versions, read_json, sha256_file, write_json
from .runner import STAGES, BodyRun

app = typer.Typer(no_args_is_help=True, add_completion=False, help="GSOP simulation engine")


def _group(name: str, help: str) -> typer.Typer:
    g = typer.Typer(no_args_is_help=True, help=help)

    @g.callback()
    def _cb() -> None:  # keeps the sub-command name in the path, e.g. `gsop s3 gates`
        pass
    app.add_typer(g, name=name)
    return g


s1, s2, s3, s4 = (_group(n, h) for n, h in (("s1", "tile grid"), ("s2", "features and targets"),
                                            ("s3", "gates"), ("s4", "base similarity")))
s5, s6, s7 = (_group(n, h) for n, h in (("s5", "Monte Carlo"), ("s6", "ML second opinion"), ("s7", "validation")))
s8, s9 = (_group(n, h) for n, h in (("s8", "export"), ("s9", "discovery")))

BodyOpt = typer.Option(..., "--body", help="moon or mars")
EARTH = lambda: data_dir("processed") / "earth_features_6km.parquet"  # noqa: E731


def _check_body(body: str) -> str:
    if body not in ("moon", "mars"):
        raise typer.BadParameter("body must be moon or mars")
    return body


def _body_run(body: str, runs: Optional[int], workers: Optional[int], store: bool = True) -> BodyRun:
    body = _check_body(body)
    cfg = load_all()
    ep = EARTH()
    if not ep.exists():
        console.print(f"[FAIL] {ep} not found. Build it with `gsop s2 earth` (or copy it from the machine that built it "
                      "and run `gsop verify-data`).")
        raise typer.Exit(1)
    tp_path = data_dir("processed") / f"targets_{body}.parquet"
    if not tp_path.exists():
        console.print(f"[FAIL] {tp_path} not found. Run `gsop s2 targets --body {body}`.")
        raise typer.Exit(1)
    earth = pd.read_parquet(ep)
    return BodyRun(body, cfg, earth, P.load_target_profiles(tp_path), results_dir(body),
                   data_dir("interim") / "mc" / body, int(runs or cfg["run"]["runs"]),
                   int(workers or os.cpu_count() or 1), float(psutil.virtual_memory().available), sha256_file(ep),
                   use_store=store)


RunsOpt = typer.Option(None, "--runs", help="Monte Carlo runs (default from config/run.yaml)")
WorkersOpt = typer.Option(None, "--workers", help="worker processes (default: all cores)")


@app.command()
def doctor() -> None:
    """Machine, packages, Earth Engine login and the memory-safe chunk size."""
    cfg = load_all()
    vm = psutil.virtual_memory()
    free_disk = psutil.disk_usage(str(ROOT)).free
    t = Table(title=f"gsop {__version__} doctor")
    t.add_column("item")
    t.add_column("value")
    import platform
    for k, v in (("OS", platform.platform()), ("machine", platform.machine()), ("Python", sys.version.split()[0]),
                 ("cores (logical)", os.cpu_count()), ("RAM total", f"{vm.total / 2**30:.1f} GB"),
                 ("RAM free", f"{vm.available / 2**30:.1f} GB"), ("disk free", f"{free_disk / 2**30:.0f} GB")):
        t.add_row(k, str(v))
    for k, v in package_versions().items():
        t.add_row(f"pkg {k}", v)
    ee_state = "not authenticated"
    try:
        import ee
        from ee import oauth
        if Path(oauth.get_credentials_path()).exists():
            ee_state = "credentials file present (login not verified over the network)"
    except Exception as e:  # noqa: BLE001
        ee_state = f"earthengine-api problem: {e}"
    t.add_row("Earth Engine", ee_state)
    plan = memory_plan(4_000_000, 15, os.cpu_count() or 1, vm.available, float(cfg["run"]["ram_fraction"]))
    t.add_row("RAM budget (40% of free)", f"{plan['budget_bytes'] / 2**30:.1f} GB")
    t.add_row("memory-safe cell chunk", f"{plan['chunk_tiles']:,} tiles (4M tiles, 15 columns, all cores)")
    t.add_row("fits all-core run", "yes" if plan["fits"] else "NO: use --workers with a smaller number")
    console.print(t)


@s1.command("tiles")
def s1_tiles(raster: Path = typer.Option(..., "--raster", help="6 km EPSG:6933 GeoTIFF with a land_frac band")) -> None:
    """Grid + land mask -> data/interim/tiles.parquet."""
    from .earth.local_loaders import build_earth_table
    df = build_earth_table(raster, data_dir("interim") / "_tmp_full.parquet")
    df[["tile_id", "ix", "iy", "lon", "lat"]].to_parquet(data_dir("interim") / "tiles.parquet", index=False)
    (data_dir("interim") / "_tmp_full.parquet").unlink(missing_ok=True)
    console.print(f"[PASS] {len(df):,} land tiles -> data/interim/tiles.parquet")


@s2.command("earth")
def s2_earth(source: str = typer.Option("local", "--source", help="gee or local"),
             src: Optional[Path] = typer.Option(None, "--src", help="local: GeoTIFF or folder of 6 km rasters")) -> None:
    """Earth features -> data/processed/earth_features_6km.parquet (+ grid.json, MANIFEST sha256)."""
    out = EARTH()
    if source == "gee":
        from .earth import gee_export
        gee_export.run()
        return
    from .earth.local_loaders import build_earth_table
    s = src or data_dir("raw") / "earth"
    df = build_earth_table(s, out)
    T.write_data_manifest(out.parent)
    console.print(f"[PASS] {len(df):,} tiles -> {out}; MANIFEST.json written (send it with the parquet and grid.json)")


@s2.command("targets")
def s2_targets(body: str = BodyOpt, dem: Optional[Path] = typer.Option(None, "--dem", help="DEM GeoTIFF (LOLA or MOLA)")) -> None:
    """Target profiles -> data/processed/targets_{body}.parquet."""
    from .targets import common, mars, moon
    cfg = load_all()
    rows = (moon if _check_body(body) == "moon" else mars).build(cfg, dem)
    df = common.write_profile(rows, data_dir("processed") / f"targets_{body}.parquet")
    un = df[df["unavailable"]].groupby("target")["col"].apply(list).to_dict()
    console.print(f"[PASS] {df['target'].nunique()} targets written")
    for t, c in un.items():
        console.print(f"[WARN] {t}: unavailable {c}")


def _stage_cmd(group: typer.Typer, cmd: str, stages: tuple[str, ...], doc: str) -> None:
    @group.command(cmd, help=doc)
    def _run(body: str = BodyOpt, runs: Optional[int] = RunsOpt, workers: Optional[int] = WorkersOpt) -> None:
        br = _body_run(body, runs, workers)
        br.run(stages)
        console.print(f"[PASS] {doc} done for {body}")


_stage_cmd(s3, "gates", ("gates",), "gates: passed/rejected tables with reasons")
_stage_cmd(s4, "score", ("gates", "score"), "base similarity 0-100 per target x profile")
_stage_cmd(s5, "simulate", ("gates", "simulate"), "Monte Carlo simulation")
_stage_cmd(s6, "ml", ("ml",), "ML second opinion")
_stage_cmd(s7, "validate", ("validate",), "validation against known sites")
_stage_cmd(s8, "export", ("export",), "export results for the site")
_stage_cmd(s9, "discover", ("discover",), "discovery: robust and novel candidate list")


@app.command()
def run(body: str = BodyOpt, runs: Optional[int] = RunsOpt, workers: Optional[int] = WorkersOpt) -> None:
    """Runs s3..s7 (+s8, s9) in order, resumable. Writes results/<body>/run_meta.json."""
    br = _body_run(body, runs, workers)
    br.run(STAGES)
    if br.unscored:
        for k, v in br.unscored.items():
            console.print(f"[WARN] {k}: {v}")
    console.print(f"[PASS] run complete: results/{body}/")


@app.command()
def golden(regenerate_inputs: bool = typer.Option(False, "--regenerate-inputs", help="maintainers only"),
           out: Path = typer.Option(Path("golden.json"), "--out"), workers: int = typer.Option(1, "--workers"),
           check: bool = typer.Option(False, "--check", help="compare with tests/golden/golden_expected.json")) -> None:
    """Fixed 5,000-tile synthetic slice, 50 runs, both bodies. Writes golden.json."""
    if regenerate_inputs:
        GD.make_inputs()
        console.print("[WARN] golden inputs regenerated: delete tests/golden/golden_expected.json and re-record it")
    t0 = time.perf_counter()
    res = GD.run_golden(workers=workers, out=out)
    console.print(f"[PASS] golden run {time.perf_counter() - t0:.1f}s -> {out}")
    if check:
        tol = load_all()["run"]["compare"]
        rep = Report("golden vs expected")
        for r in T.compare_golden(read_json(GD.GOLDEN_DIR / "golden_expected.json"), res, tol):
            rep.check(r["name"], r["ok"], r["detail"])
        raise typer.Exit(rep.finish())


@app.command("verify-data")
def verify_data() -> None:
    """Checks sha256 of data/processed files against MANIFEST.json."""
    bad = T.verify_data(data_dir("processed"))
    if bad:
        for b in bad:
            console.print(f"[FAIL] {b}")
        raise typer.Exit(1)
    console.print("[PASS] data/processed matches MANIFEST.json")


@app.command()
def compare(dir_a: Path, dir_b: Path, report: Path = typer.Option(Path("compare_report.json"), "--report")) -> None:
    """Compares two result folders (or two golden.json files) with tolerances."""
    tol = load_all()["run"]["compare"]
    rows = T.compare_dirs(dir_a, dir_b, tol, report)
    rep = Report("compare")
    for r in rows:
        rep.check(r["name"], r["ok"], r["detail"])
    raise typer.Exit(rep.finish())


@app.command()
def merge(results_moon: Path, results_mars: Path, out: Path = typer.Option(None, "--out"),
          force: bool = typer.Option(False, "--force")) -> None:
    """Merges the two bodies' exports into results/all/ for the site."""
    out = out or results_dir() / "all"
    for w in T.merge_results(results_moon, results_mars, out, force):
        console.print(f"[WARN] {w}")
    console.print(f"[PASS] merged into {out}")


@app.command("check-operators")
def check_operators() -> None:
    """Earth Engine vs numpy terrain operators on one small window. Phase 2: needs an authenticated session."""
    try:
        import ee
        ee.Initialize()
    except Exception as e:  # noqa: BLE001
        console.print(f"[FAIL] Earth Engine is not ready ({e}). Run `earthengine authenticate`, give the Cloud project "
                      "id to Anay, then implement the Earth Engine side (issue #2).")
        raise typer.Exit(1)
    console.print("[PENDING] Earth Engine side of the operator is not implemented yet (issue #2)")
    raise typer.Exit(2)


if __name__ == "__main__":
    app()
