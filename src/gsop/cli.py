"""Single CLI: `uv run gsop ...`. Same commands on Windows and macOS."""

from __future__ import annotations

import logging
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
from .parallel import default_workers
from .provenance import ROOT, package_versions, read_json, sha256_file, write_json
from .runner import STAGES, BodyRun, stage_name, stages_from

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


def _parse_bbox(bbox: Optional[str]) -> Optional[tuple[float, float, float, float]]:
    """--bbox lon_min,lat_min,lon_max,lat_max, or None. Anything else is a usage error, not a traceback."""
    if bbox is None:
        return None
    try:
        box = tuple(float(v) for v in bbox.split(","))
    except ValueError:
        raise typer.BadParameter("--bbox needs four numbers: lon_min,lat_min,lon_max,lat_max")
    if len(box) != 4:
        raise typer.BadParameter("--bbox needs four numbers: lon_min,lat_min,lon_max,lat_max")
    if not (box[0] < box[2] and box[1] < box[3]):
        raise typer.BadParameter("--bbox needs lon_min < lon_max and lat_min < lat_max")
    return box


def _check_body(body: str) -> str:
    if body not in ("moon", "mars"):
        raise typer.BadParameter("body must be moon or mars")
    return body


def _enable_stage_log() -> None:
    """Show every stage skip and rerun, with the reason, on stderr."""
    lg = logging.getLogger("gsop")            # parent of gsop.runner, .montecarlo, .pipeline, .tiles
    if not lg.handlers:
        class _Stderr(logging.StreamHandler):          # follows sys.stderr, which test runners swap per call
            def __init__(self) -> None:
                super().__init__()

            @property
            def stream(self):
                return sys.stderr

            @stream.setter
            def stream(self, _v) -> None:
                pass
        h = _Stderr()
        h.setFormatter(logging.Formatter("%(message)s"))
        lg.addHandler(h)
    lg.setLevel(logging.INFO)
    lg.propagate = False


def _forced(force: Optional[str], from_stage: Optional[str]) -> list[str]:
    """--force STAGE reruns that one stage; --from STAGE reruns it and every later stage."""
    out: list[str] = []
    try:
        if force:
            out.append(stage_name(force))
        if from_stage:
            out += list(stages_from(from_stage))
    except ValueError as e:
        raise typer.BadParameter(str(e))
    return out


def _body_run(body: str, runs: Optional[int], workers: Optional[int], store: bool = True) -> BodyRun:
    _enable_stage_log()
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
                   default_workers(workers), float(psutil.virtual_memory().available), sha256_file(ep),
                   use_store=store)


RunsOpt = typer.Option(None, "--runs", help="Monte Carlo runs (default from config/run.yaml)")
WorkersOpt = typer.Option(None, "--workers", help="worker processes (default: all cores)")
ForceOpt = typer.Option(None, "--force", help="rerun this one stage even if it is finished (simulate, or s5)")
FromOpt = typer.Option(None, "--from", help="rerun this stage and every later one (s5 = simulate onward)")


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
def s1_tiles(raster: Path = typer.Option(..., "--raster", help="6 km EPSG:6933 GeoTIFF (or folder) with a land_frac band"),
             plan: Optional[Path] = typer.Option(None, "--plan", help="the gee_export plan JSON, if bands are not named"),
             force: bool = typer.Option(False, "--force", help="rerun even if tiles.parquet is up to date")) -> None:
    """Land tiles of the 6 km grid -> data/interim/tiles.parquet. Prints the count against the plan's ~4 million."""
    from . import tiles as TL
    _enable_stage_log()
    rep = TL.run_stage(raster, data_dir("interim"), load_all()["run"], force, plan)
    tag = "WARN" if rep["far_off"] else "PASS"
    console.print(f"[{tag}] {rep['message']} -> data/interim/tiles.parquet" + (" (skipped: up to date)" if rep["skipped"] else ""))


