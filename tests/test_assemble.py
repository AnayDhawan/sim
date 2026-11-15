"""Earth assembler (earth/assemble.py, SPEC 3e) on small synthetic GeoTIFFs, plus a check on the real downloads if present."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import Affine
from typer.testing import CliRunner

from gsop.earth import assemble as A
from gsop.grid import Grid

G = Grid()
NAN = np.nan


def _tif(path: Path, bands: list[np.ndarray], ix0: int, iy0: int, names: list[str] | None, nodata=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    h, w = bands[0].shape
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=len(bands), dtype="float32", crs="EPSG:6933",
                       nodata=nodata, transform=Affine(6000.0, 0, G.x0 + ix0 * 6000.0, 0, -6000.0, G.y_top - iy0 * 6000.0)) as ds:
        for i, a in enumerate(bands, 1):
            ds.write(np.asarray(a, dtype="float32"), i)
            if names:
                ds.set_band_description(i, names[i - 1])


def gate(path, ix0, iy0, land, water=0.0, ndvi=0.1, built=0.0, names=True):
    land = np.asarray(land, dtype=float)
    f = lambda v: np.broadcast_to(np.asarray(v, dtype=float), land.shape)  # noqa: E731
    _tif(path, [land, f(water), f(ndvi), f(built)], ix0, iy0, A.GATE_BANDS if names else None)


def terrain(path, ix0, iy0, slope, names=True, nodata=None):
    s = np.asarray(slope, dtype=float)
    bands = [s, s * 2, s * 100, s * 10 + 500, s / 10, s]       # slope_med, slope_p90, relief, elev_mean, rough_a, rough_b
    _tif(path, bands, ix0, iy0, A.TERRAIN_BANDS if names else None, nodata)


ROW_MID = 1000                  # about 9N, SRTM country
ROW_NORTH = 100                 # about 66N, GLO30 country
ROW_SOUTH = 2300                # about 61S, south of SRTM


def _row(df, ix, iy):
    r = df[(df.ix == ix) & (df.iy == iy)]
    assert len(r) == 1, (ix, iy, len(r))
    return r.iloc[0]


def test_gate_placement_land_threshold_and_tile_id(tmp_path):
    land = np.array([[1.0, 0.4, 0.5], [NAN, 1.0, 1.0]])
    gate(tmp_path / "g" / "gate_6km_r01_c02.tif", 3000, ROW_MID, land)
    df, rep = A.assemble(tmp_path / "g", None, None, add_solar=False)
    assert len(df) == 4 and rep["land_tiles"] == 4                       # 0.4 and NaN are not land, 0.5 is
    r = _row(df, 3002, ROW_MID)
    assert r.tile_id == ROW_MID * G.ncols + 3002 == G.tile_id(3002, ROW_MID)
    assert df["tile_id"].is_monotonic_increasing
    lon, lat = G.centre_lonlat(3002, ROW_MID)
    assert r.lon == pytest.approx(float(lon)) and r.lat == pytest.approx(float(lat))
    assert df[A.TERRAIN_BANDS].isna().all().all()                        # no terrain folder: NaN terrain
    assert rep["tiles_with_nan_terrain"] == 4 and rep["share_of_land_tiles_with_terrain"] == 0.0


def test_edge_overlap_finite_beats_missing_and_equal_values_are_fine(tmp_path):
    gate(tmp_path / "g" / "gate_6km_r01_c00.tif", 3000, ROW_MID, np.ones((2, 6)))
    # Earth Engine style: each chunk has one extra edge column that the neighbour also covers
    a = np.array([[1.0, 2.0, 3.0, NAN], [1.0, 2.0, 3.0, NAN]])           # columns 3000..3003, last one empty
    b = np.array([[4.0, 5.0, 6.0], [4.0, 5.0, 6.0]])                     # columns 3003..3005
    terrain(tmp_path / "t" / "terrain90_r00_c00.tif", 3000, ROW_MID, a)
    terrain(tmp_path / "t" / "terrain90_r00_c01.tif", 3003, ROW_MID, b)
    # a Drive duplicate with identical values is not double counted
    terrain(tmp_path / "t" / "terrain90_r00_c01 (1).tif", 3003, ROW_MID, b)
    df, rep = A.assemble(tmp_path / "g", tmp_path / "t", None, add_solar=False)
    assert list(df[df.iy == ROW_MID].sort_values("ix")["slope_med"]) == [1, 2, 3, 4, 5, 6]
    assert rep["tiles_with_complete_terrain"] == 12 and rep["tiles_terrain_from_srtm"] == 12 and len(df) == 12


def test_overlap_with_different_values_is_an_error(tmp_path):
    gate(tmp_path / "g" / "gate_6km_r01_c00.tif", 3000, ROW_MID, np.ones((1, 4)))
    terrain(tmp_path / "t" / "terrain90_r00_c00.tif", 3000, ROW_MID, [[1.0, 2.0, 3.0]])
    terrain(tmp_path / "t" / "terrain90_r00_c01.tif", 3002, ROW_MID, [[9.0, 4.0]])
    with pytest.raises(A.OverlapError, match="terrain90_r00_c0.*apart"):
        A.assemble(tmp_path / "g", tmp_path / "t", None, add_solar=False)
    # within the tolerance is the same value
    terrain(tmp_path / "t" / "terrain90_r00_c01.tif", 3002, ROW_MID, [[3.0 + 1e-7, 4.0]])
    df, _ = A.assemble(tmp_path / "g", tmp_path / "t", None, add_solar=False)
    assert df["slope_med"].notna().all()


def test_small_edge_disagreement_takes_the_interior_file(tmp_path):
    """Two chunks of one product that differ by a few percent on a shared border tile (less context at a file edge):
    the file where the tile is farther from its edge wins. A larger disagreement still stops the build."""
    gate(tmp_path / "g" / "gate_6km_r01_c00.tif", 3000, ROW_MID, np.ones((3, 6)))
    a = np.full((3, 3), 3.00)                         # columns 3000..3002
    b = np.full((3, 5), 3.10)                         # columns 3001..3005
    terrain(tmp_path / "t" / "terrain90_r00_c00.tif", 3000, ROW_MID, a)
    terrain(tmp_path / "t" / "terrain90_r00_c01.tif", 3001, ROW_MID, b)
    df, rep = A.assemble(tmp_path / "g", tmp_path / "t", None, add_solar=False)
    mid = df[df.iy == ROW_MID + 1].set_index("ix")["slope_med"]
    assert mid[3001] == pytest.approx(3.00)           # interior of file A (distance 1), edge of file B (distance 0)
    assert mid[3002] == pytest.approx(3.10)           # edge of file A (distance 0), interior of file B (distance 1)
    assert rep["srtm"]["edge_overlap_tiles_resolved"] >= 2
    terrain(tmp_path / "t" / "terrain90_r00_c01.tif", 3001, ROW_MID, np.full((3, 5), 12.0))     # far more than 50 percent apart
    with pytest.raises(A.OverlapError, match="apart"):
        A.assemble(tmp_path / "g", tmp_path / "t", None, add_solar=False)


def test_split_retry_pieces_without_parent(tmp_path):
    gate(tmp_path / "g" / "gate_6km_r01_c00.tif", 3000, ROW_MID, np.ones((4, 4)))
    # the parent terrain90_r03_c07 failed and has no file; its two halves are _r0 (top rows) and _r1 (bottom rows)
    terrain(tmp_path / "t" / "terrain90_r03_c07_r0.tif", 3000, ROW_MID, np.full((2, 4), 1.0))
    terrain(tmp_path / "t" / "terrain90_r03_c07_r1.tif", 3000, ROW_MID + 2, np.full((2, 4), 2.0))
    df, rep = A.assemble(tmp_path / "g", tmp_path / "t", None, add_solar=False)
    assert rep["srtm"]["files"] == 2 and rep["tiles_with_complete_terrain"] == 16
    assert (df[df.iy < ROW_MID + 2]["slope_med"] == 1.0).all() and (df[df.iy >= ROW_MID + 2]["slope_med"] == 2.0).all()


def test_split_gate_pieces_and_names(tmp_path):
    # top-row chunk split in pieces _p0_s0, _p0_s1, _p1: placed by transform, not by name
    gate(tmp_path / "g" / "gate_6km_r00_c00_p0_s0.tif", 10, ROW_NORTH, np.ones((1, 3)))
    gate(tmp_path / "g" / "gate_6km_r00_c00_p0_s1.tif", 10, ROW_NORTH + 1, np.ones((1, 3)))
    gate(tmp_path / "g" / "gate_6km_r00_c00_p1.tif", 10, ROW_NORTH + 2, np.ones((1, 3)))
    gate(tmp_path / "g" / "notes.tif", 10, ROW_NORTH + 3, np.ones((1, 3)))       # not a gate name: skipped, reported
    df, rep = A.assemble(tmp_path / "g", None, None, add_solar=False)
    assert len(df) == 9 and rep["gate"]["files"] == 3 and rep["gate"]["skipped_names"] == ["notes.tif"]


def test_nodata_9999_nan_and_declared_nodata_are_missing(tmp_path):
    gate(tmp_path / "g" / "gate_6km_r01_c00.tif", 3000, ROW_MID, np.ones((1, 4)), ndvi=[[0.1, NAN, 0.1, 0.1]])
    terrain(tmp_path / "t" / "terrain90_r00_c00.tif", 3000, ROW_MID, [[-9999.0, NAN, 7.0, 3.0]])
    s = np.array([[1.0, 1.0, 1.0, -32768.0]])
    _tif(tmp_path / "t2" / "terrain90_r00_c00.tif", [s] * 6, 3000, ROW_MID, A.TERRAIN_BANDS, nodata=-32768.0)
    df, rep = A.assemble(tmp_path / "g", tmp_path / "t", None, add_solar=False)
    v = df.sort_values("ix")["slope_med"].to_numpy()
    assert np.isnan(v[0]) and np.isnan(v[1]) and v[2] == 7.0                # -9999 * 2 etc. never leak in
    assert np.isnan(df.sort_values("ix")["ndvi_median"].to_numpy()[1])
    assert rep["land_tiles_with_all_gate_layers"] == 3
    df2, _ = A.assemble(tmp_path / "g", tmp_path / "t2", None, add_solar=False)
    assert np.isnan(df2.sort_values("ix")["slope_med"].to_numpy()[3])


def test_source_precedence_north_south_and_fallback(tmp_path):
    for iy in (ROW_MID, ROW_NORTH, ROW_SOUTH):
        gate(tmp_path / "g" / f"gate_6km_r00_c{iy}.tif", 500, iy, np.ones((1, 2)))
    # both sources everywhere at column 500; only one source at column 501
    terrain(tmp_path / "s" / "terrain90_r00_c00.tif", 500, ROW_MID, [[1.0, 1.0]])
    terrain(tmp_path / "s" / "terrain90_r00_c01.tif", 500, ROW_NORTH, [[1.0, 1.0]])     # SRTM margin data north of 60N
    terrain(tmp_path / "h" / "terrain90_stage1_x_r00_c00.tif", 500, ROW_MID, [[2.0, NAN]])
    terrain(tmp_path / "h" / "terrain90_stage1_x_r00_c01.tif", 500, ROW_NORTH, [[2.0, NAN]])
    terrain(tmp_path / "h" / "terrain90_stage1_mcmurdo_r00_c00.tif", 500, ROW_SOUTH, [[2.0, 2.0]])
    df, rep = A.assemble(tmp_path / "g", tmp_path / "s", tmp_path / "h", add_solar=False)
    assert _row(df, 500, ROW_MID).slope_med == 1.0          # at or below 60N: SRTM wins
    assert _row(df, 500, ROW_NORTH).slope_med == 2.0        # above 60N: GLO30 wins
    assert _row(df, 501, ROW_NORTH).slope_med == 1.0        # above 60N, GLO30 missing: SRTM fallback
    assert _row(df, 500, ROW_SOUTH).slope_med == 2.0        # south of 56S only GLO30
    assert rep["tiles_in_both_sources"] == 2 and rep["tiles_terrain_from_glo30"] == 3 and rep["tiles_terrain_from_srtm"] == 3


def test_band_descriptions_must_match_and_missing_ones_use_the_export_order(tmp_path):
    gate(tmp_path / "g" / "gate_6km_r01_c00.tif", 3000, ROW_MID, np.ones((1, 2)), names=False)
    terrain(tmp_path / "t" / "terrain90_r00_c00.tif", 3000, ROW_MID, [[3.0, 4.0]], names=False)
    df, _ = A.assemble(tmp_path / "g", tmp_path / "t", None, add_solar=False)
    assert list(df["relief"]) == [300.0, 400.0] and list(df["elev_mean"]) == [530.0, 540.0]
    _tif(tmp_path / "bad" / "terrain90_r00_c00.tif", [np.ones((1, 2))] * 6, 3000, ROW_MID,
         ["slope_p90", "slope_med", "relief", "elev_mean", "rough_a", "rough_b"])
    with pytest.raises(ValueError, match="differ from the expected order"):
        A.assemble(tmp_path / "g", tmp_path / "bad", None, add_solar=False)


EXPECTED_COLUMNS = ["tile_id", "ix", "iy", "lon", "lat", "water_ice_frac", "ndvi_median", "built_crop_frac", "slope_med",
                    "slope_p90", "relief", "elev_mean", "rough_a", "rough_b", "sun_max_elev", "sun_low_share",
                    "insol_annual", "air_density"]


def test_full_schema_gates_cli_manifest_and_verify_data(tmp_path, monkeypatch):
    import gsop.cli as cli
    from gsop.config import load_all
    from gsop.gates import CODE, apply_gates

    land = np.ones((3, 4))
    land[0, 0] = 0.2
    gate(tmp_path / "g" / "gate_6km_r01_c00.tif", 3000, ROW_MID, land, ndvi=[[0.1, 0.1, 0.5, 0.1]] * 3)
    terrain(tmp_path / "t" / "terrain90_r00_c00.tif", 3000, ROW_MID, np.where(np.arange(12).reshape(3, 4) == 11, NAN, 1.0))
    proc = tmp_path / "data" / "processed"
    monkeypatch.setattr(cli, "data_dir", lambda sub: tmp_path / "data" / sub)
    r = CliRunner().invoke(cli.app, ["s2", "assemble", "--gate", str(tmp_path / "g"), "--terrain", str(tmp_path / "t")])
    assert r.exit_code == 0, r.output
    assert "land tiles with complete terrain 10" in " ".join(r.output.split())
    for f in ("earth_features_6km.parquet", "grid.json", "earth_coverage.json", "MANIFEST.json"):
        assert (proc / f).exists(), f
    df = pd.read_parquet(proc / "earth_features_6km.parquet")
    assert list(df.columns) == EXPECTED_COLUMNS and len(df) == 11
    assert df["tile_id"].dtype == np.int64 and df["slope_med"].dtype == np.float32
    assert df[["sun_max_elev", "insol_annual"]].notna().all().all()
    assert df["air_density"].isna().sum() == 1                            # the tile with no terrain has no density
    cfg = load_all()
    used = ["slope_med", "slope_p90", "relief", "rough_a", "rough_b", "sun_max_elev", "sun_low_share"]
    g = apply_gates(df, cfg["gates"], used)
    codes = dict(zip(df["tile_id"], np.asarray(g["code"] if isinstance(g, pd.DataFrame) else g)))
    assert codes[G.tile_id(3003, ROW_MID + 2)] == CODE["missing_data"]   # NaN terrain -> missing_data
    assert codes[G.tile_id(3002, ROW_MID)] == CODE["vegetated"]
    assert codes[G.tile_id(3001, ROW_MID)] == CODE["ok"]
    r = CliRunner().invoke(cli.app, ["verify-data"])
    assert r.exit_code == 0 and "[PASS]" in r.output, r.output
    r = CliRunner().invoke(cli.app, ["s2", "assemble", "--gate", str(tmp_path / "nope")])
    assert r.exit_code == 1 and "[FAIL]" in r.output


REAL = Path(r"C:\Users\lenovo\sim\data\raw")


@pytest.mark.skipif(not (REAL / "terrain90" / "gsop_terrain90").exists(), reason="real downloads not on this machine")
def test_real_downloads_assemble_without_overlap_errors():
    gate_dir, srtm_dir = REAL / "gate" / "gsop_gate", REAL / "terrain90" / "gsop_terrain90"
    hi_dir = REAL / "terrain90_hi" / "gsop_terrain90_hi"
    df, rep = A.assemble(gate_dir, srtm_dir, hi_dir, add_solar=False)
    assert rep["srtm"]["files"] > 0 and rep["tiles_terrain_from_srtm"] > 0
    assert rep["tiles_with_complete_terrain"] + rep["tiles_with_nan_terrain"] == rep["land_tiles"] == len(df)
    # one tile read straight from a source file equals the assembled value
    f = sorted(srtm_dir.glob("terrain90_r*_c*.tif"))[len(list(srtm_dir.glob("*.tif"))) // 2]
    with rasterio.open(f) as ds:
        a = ds.read(1)
        c0 = int(round((ds.transform.c - G.x0) / 6000.0))
        r0 = int(round((G.y_top - ds.transform.f) / 6000.0))
    sub = df.set_index("tile_id")
    hits = 0
    for j, i in zip(*np.nonzero(np.isfinite(a) & (a != -9999))):
        t = G.tile_id(c0 + i, r0 + j)
        if t in sub.index and G.centre_lonlat(c0 + i, r0 + j)[1] <= 60.0:
            assert sub.at[t, "slope_med"] == pytest.approx(float(a[j, i]))
            hits += 1
            if hits > 20:
                break
