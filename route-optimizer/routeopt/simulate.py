"""Monte Carlo delay model for a route.

Per leg: with probability p a delay occurs, its duration ~ lognormal(mean=mu, sigma=0.6);
plus a rare disruption shock (reroute, +7-14 days) with probability 0.10 * geopolitical risk.
Legs are independent, so a route with more legs/hubs accumulates more delay exposure.
The same function is used for *estimated* parameters (decision time) and *true* parameters
(evaluation) -- only the inputs differ.
"""
from __future__ import annotations

import numpy as np

from . import config as C


def simulate_delay(p, mu, geo, n: int, rng: np.random.Generator) -> np.ndarray:
    """Return n samples of total route delay in days. p, mu, geo are per-leg arrays."""
    p, mu, geo = (np.asarray(x, dtype=float) for x in (p, mu, geo))
    L = len(p)
    occurs = rng.random((n, L)) < p
    sig = C.DELAY_SIGMA
    dur = rng.lognormal(np.log(np.maximum(mu, 1e-6)) - sig**2 / 2, sig, (n, L))
    delay = (occurs * dur).sum(axis=1)
    shock = rng.random((n, L)) < (C.SHOCK_P_PER_GEO * geo)
    delay += (shock * rng.uniform(*C.SHOCK_DAYS, (n, L))).sum(axis=1)
    return delay


def expected_delay(p, mu, geo) -> float:
    """Closed-form E[delay] (used as a cross-check against Monte Carlo in tests)."""
    p, mu, geo = (np.asarray(x, dtype=float) for x in (p, mu, geo))
    return float((p * mu).sum() + (C.SHOCK_P_PER_GEO * geo * sum(C.SHOCK_DAYS) / 2).sum())