@s2.command("earth")
def s2_earth(source: str = typer.Option("local", "--source", help="gee or local"),
             src: Optional[Path] = typer.Option(None, "--src", help="local: GeoTIFF or folder of 6 km rasters"),
             plan: Optional[Path] = typer.Option(None, "--plan", help="local: the gee_export `<name>_export_plan.json` that lists "
                                                 "the GeoTIFFs, if it is not in the --src folder"),
             add_solar: bool = typer.Option(False, "--add-solar", help="local: add sun_max_elev, sun_low_share, insol_annual "
                                            "computed from latitude only (earth/solar.py)"),
             verify: bool = typer.Option(False, "--verify", help="gee: check every collection id in the live catalog and stop"),
             bbox: Optional[str] = typer.Option(None, "--bbox", help="gee: lon_min,lat_min,lon_max,lat_max (default: global)"),
             name: str = typer.Option("gsop_earth", "--name", help="gee: export task prefix"),
             project: Optional[str] = typer.Option(None, "--project", help="gee: Cloud project id (or set GSOP_EE_PROJECT)"),
             dry_run: bool = typer.Option(False, "--dry-run", help="gee: print the export plan, start nothing")) -> None:
    """Earth features -> data/processed/earth_features_6km.parquet (+ grid.json, MANIFEST sha256)."""
    out = EARTH()
    if source == "gee":
        from .earth import gee_export
        from .earth import open_data as OD
        if verify:
            try:
                rows = gee_export.verify(project)
            except RuntimeError as e:
                console.print(f"[FAIL] {e}")
                raise typer.Exit(1)
            bad = [r for r in rows if not r["reachable"] or r.get("bands_missing")]
            for r in rows:
                console.print(f"[{'FAIL' if r in bad else 'PASS'}] {r['id']}: {r.get('error') or r.get('bands_missing') or 'ok'}")
            # typer.Exit is a RuntimeError, so it must never be raised inside a try that catches RuntimeError
            raise typer.Exit(1 if bad else 0)
        box = _parse_bbox(bbox)
        try:
            tasks = gee_export.run(box, name, project=project, dry_run=dry_run)
        except RuntimeError as e:
            console.print(f"[FAIL] {e}")
            raise typer.Exit(1)
        plan_file = data_dir("raw") / "earth" / f"{name}_export_plan.json"
        console.print(f"[PASS] {len(tasks)} export task(s) {'planned' if dry_run else 'started'}. Plan: {plan_file}")
        console.print("Download the GeoTIFFs from Drive. The loader names their bands from this plan, so either copy the plan "
                      "JSON into the same folder as the GeoTIFFs, or pass it with --plan:")
        console.print("  uv run gsop s2 earth --source local --src <folder> --plan <plan json> --add-solar")
        return
    from .earth.local_loaders import build_earth_table
    s = src or data_dir("raw") / "earth"
    df = build_earth_table(s, out, add_solar=add_solar, plan=plan)
    T.write_data_manifest(out.parent)
    console.print(f"[PASS] {len(df):,} tiles -> {out}; MANIFEST.json written (send it with the parquet and grid.json)")


@s2.command("open-data")
def s2_open_data(spec: Path = typer.Option(Path("config/open_data.yaml"), "--spec", help="YAML: dem and layers files"),
                 out: Path = typer.Option(None, "--out", help="output GeoTIFF (default data/raw/earth/earth_6km.tif)"),
                 bbox: Optional[str] = typer.Option(None, "--bbox", help="lon_min,lat_min,lon_max,lat_max (default: global)")) -> None:
    """Open-data fallback: resample downloaded rasters onto the 6 km grid. Then run `gsop s2 earth --source local`."""
    import yaml
    from .earth import open_data as OD
    cfg = load_all()
    sp = yaml.safe_load(Path(spec).read_text(encoding="utf-8"))
    box = _parse_bbox(bbox)
    dst = out or data_dir("raw") / "earth" / "earth_6km.tif"
    rep = OD.build_rasters(sp, cfg["features"]["operator"], dst, box)
    console.print(f"[PASS] {dst} with bands {rep['bands']}")
    for c, why in rep["left_out"].items():
        console.print(f"[WARN] left out {c}: {why}")
    console.print(f"Next: uv run gsop s2 earth --source local --src {dst}")


