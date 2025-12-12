from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np


@dataclass
class CoolingEnvConfig:
    dt_minutes: int = 5
    horizon_steps: int = 12  # forecast horizon (e.g., 60 minutes at 5-min dt)

    # Thermal model (simple but stable for demos)
    temp_ambient_c: float = 24.0
    temp_start_c: float = 26.0
    temp_max_c: float = 30.0  # SLA limit (demo)
    # \"Efficiency target\": encourage running warmer (but still safe).
    temp_target_c: float = 29.0

    # Calibrated so temps sit ~24-30C for typical demo loads (300-800kW).
    thermal_mass: float = 5.0  # higher = slower temperature changes
    heat_gain_per_kw: float = 0.0018  # scaled: per-step heat gain per kW IT load
    cooling_scale: float = 0.85  # scaled: converts capacity -> per-step cooling term

    # Cooling effectiveness
    fan_cooling_gain: float = 1.35
    flow_cooling_gain: float = 1.85

    # Actuator limits
    fan_min: float = 0.15
    fan_max: float = 1.00
    flow_min: float = 0.15
    flow_max: float = 1.00
    actuator_alpha: float = 0.35  # actuator lag: actual <- actual + alpha*(cmd-actual)

    # Energy model (kW), produces a PUE-like proxy
    it_baseline_kw: float = 0.0  # supplied externally via workload
    cooling_overhead_kw: float = 25.0
    fan_power_kw_at_1: float = 65.0  # fan ~ cubic
    pump_power_kw_at_1: float = 55.0  # pump ~ quadratic

    # Reward shaping
    # NOTE: these weights are primarily for RL learning stability; metrics are computed from physics/energy.
    energy_cost_weight: float = 0.02
    # Strongly enforce temperature SLA (investor demo: \"safe and efficient\")
    sla_violation_weight: float = 220.0
    cold_weight: float = 0.25  # penalty for being below temp_target_c (squared)
    wear_weight: float = 0.08

    # Stochasticity
    process_noise_c: float = 0.06


class CoolingEnv:
    """Toy cooling-control environment.

    State includes: current temp, current load, forecast horizon, current fan/flow.
    Actions are discrete adjustments to fan and flow.
    """

    ACTIONS = (
        (0.0, 0.0),
        (+0.08, 0.0),
        (-0.08, 0.0),
        (0.0, +0.08),
        (0.0, -0.08),
        (+0.05, +0.05),
        (-0.05, -0.05),
    )

    def __init__(self, cfg: CoolingEnvConfig, *, seed: int = 0):
        self.cfg = cfg
        self.rng = np.random.default_rng(seed)
        self.reset()

    def reset(
        self,
        *,
        load_kw: float | None = None,
        forecast_kw: np.ndarray | None = None,
        temp_c: float | None = None,
        fan: float | None = None,
        flow: float | None = None,
    ) -> np.ndarray:
        self.temp_c = float(self.cfg.temp_start_c if temp_c is None else temp_c)
        self.fan = float(0.55 if fan is None else fan)  # actual
        self.flow = float(0.55 if flow is None else flow)  # actual
        self.fan_cmd = float(self.fan)
        self.flow_cmd = float(self.flow)
        self.load_kw = float(350.0 if load_kw is None else load_kw)
        self.forecast_kw = (
            np.full((self.cfg.horizon_steps,), self.load_kw, dtype=float)
            if forecast_kw is None
            else np.asarray(forecast_kw, dtype=float).reshape(self.cfg.horizon_steps)
        )
        return self._obs()

    def set_inputs(self, *, load_kw: float, forecast_kw: np.ndarray) -> None:
        self.load_kw = float(load_kw)
        self.forecast_kw = np.asarray(forecast_kw, dtype=float).reshape(self.cfg.horizon_steps)

    def _cooling_capacity(self) -> float:
        # Normalized "capacity" signal (unitless)
        fan_eff = self.cfg.fan_cooling_gain * (self.fan**1.4)
        flow_eff = self.cfg.flow_cooling_gain * (self.flow**1.2)
        return fan_eff + flow_eff

    def cooling_power_kw(self) -> float:
        # Fan ~ cubic, pump ~ quadratic
        fan_kw = self.cfg.fan_power_kw_at_1 * (self.fan**3)
        pump_kw = self.cfg.pump_power_kw_at_1 * (self.flow**2)
        return self.cfg.cooling_overhead_kw + fan_kw + pump_kw

    def step(self, action_idx: int) -> Tuple[np.ndarray, float, Dict[str, float]]:
        df, dw = self.ACTIONS[int(action_idx)]
        prev_fan, prev_flow = self.fan, self.flow

        # Update command (instant), then apply actuator lag to actual.
        self.fan_cmd = float(np.clip(self.fan_cmd + df, self.cfg.fan_min, self.cfg.fan_max))
        self.flow_cmd = float(np.clip(self.flow_cmd + dw, self.cfg.flow_min, self.cfg.flow_max))
        a = float(self.cfg.actuator_alpha)
        self.fan = float(np.clip(self.fan + a * (self.fan_cmd - self.fan), self.cfg.fan_min, self.cfg.fan_max))
        self.flow = float(np.clip(self.flow + a * (self.flow_cmd - self.flow), self.cfg.flow_min, self.cfg.flow_max))

        # Temperature dynamics
        heat_in = self.cfg.heat_gain_per_kw * self.load_kw
        cooling = self.cfg.cooling_scale * self._cooling_capacity()
        drift_to_ambient = 0.12 * (self.cfg.temp_ambient_c - self.temp_c)

        noise = float(self.rng.normal(0.0, self.cfg.process_noise_c))
        dtemp = (heat_in - cooling + drift_to_ambient) / max(1e-6, self.cfg.thermal_mass)
        self.temp_c = float(self.temp_c + dtemp + noise)

        # Reward
        cool_kw = self.cooling_power_kw()
        sla_violation = max(0.0, self.temp_c - self.cfg.temp_max_c)
        cold = max(0.0, self.cfg.temp_target_c - self.temp_c)
        wear = abs(self.fan - prev_fan) + abs(self.flow - prev_flow)

        reward = (
            -self.cfg.energy_cost_weight * cool_kw
            -self.cfg.sla_violation_weight * (sla_violation**2)
            -self.cfg.cold_weight * (cold**2)
            -self.cfg.wear_weight * wear
        )

        info = {
            "temp_c": float(self.temp_c),
            "load_kw": float(self.load_kw),
            "fan": float(self.fan),
            "flow": float(self.flow),
            "cooling_kw": float(cool_kw),
            "sla_violation_c": float(sla_violation),
        }
        return self._obs(), float(reward), info

    def _obs(self) -> np.ndarray:
        # Normalize for learning stability
        t = (self.temp_c - 20.0) / 15.0
        l = (self.load_kw - 100.0) / 900.0
        fcast = (self.forecast_kw - 100.0) / 900.0
        fan = self.fan
        flow = self.flow
        return np.concatenate(([t, l, fan, flow], fcast.astype(float)), axis=0).astype(np.float32)
