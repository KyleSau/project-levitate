"""Physical constants (SI). Sources: CODATA 2018, ISA standard atmosphere."""

G0 = 9.80665                # standard gravity [m/s^2]
EPS0 = 8.8541878128e-12     # vacuum permittivity [F/m]
MU0 = 1.25663706212e-6      # vacuum permeability [H/m]
R_UNIVERSAL = 8.314462618   # [J/(mol K)]

# ISA sea level
RHO_AIR_SL = 1.225          # [kg/m^3] at 15 C, 101325 Pa
P_SL = 101325.0             # [Pa]
T_SL = 288.15               # [K]
MU_AIR_SL = 1.789e-5        # dynamic viscosity [Pa s]

M_AIR = 0.0289647           # molar mass dry air [kg/mol]
M_H2 = 0.00201588           # [kg/mol]
M_HE = 0.004002602          # [kg/mol]

H2_LHV = 119.96e6           # lower heating value [J/kg]
J_PER_WH = 3600.0


def air_density(pressure_pa: float = P_SL, temperature_k: float = T_SL) -> float:
    """Ideal-gas dry-air density."""
    return pressure_pa * M_AIR / (R_UNIVERSAL * temperature_k)


def gas_density(molar_mass: float, pressure_pa: float = P_SL, temperature_k: float = T_SL) -> float:
    return pressure_pa * molar_mass / (R_UNIVERSAL * temperature_k)