@s2.command("targets")
def s2_targets(body: str = BodyOpt, dem: Optional[Path] = typer.Option(None, "--dem", help="DEM GeoTIFF (LOLA or MOLA)"),
               psr: Optional[Path] = typer.Option(None, "--psr", help="moon: PSR raster (non-zero = permanently shadowed)")) -> None:
    """Target profiles -> data/processed/targets_{body}.parquet."""
    from .targets import common, mars, moon
    cfg = load_all()
    if _check_body(body) == "moon":
        rows = moon.build(cfg, dem, psr)
    else:
        if psr:
            raise typer.BadParameter("--psr is for the Moon only")
        rows = mars.build(cfg, dem)
    df = common.write_profile(rows, data_dir("processed") / f"targets_{body}.parquet")
    un = df[df["unavailable"]].groupby("target")["col"].apply(list).to_dict()
    console.print(f"[PASS] {df['target'].nunique()} targets written")
    for t, c in un.items():
        console.print(f"[WARN] {t}: unavailable {c}")


def _stage_cmd(group: typer.Typer, cmd: str, stages: tuple[str, ...], doc: str) -> None:
    @group.command(cmd, help=doc)
    def _run(body: str = BodyOpt, runs: Optional[int] = RunsOpt, workers: Optional[int] = WorkersOpt,
             force: bool = typer.Option(False, "--force", help="rerun this stage even if it is finished")) -> None:
        br = _body_run(body, runs, workers)
        br.run(stages, force=[stages[-1]] if force else [])
        console.print(f"[PASS] {doc} done for {body}")


_stage_cmd(s3, "gates", ("gates",), "gates: passed/rejected tables with reasons")
_stage_cmd(s4, "score", ("gates", "score"), "base similarity 0-100 per target x profile")
_stage_cmd(s5, "simulate", ("gates", "simulate"), "Monte Carlo simulation")
_stage_cmd(s6, "ml", ("ml",), "ML second opinion")
_stage_cmd(s7, "validate", ("validate",), "validation against known sites")
_stage_cmd(s8, "export", ("export",), "export results for the site")
_stage_cmd(s9, "discover", ("discover",), "discovery: robust and novel candidate list")


@app.command()
def run(body: str = BodyOpt, runs: Optional[int] = RunsOpt, workers: Optional[int] = WorkersOpt,
        force: Optional[str] = ForceOpt, from_stage: Optional[str] = FromOpt) -> None:
    """Runs s3..s7 (+s8, s9) in order, resumable. Writes results/<body>/run_meta.json.
    Finished stages are skipped when their inputs, config and code are unchanged; each skip and rerun is logged."""
    forced = _forced(force, from_stage)
    br = _body_run(body, runs, workers)
    br.run(STAGES, force=forced)
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
def check_operators(project: Optional[str] = typer.Option(None, "--project", help="Earth Engine Cloud project id"),
                    lon: Optional[float] = typer.Option(None, "--lon", help="window centre longitude (default: config/run.yaml operator_check)"),
                    lat: Optional[float] = typer.Option(None, "--lat", help="window centre latitude"),
                    tiles: Optional[int] = typer.Option(None, "--tiles", help="window edge in 6 km tiles")) -> None:
    """Earth Engine vs numpy terrain operators on one small window; writes results/operator_check.json. Needs a login."""
    from .earth import check_operators as CO
    if (lon is None) != (lat is None):
        raise typer.BadParameter("--lon and --lat go together: give both or neither")
    centre = (lon, lat) if lon is not None else None
    try:
        rep = CO.run(centre, tiles, project=project, out=results_dir() / "operator_check.json")
    except RuntimeError as e:
        console.print(f"[FAIL] {e}")
        raise typer.Exit(1)
    for k, r in rep["features"].items():
        console.print(f"[{'PASS' if r['ok'] else 'FAIL'}] {k}: relative difference {r['rel_diff']:.3%} over {r['n']} tiles")
    raise typer.Exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    app()
