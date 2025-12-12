from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

from .controllers import FixedController, ForecastController, ReactiveController
from .dqn import DQN, DQNConfig
from .env import CoolingEnv, CoolingEnvConfig
from .replay import ReplayBuffer
from .workload import generate_workload


@dataclass
class EpisodeResult:
    name: str
    total_cooling_kwh: float
    total_it_kwh: float
    sla_violations: int
    sla_violation_degree_minutes: float
    avg_temp_c: float
    max_temp_c: float


def _rollout(
    *,
    name: str,
    env_cfg: CoolingEnvConfig,
    load_kw: np.ndarray,
    forecast_kw: np.ndarray,
    policy_fn,
) -> Tuple[EpisodeResult, Dict[str, np.ndarray]]:
    env = CoolingEnv(env_cfg, seed=123)
    obs = env.reset(load_kw=float(load_kw[0]), forecast_kw=forecast_kw[0])

    T = load_kw.shape[0]
    temps = np.zeros((T,), dtype=float)
    fans = np.zeros((T,), dtype=float)
    flows = np.zeros((T,), dtype=float)
    cool_kw = np.zeros((T,), dtype=float)
    rewards = np.zeros((T,), dtype=float)
    sla_v = np.zeros((T,), dtype=float)

    it_kwh = 0.0
    cooling_kwh = 0.0
    violations = 0
    violation_degree_minutes = 0.0

    dt_h = env_cfg.dt_minutes / 60.0

    for t in range(T):
        env.set_inputs(load_kw=float(load_kw[t]), forecast_kw=forecast_kw[t])
        a = int(policy_fn(obs, env.ACTIONS))
        obs, r, info = env.step(a)

        temps[t] = info["temp_c"]
        fans[t] = info["fan"]
        flows[t] = info["flow"]
        cool_kw[t] = info["cooling_kw"]
        rewards[t] = r
        sla_v[t] = info["sla_violation_c"]

        it_kwh += float(load_kw[t]) * dt_h
        cooling_kwh += float(info["cooling_kw"]) * dt_h

        if info["sla_violation_c"] > 0:
            violations += 1
            violation_degree_minutes += float(info["sla_violation_c"]) * env_cfg.dt_minutes

    res = EpisodeResult(
        name=name,
        total_cooling_kwh=float(cooling_kwh),
        total_it_kwh=float(it_kwh),
        sla_violations=int(violations),
        sla_violation_degree_minutes=float(violation_degree_minutes),
        avg_temp_c=float(np.mean(temps)),
        max_temp_c=float(np.max(temps)),
    )
    series = {
        "temp_c": temps,
        "fan": fans,
        "flow": flows,
        "cooling_kw": cool_kw,
        "reward": rewards,
        "sla_violation_c": sla_v,
        "load_kw": load_kw.astype(float),
    }
    return res, series


