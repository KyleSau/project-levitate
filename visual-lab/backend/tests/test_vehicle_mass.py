"""Mass distribution -> mass, CG, inertia consistency."""
import numpy as np
import pytest

from vlab.vehicle import (MassComponent, VehicleConfig, box_inertia, check_inertia, default_vehicle,
                          mass_properties, scale_total_mass, set_cg)


def test_default_mass_and_symmetry():
    mp = mass_properties(default_vehicle())
    assert mp.mass_kg == pytest.approx(0.020)
    assert mp.valid
    assert abs(mp.cg_m[0]) < 1e-15 and abs(mp.cg_m[1]) < 1e-15
    J = np.array(mp.inertia_kgm2)
    assert J[2, 2] > J[1, 1] > J[0, 0] > 0      # long thin board: yaw > pitch > roll


def test_single_box_matches_textbook():
    v = VehicleConfig(components=[MassComponent(name="b", mass_kg=0.02, size_m=(0.1, 0.032, 0.009))], actuators=[])
    J = np.array(mass_properties(v).inertia_kgm2)
    np.testing.assert_allclose(np.diag(J), [0.02 * (0.032**2 + 0.009**2) / 12, 0.02 * (0.1**2 + 0.009**2) / 12,
                                            0.02 * (0.1**2 + 0.032**2) / 12], rtol=1e-12)


def test_mass_scaling_scales_inertia_linearly():
    a = mass_properties(default_vehicle(0.020))
    b = mass_properties(scale_total_mass(default_vehicle(0.020), 0.050))
    np.testing.assert_allclose(np.array(b.inertia_kgm2), np.array(a.inertia_kgm2) * 2.5, rtol=1e-12, atol=1e-20)
    np.testing.assert_allclose(b.cg_m, a.cg_m, atol=1e-15)


def test_cg_shift_updates_inertia_by_parallel_axis():
    v0 = default_vehicle()
    v1 = set_cg(v0, (0.006, 0.0, 0.0))
    mp1 = mass_properties(v1)
    assert mp1.cg_m[0] == pytest.approx(0.006, abs=1e-12)
    # independent recomputation about the new CG
    J = np.zeros((3, 3))
    cg = np.array(mp1.cg_m)
    for c in v1.components:
        d = np.array(c.pos_m) - cg
        J += box_inertia(c.mass_kg, *c.size_m) + c.mass_kg * (d @ d * np.eye(3) - np.outer(d, d))
    np.testing.assert_allclose(mp1.inertia_kgm2, J, rtol=1e-12, atol=1e-20)
    assert mp1.inertia_kgm2[1][1] != pytest.approx(mass_properties(v0).inertia_kgm2[1][1], rel=1e-6)
    assert mp1.valid


def test_unreachable_cg_rejected():
    with pytest.raises(ValueError):
        set_cg(default_vehicle(), (0.045, 0, 0))


def test_invalid_inertia_detected():
    assert check_inertia(np.diag([1.0, 1.0, 3.0]))          # violates triangle inequality
    assert check_inertia(np.diag([1.0, -1.0, 1.0]))
    assert not check_inertia(np.diag([1.0, 2.0, 2.5]))
