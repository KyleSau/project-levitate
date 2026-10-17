"""Physical constants (SI). Sources: CODATA 2018, ISO 2533 standard atmosphere."""

G0 = 9.80665                 # standard gravity [m/s^2] (exact, CGPM 1901)
R_UNIVERSAL = 8.314462618    # molar gas constant [J/(mol K)]
M_AIR = 0.0289647            # molar mass of dry air [kg/mol]
P_SL = 101325.0              # ISA sea-level pressure [Pa]
T_SL = 288.15                # ISA sea-level temperature [K]
RHO_SL = 1.225               # ISA sea-level density [kg/m^3]
MU_SL = 1.789e-5             # ISA sea-level dynamic viscosity [Pa s]

# Sutherland's law for air (White, Viscous Fluid Flow): mu = mu_ref (T/T_ref)^1.5 (T_ref+S)/(T+S)
SUTHERLAND_MU_REF = 1.716e-5
SUTHERLAND_T_REF = 273.15
SUTHERLAND_S = 110.4


def ideal_gas_density(pressure_pa: float = P_SL, temperature_k: float = T_SL, molar_mass: float = M_AIR) -> float:
    return pressure_pa * molar_mass / (R_UNIVERSAL * temperature_k)


def sutherland_viscosity(temperature_k: float) -> float:
    t = temperature_k
    return SUTHERLAND_MU_REF * (t / SUTHERLAND_T_REF) ** 1.5 * (SUTHERLAND_T_REF + SUTHERLAND_S) / (t + SUTHERLAND_S)
