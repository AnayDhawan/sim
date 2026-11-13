"""Stage orchestration for one body: s3 gates, s4 score, s5 simulate, s6 ml, s7 validate, s8 export, s9 discover."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import discover as D
from . import gates as G
from . import ml as ML
from . import pipeline as P
from . import validate as V
from . import weights as W
from .export import export_body
from .provenance import StageStore, config_hash, read_json, run_meta, write_json

STAGES = ("gates", "score", "simulate", "ml", "validate", "discover", "export")


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

    def _stage(self, stage: str, key: str, inputs: dict[str, str], fn) -> bool:
        """Run fn unless a marker with identical inputs exists. Returns True if it ran."""
        sid = f"{stage}__{key}"
        inputs = {**inputs, "earth": self.earth_hash, "runs": str(self.runs)}
        if self.store and self.store.is_done(sid, self.cfg_hash, inputs):
            return False
        t0 = time.perf_counter()
        fn()
        dt = time.perf_counter() - t0
        self.timings[sid] = dt
        if self.store:
            self.store.mark(sid, self.cfg_hash, inputs, dt)
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
                g[["tile_id", "code"]].to_parquet(self.res_dir / f"gates__{prof}.parquet", index=False)
                write_json(self.res_dir / f"gates__{prof}.json", {
                    "profile": prof, "n_tiles": int(len(g)), "n_passed": int(g["passed"].sum()),
                    "rejected_by_reason": {k: int(v) for k, v in g["reason"].value_counts().items() if k != "ok"}})
            self._stage("gates", prof, {}, go)

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

                def go(t=t, prof=prof, name=name):
                    try:
                        job = self.job(t, prof)
                    except P.UnavailableColumns as e:
                        self.unscored[name] = str(e)
                        write_json(self.res_dir / name / "unscored.json", {"reason": str(e)})
                        return
                    self.summaries[name] = P.run_job(job, self.cfg, self.res_dir / name, self.runs, self.workers,
                                                     self.work_dir, self.free_bytes, with_mc=with_mc)
                if not self._stage(stage, name, {"target": th}, go):
                    sp = self.res_dir / name / "summary.json"
                    if sp.exists():
                        self.summaries[name] = read_json(sp)

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
            self._stage("ml", name, {}, go)

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
        self._stage("validate", "body", {}, go)

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
                d.to_json(self.res_dir / name / "discovery.json", orient="records", indent=1)
            self._stage("discover", name, {}, go)

    # ------------------------------------------------------------------ s8
    def s8_export(self) -> None:
        for name in self.summaries:
            sp = self.res_dir / name / "summary.json"
            if sp.exists():
                self.summaries[name] = read_json(sp)
        export_body(self.body, self.res_dir, self.cfg["ledger"], self.summaries, self.unscored, list(self.profiles))

    # ------------------------------------------------------------------ all
    def run(self, stages: tuple[str, ...] = STAGES) -> None:
        t0 = time.perf_counter()
        fns = {"gates": self.s3_gates, "score": self.s4_score, "simulate": self.s5_simulate, "ml": self.s6_ml,
               "validate": self.s7_validate, "discover": self.s9_discover, "export": self.s8_export}
        for s in stages:
            fns[s]()
        write_json(self.res_dir / "run_meta.json", run_meta(
            self.cfg_hash, {"master_seed": self.cfg["run"]["master_seed"]},
            {**self.timings, "total": time.perf_counter() - t0},
            {"body": self.body, "runs": self.runs, "workers": self.workers, "earth_hash": self.earth_hash,
             "unscored": self.unscored, "stages": list(stages)}))
