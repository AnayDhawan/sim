"""Stage orchestration for one body: s3 gates, s4 score, s5 simulate, s6 ml, s7 validate, s8 export, s9 discover."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from . import discover as D
from . import gates as G
from . import ml as ML
from . import pipeline as P
from . import validate as V
from . import weights as W
from .export import export_body
from .provenance import StageStore, atomic_to_parquet, atomic_write_text, config_hash, read_json, run_meta, write_json

log = logging.getLogger("gsop.runner")

STAGES = ("gates", "score", "simulate", "ml", "validate", "discover", "export")
# CLI numbering (`gsop s3 ... s9`). `--from s5` reruns every stage numbered 5 or more.
STAGE_NUMBER = {"gates": 3, "score": 4, "simulate": 5, "ml": 6, "validate": 7, "export": 8, "discover": 9}
# Stages whose result depends on the number of Monte Carlo runs.
RUN_DEPENDENT = ("simulate", "ml", "discover")
MC_RUN_KEYS = ("master_seed", "batch_runs", "top_fracs", "robust", "candidates", "convergence_checkpoints")


def stage_name(label: str) -> str:
    """'simulate' or 's5' -> 'simulate'."""
    label = label.strip().lower()
    if label in STAGE_NUMBER:
        return label
    by_number = {f"s{n}": s for s, n in STAGE_NUMBER.items()}
    if label in by_number:
        return by_number[label]
    raise ValueError(f"unknown stage {label!r}; use one of {', '.join(STAGE_NUMBER)} or s3..s9")


def stages_from(label: str) -> tuple[str, ...]:
    """Every stage numbered like `label` or later, in run order."""
    n = STAGE_NUMBER[stage_name(label)]
    return tuple(s for s in STAGES if STAGE_NUMBER[s] >= n)


def hash_frame(df: pd.DataFrame) -> str:
    return config_hash({"shape": list(df.shape), "cols": list(df.columns),
                        "h": int(pd.util.hash_pandas_object(df.head(20000), index=False).sum() % (1 << 62))})


class BodyRun:
    def __init__(self, body: str, cfg: dict[str, Any], earth: pd.DataFrame, tprofs: dict[str, Any], res_dir: Path,
                 work_dir: Path, runs: int, workers: int, free_bytes: float, earth_hash: str, use_store: bool = True):
        self.body, self.cfg, self.earth, self.tprofs = body, cfg, earth, tprofs
        self.res_dir, self.work_dir = Path(res_dir), Path(work_dir)
        self.res_dir.mkdir(parents=True, exist_ok=True)
        self.runs, self.workers, self.free_bytes = runs, workers, free_bytes
        self.earth_hash = earth_hash
        self.store = StageStore(self.res_dir) if use_store else None
        self.profiles = cfg["purposes"]["profiles"][body]
        self.cfg_hash = config_hash({k: cfg[k] for k in cfg})
        self._gates: dict[str, pd.DataFrame] = {}
        self.summaries: dict[str, dict[str, Any]] = {}
        self.timings: dict[str, float] = {}
        self.events: list[dict[str, str]] = []       # one row per stage job: run or skip, and why
        self.forced: set[str] = set()
        self.targets, self.unscored = self._split_targets()
        for sp in sorted(self.res_dir.glob("*/summary.json")):      # lets s6 to s9 run as separate commands
            self.summaries[sp.parent.name] = read_json(sp)

    # ------------------------------------------------------------------ targets
    def _split_targets(self) -> tuple[list[str], dict[str, str]]:
        ok, bad = [], {}
        for name, t in self.cfg["targets"][self.body].items():
            if t.get("lat") is None:
                bad[name] = f"unscored: no target data ({t.get('status', 'no coordinates')})"
            elif name not in self.tprofs:
                bad[name] = "unscored: no target profile (run `gsop s2 targets`)"
            else:
                ok.append(name)
        return ok, bad

    # ------------------------------------------------------------------ stage bookkeeping
    def stage_config(self, stage: str) -> dict[str, Any]:
        """The part of the config a stage's output depends on. Upstream stages' config reaches a stage through the
        upstream marker hash (`upstream` in `_stage`), so each entry lists only what the stage adds itself."""
        c, b = self.cfg, self.body
        drop = c["run"].get("drop_columns") or []
        score = {"weights": c["weights"][b], "alt_weight_sets": c["weights"]["alt_weight_sets"][b],
                 "purposes": c["purposes"],
                 "measurement_uncertainty": (c["features"].get("measurement_uncertainty") or {}).get(b),
                 "earth_uncertainty": c["features"].get("earth_uncertainty"), "gates": c["gates"], "drop_columns": drop}
        mc = {k: c["run"].get(k) for k in MC_RUN_KEYS}
        return {
            "gates": {"gates": c["gates"], "purposes": c["purposes"], "drop_columns": drop,
                      "columns": {f: v["columns"] for f, v in c["weights"][b].items()}},
            "score": score,
            "simulate": {**score, "mc": mc},
            "ml": {"known_sites": c["known_sites"]["primary"], "ml": c["run"]["ml"], "master_seed": c["run"]["master_seed"]},
            "validate": {"known_sites": c["known_sites"], "site_match_radius_km": c["run"]["site_match_radius_km"]},
            "discover": {"known_sites": c["known_sites"], "discovery": c["run"]["discovery"], "gates": c["gates"]},
        }[stage]

    def _key_of(self, *sids: str) -> str:
        """Marker identity of the first finished stage among `sids` (a stage can be satisfied by a later one)."""
        if not self.store:
            return "nostore"
        for sid in sids:
            if self.store.read(sid):
                return self.store.key_hash(sid)
        return "missing"

    def _inputs(self, stage: str, inputs: dict[str, str], upstream: dict[str, str] | None) -> dict[str, str]:
        out = {**inputs, "earth": self.earth_hash, **(upstream or {})}
        if stage in RUN_DEPENDENT:
            out["runs"] = str(self.runs)
        return out

    def _stage(self, stage: str, key: str, inputs: dict[str, str], fn: Callable[[], None],
               outputs: Iterable[Path] = (), upstream: dict[str, str] | None = None) -> bool:
        """Run fn unless the stage is finished with identical inputs. Returns True if it ran.
        `outputs`: files the stage writes (recorded in the marker once they exist; a deleted output reruns the stage).
        `upstream`: name -> identity of the stage markers this one reads from."""
        sid = f"{stage}__{key}"
        inputs = self._inputs(stage, inputs, upstream)
        cfg_part = config_hash(self.stage_config(stage))
        if stage in self.forced:
            reason = "forced"
        elif self.store:
            done, reason = self.store.check(sid, cfg_part, inputs)
            if done:
                self.events.append({"stage": sid, "action": "skip", "reason": reason})
                log.info("[skip] %s: %s", sid, reason)
                return False
        else:
            reason = "no stage store"
        self.events.append({"stage": sid, "action": "run", "reason": reason})
        log.info("[run]  %s: %s", sid, reason)
        if self.store:
            self.store.invalidate(sid)          # a crash from here on must not leave a marker that says "done"
        t0 = time.perf_counter()
        fn()
        dt = time.perf_counter() - t0
        self.timings[sid] = dt
        if self.store:
            self.store.mark(sid, cfg_part, inputs, dt, [p for p in outputs if Path(p).exists()])
        return True

    # ------------------------------------------------------------------ s3
    def gate_table(self, profile: str, columns: list[str]) -> pd.DataFrame:
        if profile not in self._gates:
            expr = G.extra_gate_expr(self.cfg["purposes"], profile, self.body)
            self._gates[profile] = G.apply_gates(self.earth, self.cfg["gates"], columns, expr)
        return self._gates[profile]

    def _columns(self) -> list[str]:
        drop = list(self.cfg["run"].get("drop_columns") or [])
        bc = P.active_body_cfg(self.cfg["weights"][self.body], drop)
        return list(dict.fromkeys(c for f in bc.values() for c in f["columns"]))

    def s3_gates(self) -> None:
        cols = self._columns()
        for prof in self.profiles:
            def go(prof=prof):
                g = self.gate_table(prof, cols)
                atomic_to_parquet(g[["tile_id", "code"]], self.res_dir / f"gates__{prof}.parquet", index=False)
                write_json(self.res_dir / f"gates__{prof}.json", {
                    "profile": prof, "n_tiles": int(len(g)), "n_passed": int(g["passed"].sum()),
                    "rejected_by_reason": {k: int(v) for k, v in g["reason"].value_counts().items() if k != "ok"}})
            self._stage("gates", prof, {}, go, [self.res_dir / f"gates__{prof}.parquet",
                                                self.res_dir / f"gates__{prof}.json"])

    # ------------------------------------------------------------------ s4 / s5
    def job(self, target: str, profile: str) -> P.Job:
        return P.prepare_job(self.body, target, profile, self.cfg, self.earth, self.tprofs[target],
                             self.gate_table(profile, self._columns()))

    def _score(self, with_mc: bool) -> None:
        for t in self.targets:
            for prof in self.profiles:
                name = f"{t}__{prof}"
                stage = "simulate" if with_mc else "score"
                th = config_hash(self.tprofs[t]["cols"])
                d = self.res_dir / name

                def go(t=t, prof=prof, name=name):
                    try:
                        job = self.job(t, prof)
                    except P.UnavailableColumns as e:
                        self.unscored[name] = str(e)
                        write_json(self.res_dir / name / "unscored.json", {"reason": str(e)})
                        return
                    self.summaries[name] = P.run_job(job, self.cfg, self.res_dir / name, self.runs, self.workers,
                                                     self.work_dir, self.free_bytes, with_mc=with_mc)
                outs = [d / "unscored.json", d / "base_scores.parquet", d / "summary.json"]
                if with_mc:
                    outs += [d / "mc_summary.parquet", d / "convergence.json"]
                up = {"gates": self._key_of(f"gates__{prof}")}
                if (not with_mc and self.store and "score" not in self.forced and
                        self.store.check(f"simulate__{name}", config_hash(self.stage_config("simulate")),
                                         self._inputs("simulate", {"target": th}, up))[0]):
                    # a finished simulate stage already wrote everything the score stage writes
                    self.events.append({"stage": f"score__{name}", "action": "skip",
                                        "reason": "covered by a finished simulate stage"})
                    log.info("[skip] score__%s: covered by a finished simulate stage", name)
                    ran = False
                else:
                    ran = self._stage(stage, name, {"target": th}, go, outs, up)
                if ran and not with_mc and self.store:
                    # the score stage rewrites summary.json without the Monte Carlo fields, so the simulate stage
                    # for this job has to run again to put them back
                    self.store.invalidate(f"simulate__{name}")
                if not ran:
                    sp = self.res_dir / name / "summary.json"
                    if sp.exists():
                        self.summaries[name] = read_json(sp)
                    elif (self.res_dir / name / "unscored.json").exists():
                        self.unscored[name] = read_json(self.res_dir / name / "unscored.json")["reason"]

    def s4_score(self) -> None:
        self._score(False)

    def s5_simulate(self) -> None:
        self._score(True)

    # ------------------------------------------------------------------ s6
    def s6_ml(self) -> None:
        ks = self.cfg["known_sites"]
        sites = {n: s for n, s in ks["primary"].items() if self.body in s["bodies"]}
        for name in list(self.summaries):
            if not (self.res_dir / name / "mc_summary.parquet").exists():
                continue
            t, prof = name.split("__")

            def go(t=t, prof=prof, name=name):
                job = self.job(t, prof)
                rows = job.gated_rows
                score = pd.read_parquet(self.res_dir / name / "base_scores.parquet")["score"].to_numpy()
                mc = pd.read_parquet(self.res_dir / name / "mc_summary.parquet")
                robust_tiles = mc.loc[mc["robust"], "tile_id"].to_numpy()
                tile_row = pd.Series(np.arange(len(rows)), index=self.earth["tile_id"].to_numpy()[rows])
                robust_idx = tile_row.reindex(robust_tiles).dropna().astype(int).to_numpy()
                out = ML.run_ml(job.X, job.columns, self.earth["lat"].to_numpy()[rows],
                                self.earth["lon"].to_numpy()[rows], score, robust_idx, sites, self.cfg["run"]["ml"],
                                seed=int(self.cfg["run"]["master_seed"]))
                write_json(self.res_dir / name / "ml.json", out)
            self._stage("ml", name, {}, go, [self.res_dir / name / "ml.json"],
                        {"simulate": self._key_of(f"simulate__{name}")})

    # ------------------------------------------------------------------ s7
    def s7_validate(self) -> None:
        names = [f"{t}__base" for t in self.targets if (self.res_dir / f"{t}__base" / "base_scores.parquet").exists()]
        if not names:
            return
        warn = V.unconfirmed_sites(self.cfg["known_sites"])
        print(f"WARNING: {len(warn)} known-site coordinates are unconfirmed (config/known_sites.yaml): "
              f"{', '.join(warn)}. Validation results are provisional.")

        def go():
            path = self.res_dir / "validation.json"
            if path.exists():
                path.unlink()
            scores = {n.split("__")[0]: pd.read_parquet(self.res_dir / n / "base_scores.parquet").set_index("tile_id")["score"]
                      for n in names}
            gate = self.gate_table("base", self._columns())
            V.validate_body(self.body, self.cfg["known_sites"], float(self.cfg["run"]["site_match_radius_km"]),
                            self.earth, {t: gate for t in scores}, scores, path)
        up = {"gates": self._key_of("gates__base")}
        up.update({n: self._key_of(f"score__{n}", f"simulate__{n}") for n in names})
        self._stage("validate", "body", {}, go, [self.res_dir / "validation.json"], up)

    # ------------------------------------------------------------------ s9
    def s9_discover(self) -> None:
        gm = D.gate_margin_table(self.earth, self.cfg["gates"])
        for name, s in self.summaries.items():
            if not (self.res_dir / name / "mc_summary.parquet").exists():
                continue

            def go(name=name, s=s):
                mc = pd.read_parquet(self.res_dir / name / "mc_summary.parquet")
                t, prof = name.split("__")
                job = self.job(t, prof)
                fam = P.fam_arrays(job)
                tid = self.earth["tile_id"].to_numpy()[job.gated_rows]
                contrib = pd.DataFrame({f: job.profile_weights[f] * a for f, a in fam.items()}, index=tid)
                d = D.discover(mc, self.cfg["known_sites"], self.body, float(self.cfg["run"]["discovery"]["min_distance_km"]),
                               int(self.cfg["run"]["discovery"]["top_n"]), contrib, gm)
                atomic_write_text(self.res_dir / name / "discovery.json", d.to_json(orient="records", indent=1))
            self._stage("discover", name, {}, go, [self.res_dir / name / "discovery.json"],
                        {"simulate": self._key_of(f"simulate__{name}")})

    # ------------------------------------------------------------------ s8
    def s8_export(self) -> None:
        for name in self.summaries:
            sp = self.res_dir / name / "summary.json"
            if sp.exists():
                self.summaries[name] = read_json(sp)
        export_body(self.body, self.res_dir, self.cfg["ledger"], self.summaries, self.unscored, list(self.profiles))

    # ------------------------------------------------------------------ all
    def run(self, stages: tuple[str, ...] = STAGES, force: Iterable[str] = ()) -> None:
        """Run `stages` in the order given. `force`: stage names (or s3..s9) rerun even if finished."""
        self.forced = {stage_name(f) for f in force}
        t0 = time.perf_counter()
        fns = {"gates": self.s3_gates, "score": self.s4_score, "simulate": self.s5_simulate, "ml": self.s6_ml,
               "validate": self.s7_validate, "discover": self.s9_discover, "export": self.s8_export}
        for s in stages:
            fns[s]()
        write_json(self.res_dir / "run_meta.json", run_meta(
            self.cfg_hash, {"master_seed": self.cfg["run"]["master_seed"]},
            {**self.timings, "total": time.perf_counter() - t0},
            {"body": self.body, "runs": self.runs, "workers": self.workers, "earth_hash": self.earth_hash,
             "unscored": self.unscored, "stages": list(stages), "stage_log": self.events}))
