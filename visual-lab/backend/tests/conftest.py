import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vlab.modes import ModeConfig, resolve  # noqa: E402
from vlab.plant import Plant  # noqa: E402
from vlab.vehicle import default_vehicle  # noqa: E402


def make_plant(drag: bool = False, vehicle=None, mode: ModeConfig | None = None, g: float | None = None):
    mc = mode or ModeConfig(mode="ideal")
    mc = mc.model_copy(deep=True)
    mc.drag.enabled = drag
    if g is not None:
        mc.environment.g = g
    rm = resolve(vehicle or default_vehicle(), mc)
    return Plant(rm, mc.environment)


def air_state(plant, z=10.0, v=(0, 0, 0), q=(1, 0, 0, 0), w=(0, 0, 0)):
    x = np.zeros(plant.nx)
    x[0:3] = (0, 0, z)
    x[3:6] = v
    x[6:10] = q
    x[10:13] = w
    return x


@pytest.fixture
def plant():
    return make_plant()
