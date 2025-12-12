from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _relu(x: np.ndarray) -> np.ndarray:
    return np.maximum(x, 0.0)


@dataclass
class DQNConfig:
    obs_dim: int
    n_actions: int

    hidden: int = 96
    lr: float = 2e-3
    gamma: float = 0.99

    epsilon_start: float = 1.0
    epsilon_end: float = 0.08
    epsilon_decay_steps: int = 9000

    target_update_every: int = 250


class DQN:
    """Tiny DQN (2-layer MLP) implemented in NumPy for demo portability."""

    def __init__(self, cfg: DQNConfig, *, seed: int = 0):
        self.cfg = cfg
        self.rng = np.random.default_rng(seed)

        # Online network params
        self.W1 = (self.rng.normal(0, 0.08, size=(cfg.obs_dim, cfg.hidden))).astype(np.float32)
        self.b1 = np.zeros((cfg.hidden,), dtype=np.float32)
        self.W2 = (self.rng.normal(0, 0.08, size=(cfg.hidden, cfg.n_actions))).astype(np.float32)
        self.b2 = np.zeros((cfg.n_actions,), dtype=np.float32)

        # Target network params
        self.tW1 = self.W1.copy()
        self.tb1 = self.b1.copy()
        self.tW2 = self.W2.copy()
        self.tb2 = self.b2.copy()

        self.step_count = 0

    def _q(self, s: np.ndarray) -> np.ndarray:
        h = _relu(s @ self.W1 + self.b1)
        return h @ self.W2 + self.b2

    def _tq(self, s: np.ndarray) -> np.ndarray:
        h = _relu(s @ self.tW1 + self.tb1)
        return h @ self.tW2 + self.tb2

    def act(self, s: np.ndarray) -> int:
        eps = self.epsilon(self.step_count)
        self.step_count += 1
        if float(self.rng.random()) < eps:
            return int(self.rng.integers(0, self.cfg.n_actions))
        q = self._q(s[None, :])[0]
        return int(np.argmax(q))

    def epsilon(self, step: int) -> float:
        if step <= 0:
            return float(self.cfg.epsilon_start)
        frac = min(1.0, step / max(1, self.cfg.epsilon_decay_steps))
        return float(self.cfg.epsilon_start + frac * (self.cfg.epsilon_end - self.cfg.epsilon_start))

    def train_step(self, s, a, r, sp, done) -> float:
        """One SGD step on a replay batch; returns loss."""
        # Forward (online)
        z1 = s @ self.W1 + self.b1
        h1 = _relu(z1)
        q = h1 @ self.W2 + self.b2  # [B, A]

        # Target values (Double DQN-ish: argmax from online, value from target)
        q_next_online = self._q(sp)
        a_next = np.argmax(q_next_online, axis=1)
        q_next_target = self._tq(sp)
        v_next = q_next_target[np.arange(q_next_target.shape[0]), a_next]
        y = r + self.cfg.gamma * (1.0 - done) * v_next

        qa = q[np.arange(q.shape[0]), a]
        td = (qa - y).astype(np.float32)
        loss = float(np.mean(td * td))

        # Backprop (MSE)
        B = s.shape[0]
        dqa = (2.0 / B) * td  # [B]

        dq = np.zeros_like(q, dtype=np.float32)
        dq[np.arange(B), a] = dqa

        dW2 = h1.T @ dq
        db2 = dq.sum(axis=0)

        dh1 = dq @ self.W2.T
        dz1 = dh1 * (z1 > 0)

        dW1 = s.T @ dz1
        db1 = dz1.sum(axis=0)

        # SGD update
        lr = self.cfg.lr
        self.W1 -= lr * dW1
        self.b1 -= lr * db1
        self.W2 -= lr * dW2
        self.b2 -= lr * db2

        return loss

    def maybe_update_target(self) -> None:
        if self.step_count % max(1, self.cfg.target_update_every) != 0:
            return
        self.tW1 = self.W1.copy()
        self.tb1 = self.b1.copy()
        self.tW2 = self.W2.copy()
        self.tb2 = self.b2.copy()
