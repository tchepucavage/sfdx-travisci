from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ReplayBatch:
    s: np.ndarray
    a: np.ndarray
    r: np.ndarray
    sp: np.ndarray
    done: np.ndarray


class ReplayBuffer:
    def __init__(self, capacity: int, obs_dim: int, *, seed: int = 0):
        self.capacity = int(capacity)
        self.obs_dim = int(obs_dim)
        self.rng = np.random.default_rng(seed)

        self.s = np.zeros((capacity, obs_dim), dtype=np.float32)
        self.a = np.zeros((capacity,), dtype=np.int64)
        self.r = np.zeros((capacity,), dtype=np.float32)
        self.sp = np.zeros((capacity, obs_dim), dtype=np.float32)
        self.done = np.zeros((capacity,), dtype=np.float32)

        self.size = 0
        self.ptr = 0

    def add(self, s: np.ndarray, a: int, r: float, sp: np.ndarray, done: bool) -> None:
        i = self.ptr
        self.s[i] = s
        self.a[i] = int(a)
        self.r[i] = float(r)
        self.sp[i] = sp
        self.done[i] = 1.0 if done else 0.0

        self.ptr = (self.ptr + 1) % self.capacity
        self.size = min(self.capacity, self.size + 1)

    def sample(self, batch_size: int) -> ReplayBatch:
        n = min(self.size, self.capacity)
        idx = self.rng.integers(0, n, size=int(batch_size))
        return ReplayBatch(
            s=self.s[idx],
            a=self.a[idx],
            r=self.r[idx],
            sp=self.sp[idx],
            done=self.done[idx],
        )
