from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class WorkloadSeries:
    load_kw: np.ndarray  # shape [T]
    forecast_kw: np.ndarray  # shape [T, H]


def generate_workload(
    *,
    T: int,
    dt_minutes: int,
    horizon_steps: int,
    seed: int = 7,
    base_kw: float = 400.0,
    daily_amp_kw: float = 220.0,
    burst_amp_kw: float = 260.0,
    noise_kw: float = 20.0,
) -> WorkloadSeries:
    """Synthetic workload with day-like seasonality + bursts.

    - load_kw is IT load (kW).
    - forecast_kw is a simple noisy 'forecast' available to the controller.
    """

    rng = np.random.default_rng(seed)
    t = np.arange(T)

    steps_per_day = int(round((24 * 60) / dt_minutes))
    daily = np.sin(2.0 * np.pi * t / max(1, steps_per_day))

    # Bursty component: random pulses convolved with a short kernel.
    pulses = (rng.random(T) < 0.06).astype(float) * rng.uniform(0.4, 1.0, size=T)
    kernel = np.exp(-np.arange(0, 16) / 5.0)
    bursts = np.convolve(pulses, kernel, mode="same")
    bursts = bursts / (bursts.max() + 1e-9)

    load = (
        base_kw
        + daily_amp_kw * (0.5 + 0.5 * daily)
        + burst_amp_kw * bursts
        + rng.normal(0.0, noise_kw, size=T)
    )
    load = np.clip(load, 80.0, None)

    # Naive forecast: true future + noise; clipped to non-negative.
    forecast = np.zeros((T, horizon_steps), dtype=float)
    for i in range(T):
        for h in range(1, horizon_steps + 1):
            j = min(T - 1, i + h)
            forecast[i, h - 1] = load[j]
    forecast = forecast + rng.normal(0.0, noise_kw * 1.5, size=forecast.shape)
    forecast = np.clip(forecast, 0.0, None)

    return WorkloadSeries(load_kw=load.astype(float), forecast_kw=forecast.astype(float))
