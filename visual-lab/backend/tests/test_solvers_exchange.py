"""Scientific-solver integration (Cantera, Gmsh + scikit-fem, Agent A harness) and v1 exchange."""
import json
import math
from pathlib import Path

import numpy as np
import pytest
from conftest import air_state, make_plant

from vlab.exchange import export_flight, fields_from_doc, validate_doc, vehicle_from_doc
from vlab.mission import Step
from vlab.modes import Environment, ModeConfig
from vlab.sim import SimRequest, SimSettings, run
from vlab.vehicle import default_vehicle

FIX = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------- Cantera
@pytest.fixture(scope="module")
def air_table():
    from vlab.solvers.cantera_air import build_table
    return build_table()


def test_cantera_table_validates(air_table):
    meta = air_table["meta"]
    assert meta["solver"] == "cantera" and meta["valid"], meta["checks"]
    names = [c["check"] for c in meta["checks"]]
    assert any("Sutherland" in n for n in names) and any("ideal-gas" in n for n in names)


def test_cantera_rom_matches_direct_cantera(air_table):
    import cantera as ct
    from vlab.solvers.cantera_air import AirPropertyROM
    rom = AirPropertyROM.load()
    g = ct.Solution("air.yaml")
    g.X = {"O2": 0.21, "N2": 0.78, "AR": 0.01}
    for T, p in ((263.0, 75e3), (301.7, 99e3), (318.0, 63e3)):
        g.TP = T, p
        rho, mu = rom.lookup(T, p)
        assert rho == pytest.approx(g.density, rel=2e-3)
        assert mu == pytest.approx(g.viscosity, rel=2e-3)


def test_flight_model_consumes_cantera_rom(air_table):
    mc = ModeConfig(mode="ideal", environment=Environment(air_model="cantera_rom", temperature_k=310.0, pressure_pa=85e3))
    p = make_plant(mode=mc, drag=True)
    from vlab.solvers.cantera_air import AirPropertyROM
    rho, _ = AirPropertyROM.load().lookup(310.0, 85e3)
    assert p.rho == pytest.approx(rho, rel=1e-12)
    assert "Cantera" in p.rm.air_source
    # drag force scales with that density
    x = air_state(p, z=5.0, v=(1.0, 0, 0))
    wr = p.wrench(x, np.zeros(3))
    L, W, H = 0.1, 0.032, 0.009
    assert wr["F_drag_w"][0] == pytest.approx(-0.5 * rho * 1.05 * W * H * 1.0, rel=1e-9)


# ---------------------------------------------------------------------------- Gmsh + scikit-fem
def test_fem_circle_added_mass_exact():
    from vlab.solvers.fem_added_mass import solve_section
    s = solve_section("circle", 0.01, 0.01, refine=0.6)
    assert s["C_A"] == pytest.approx(1.0, abs=6e-3)          # truncation (a/R)^2 + discretisation
    assert s["energy_identity_rel"] < 1e-8


def test_fem_deck_section_coefficient():
    from vlab.solvers.fem_added_mass import solve_section
    s = solve_section("rect", 0.016, 0.0045, refine=0.6)
    # literature interpolation for rectangle b/a ~ 0.28: C_A ~ 1.26 (DNV-RP-C205 Table A-1 trend)
    assert 1.22 < s["C_A"] < 1.30


def test_added_mass_reduces_heave_acceleration_exactly():
    v = default_vehicle()
    p0 = make_plant(vehicle=v)
    v2 = v.model_copy(deep=True)
    ma = 1.2453e-4
    v2.added_mass_kg = (0.0, 1.446e-5, ma)
    p1 = make_plant(vehicle=v2)
    F = 0.02
    for p, m_eff in ((p0, p0.m), (p1, p1.m + ma)):
        x = air_state(p, z=5.0)
        d = p.deriv(x, np.zeros(p.n), np.array([0.0, 0.0, F + p.m * p.g]))
        assert d[5] == pytest.approx(F / m_eff, rel=1e-12)


def test_added_mass_rom_if_built():
    from vlab.solvers.fem_added_mass import AddedMassROM, ROM_PATH
    if not ROM_PATH.exists():
        pytest.skip("FEM ROM not built (run solver job fem_added_mass)")
    rom = AddedMassROM.load()
    assert rom is not None and rom.meta["valid"]
    ma = rom.added_mass_kg(0.1, 0.032, 0.009, 1.225)
    expected = 1.264 * 1.225 * math.pi * 0.016 ** 2 * 0.1
    assert ma[2] == pytest.approx(expected, rel=5e-3)


# ---------------------------------------------------------------------------- exchange (v1 schema)
def test_harness_document_imports_and_flies():
    doc = json.loads((FIX / "harness_rotor_5105.v1.json").read_text())
    assert validate_doc(doc) == []
    v, mc, notes = vehicle_from_doc(doc)
    assert v.inertia_override_kgm2 == doc["vehicle"]["inertia_kgm2"]
    mission = [Step(kind="arm", duration_s=0.4), Step(kind="takeoff", duration_s=1.5, alt_m=0.2),
               Step(kind="hold", duration_s=1.5)]
    r = run(SimRequest(vehicle=v, mode=mc, mission=mission, settings=SimSettings(t_max_s=5)))
    assert r["summary"]["mass_kg"] == pytest.approx(doc["vehicle"]["mass_kg"], rel=1e-6)
    assert r["summary"]["takeoffs"] == 1 and not r["summary"]["failures"]
    assert r["feasibility"]["evidence"] == "simplified_numerical_simulation"


def test_export_flight_validates_against_shared_schema():
    mission = [Step(kind="arm", duration_s=0.3), Step(kind="takeoff", duration_s=1.0, alt_m=0.1),
               Step(kind="hold", duration_s=0.5)]
    r = run(SimRequest(mission=mission))
    doc = export_flight(r, every=5)
    assert validate_doc(doc) == []
    assert doc["source"] == "visual_lab" and doc["evidence"] == "hypothetical_ideal"
    assert all(a["mechanism"] == "hypothetical" for a in doc["vehicle"]["actuators"])
    assert len(doc["trajectory"]["t"]) == len(doc["trajectory"]["quat"])


def test_harness_fields_convert_without_modification():
    doc = json.loads((FIX / "harness_ehd_5111.v1.json").read_text())
    fs = fields_from_doc(doc)
    assert {f["quantity"] for f in fs} == {"phi", "rho"}
    phi = [f for f in fs if f["quantity"] == "phi"][0]
    assert phi["values"] is doc["fields"]["quantities"]["phi"]["values"]
    assert phi["evidence"] == doc["evidence"]


def test_not_installed_engines_report_not_connected():
    from vlab.solvers.registry import REGISTRY
    for name in ("elmer", "openfoam", "moose", "fenicsx", "getdp"):
        info = REGISTRY[name].info()
        assert info["status"] == "NOT CONNECTED"
        with pytest.raises(RuntimeError):
            REGISTRY[name].run({})


def test_harness_live_if_connected():
    from vlab import harness
    if not harness.status()["connected"]:
        pytest.skip("Research harness: NOT CONNECTED")
    rows = harness.list_experiments("rotor_design", limit=1)
    assert isinstance(rows, list)
