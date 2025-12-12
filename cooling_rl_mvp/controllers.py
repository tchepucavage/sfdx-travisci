from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class FixedController:
    fan: float = 0.55
    flow: float = 0.55

    def select_action(self, obs: np.ndarray, *, action_table) -> int:
        # Choose the action that moves fan/flow closest to the fixed setpoints
        cur_fan = float(obs[2])
        cur_flow = float(obs[3])
        best_i, best = 0, 1e9
        for i, (df, dw) in enumerate(action_table):
            f = np.clip(cur_fan + df, 0.0, 1.0)
            w = np.clip(cur_flow + dw, 0.0, 1.0)
            score = abs(f - self.fan) + abs(w - self.flow)
            if score < best:
                best = score
                best_i = i
        return int(best_i)


@dataclass
class ReactiveController:
    """Simple rule-based controller (reactive) as a baseline."""

    temp_target_c: float = 27.0

    def select_action(self, obs: np.ndarray, *, action_table) -> int:
        temp_c = float(obs[0] * 15.0 + 20.0)
        cur_fan = float(obs[2])
        cur_flow = float(obs[3])

        err = temp_c - self.temp_target_c

        # More aggressive if hot, back off if cool.
        if err > 0.6:
            desired = (min(1.0, cur_fan + 0.08), min(1.0, cur_flow + 0.08))
        elif err < -0.6:
            desired = (max(0.15, cur_fan - 0.08), max(0.15, cur_flow - 0.08))
        else:
            desired = (cur_fan, cur_flow)

        best_i, best = 0, 1e9
        for i, (df, dw) in enumerate(action_table):
            f = np.clip(cur_fan + df, 0.0, 1.0)
            w = np.clip(cur_flow + dw, 0.0, 1.0)
            score = abs(f - desired[0]) + abs(w - desired[1])
            if score < best:
                best = score
                best_i = i
        return int(best_i)


@dataclass
class ForecastController:
    """Uses forecast to pre-cool ahead of predicted spikes (baseline)."""

    temp_target_c: float = 27.0
    pre_cool_threshold_kw: float = 650.0

    def select_action(self, obs: np.ndarray, *, action_table) -> int:
        temp_c = float(obs[0] * 15.0 + 20.0)
        cur_load_kw = float(obs[1] * 900.0 + 100.0)
        cur_fan = float(obs[2])
        cur_flow = float(obs[3])
        forecast_kw = obs[4:]
        fcast_max_kw = float((forecast_kw * 900.0 + 100.0).max())

        # If forecast says a spike is coming, bias toward pre-cooling.
        if fcast_max_kw > self.pre_cool_threshold_kw and temp_c < (self.temp_target_c + 0.4):
            desired = (min(1.0, cur_fan + 0.08), min(1.0, cur_flow + 0.08))
        else:
            # Otherwise behave like a gentler reactive controller
            err = temp_c - self.temp_target_c
            if err > 0.7:
                desired = (min(1.0, cur_fan + 0.08), min(1.0, cur_flow + 0.08))
            elif err < -0.7 and cur_load_kw < 520.0:
                desired = (max(0.15, cur_fan - 0.08), max(0.15, cur_flow - 0.08))
            else:
                desired = (cur_fan, cur_flow)

        best_i, best = 0, 1e9
        for i, (df, dw) in enumerate(action_table):
            f = np.clip(cur_fan + df, 0.0, 1.0)
            w = np.clip(cur_flow + dw, 0.0, 1.0)
            score = abs(f - desired[0]) + abs(w - desired[1])
            if score < best:
                best = score
                best_i = i
        return int(best_i)