def _train_dqn(
    *,
    env_cfg: CoolingEnvConfig,
    load_kw: np.ndarray,
    forecast_kw: np.ndarray,
    steps: int,
    seed: int,
) -> DQN:
    env = CoolingEnv(env_cfg, seed=seed)
    obs_dim = 4 + env_cfg.horizon_steps
    dqn = DQN(DQNConfig(obs_dim=obs_dim, n_actions=len(env.ACTIONS)), seed=seed)

    rb = ReplayBuffer(capacity=45_000, obs_dim=obs_dim, seed=seed)

    episode_len = 240  # periodic resets stabilize training (toy env is non-terminating)

    def random_reset(t_index: int) -> np.ndarray:
        temp = float(env.rng.uniform(env_cfg.temp_start_c - 0.8, env_cfg.temp_start_c + 1.2))
        fan = float(env.rng.uniform(0.25, 0.85))
        flow = float(env.rng.uniform(0.25, 0.85))
        return env.reset(load_kw=float(load_kw[t_index]), forecast_kw=forecast_kw[t_index], temp_c=temp, fan=fan, flow=flow)

    obs = random_reset(0)

    # Warm start: small random buffer
    warm = min(1500, steps // 5)
    for t in range(warm):
        i = t % load_kw.shape[0]
        env.set_inputs(load_kw=float(load_kw[i]), forecast_kw=forecast_kw[i])
        a = int(env.rng.integers(0, len(env.ACTIONS)))
        obs2, r, info = env.step(a)
        end = ((t + 1) % episode_len) == 0
        if end:
            obs_reset = random_reset((i + 1) % load_kw.shape[0])
            rb.add(obs, a, r, obs_reset, True)
            obs = obs_reset
        else:
            rb.add(obs, a, r, obs2, False)
            obs = obs2

    batch = 128
    learn_every = 2

    for t in range(steps):
        i = t % load_kw.shape[0]
        env.set_inputs(load_kw=float(load_kw[i]), forecast_kw=forecast_kw[i])

        a = dqn.act(obs)
        obs2, r, info = env.step(a)
        end = ((t + 1) % episode_len) == 0
        if end:
            obs_reset = random_reset((i + 1) % load_kw.shape[0])
            rb.add(obs, a, r, obs_reset, True)
            obs = obs_reset
        else:
            rb.add(obs, a, r, obs2, False)
            obs = obs2

        if rb.size >= batch and (t % learn_every == 0):
            b = rb.sample(batch)
            dqn.train_step(b.s, b.a, b.r, b.sp, b.done)
            dqn.maybe_update_target()

    return dqn


def _print_results(results: List[EpisodeResult]) -> None:
    def pue_proxy(r: EpisodeResult) -> float:
        # proxy: (IT + cooling) / IT
        return (r.total_it_kwh + r.total_cooling_kwh) / max(1e-9, r.total_it_kwh)

    print("\n=== Cooling Optimization MVP (Toy Simulation) ===")
    for r in results:
        print(
            f"{r.name:>12} | cooling_kWh={r.total_cooling_kwh:8.1f} | "
            f"PUE~={pue_proxy(r):5.3f} | avgT={r.avg_temp_c:4.2f}C | "
            f"maxT={r.max_temp_c:4.2f}C | SLA_steps={r.sla_violations:4d} | "
            f"deg-min={r.sla_violation_degree_minutes:7.1f}"
        )

    base = results[0]
    for r in results[1:]:
        savings = 100.0 * (base.total_cooling_kwh - r.total_cooling_kwh) / max(1e-9, base.total_cooling_kwh)
        print(f"Savings vs {base.name}: {r.name} => {savings:5.1f}%")

    reactive = next((r for r in results if r.name.lower() == "reactive"), None)
    if reactive is not None:
        for r in results:
            if r.name == reactive.name:
                continue
            savings = 100.0 * (reactive.total_cooling_kwh - r.total_cooling_kwh) / max(1e-9, reactive.total_cooling_kwh)
            print(f"Savings vs Reactive: {r.name} => {savings:5.1f}%")


def _plot(out_dir: Path, title: str, series_by_name: Dict[str, Dict[str, np.ndarray]], env_cfg: CoolingEnvConfig) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = list(series_by_name.keys())
    T = len(next(iter(series_by_name.values()))["temp_c"])
    x = np.arange(T) * env_cfg.dt_minutes

    fig = plt.figure(figsize=(12, 10))

    ax1 = plt.subplot(4, 1, 1)
    for n in names:
        ax1.plot(x, series_by_name[n]["temp_c"], label=n)
    ax1.axhline(env_cfg.temp_max_c, color="r", linestyle="--", linewidth=1, label="SLA max")
    ax1.set_ylabel("Temp (C)")
    ax1.set_title(title)
    ax1.legend(ncol=4, fontsize=9)

    ax2 = plt.subplot(4, 1, 2, sharex=ax1)
    ax2.plot(x, series_by_name[names[0]]["load_kw"], color="k", linewidth=1)
    ax2.set_ylabel("IT load (kW)")

    ax3 = plt.subplot(4, 1, 3, sharex=ax1)
    for n in names:
        ax3.plot(x, series_by_name[n]["cooling_kw"], label=n)
    ax3.set_ylabel("Cooling (kW)")

    ax4 = plt.subplot(4, 1, 4, sharex=ax1)
    for n in names:
        ax4.plot(x, series_by_name[n]["fan"], label=f"{n}:fan")
        ax4.plot(x, series_by_name[n]["flow"], label=f"{n}:flow", linestyle="--")
    ax4.set_ylabel("Actuators (0-1)")
    ax4.set_xlabel("Time (minutes)")
    ax4.legend(ncol=3, fontsize=8)

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "cooling_demo.png"
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="Cooling RL MVP demo")
    ap.add_argument("--steps", type=int, default=14_000, help="DQN training steps")
    ap.add_argument("--T", type=int, default=720, help="timesteps per evaluation episode")
    ap.add_argument("--dt", type=int, default=5, help="minutes per timestep")
    ap.add_argument("--horizon", type=int, default=12, help="forecast horizon in steps")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=str, default=str(Path(__file__).resolve().parent / "out"))
    args = ap.parse_args()

    env_cfg = CoolingEnvConfig(dt_minutes=args.dt, horizon_steps=args.horizon)

    wl = generate_workload(T=args.T, dt_minutes=args.dt, horizon_steps=args.horizon, seed=args.seed)
    load_kw = wl.load_kw
    forecast_kw = wl.forecast_kw

    # Baselines
    fixed = FixedController(fan=0.62, flow=0.62)
    # Conservative rule-based baselines (common in practice to protect SLA).
    reactive = ReactiveController(temp_target_c=25.5)
    forecast_ctl = ForecastController(temp_target_c=25.5)

    fixed_res, fixed_series = _rollout(
        name="Fixed",
        env_cfg=env_cfg,
        load_kw=load_kw,
        forecast_kw=forecast_kw,
        policy_fn=lambda obs, actions: fixed.select_action(obs, action_table=actions),
    )

    react_res, react_series = _rollout(
        name="Reactive",
        env_cfg=env_cfg,
        load_kw=load_kw,
        forecast_kw=forecast_kw,
        policy_fn=lambda obs, actions: reactive.select_action(obs, action_table=actions),
    )

    fcast_res, fcast_series = _rollout(
        name="Forecast",
        env_cfg=env_cfg,
        load_kw=load_kw,
        forecast_kw=forecast_kw,
        policy_fn=lambda obs, actions: forecast_ctl.select_action(obs, action_table=actions),
    )

    # Train RL
    dqn = _train_dqn(env_cfg=env_cfg, load_kw=load_kw, forecast_kw=forecast_kw, steps=args.steps, seed=args.seed)

    rl_res, rl_series = _rollout(
        name="DQN",
        env_cfg=env_cfg,
        load_kw=load_kw,
        forecast_kw=forecast_kw,
        policy_fn=lambda obs, actions: int(np.argmax(dqn._q(obs[None, :])[0])),
    )

    results = [fixed_res, react_res, fcast_res, rl_res]
    _print_results(results)

    series_by_name = {
        "Fixed": fixed_series,
        "Reactive": react_series,
        "Forecast": fcast_series,
        "DQN": rl_series,
    }

    out_dir = Path(args.out)
    _plot(out_dir, "Cooling control vs. workload (toy simulation)", series_by_name, env_cfg)
    print(f"\nSaved plot: {out_dir / 'cooling_demo.png'}")


if __name__ == "__main__":
    main()
