"""Decision framework: metrics -> hard constraints -> Pareto -> weighted scoring -> recommendation.

Definition of "optimal" (see report s.1): the route that minimises a profile-weighted sum of
four normalised criteria, among routes that satisfy the shipment's hard constraints
(budget and a chance constraint P(on time) >= profile threshold):

    cost     expected landed cost = freight + E[delay days] * delay-cost-rate * TEU
    time     expected transit days (nominal + E[delay])
    spread   P90 - P50 transit days (how unpredictable the route is)
    exposure structural geopolitical/congestion exposure of the lanes and hubs (0-1)

Only *_est columns are read here.  Ground truth is never visible to the decision system.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config as C
from .simulate import simulate_delay

N_SIMS = 2000


@dataclass
class RouteMetrics:
    route_id: str
    path: list
    mode: str
    freight: float
    nominal_days: float
    exp_delay: float
    exp_days: float
    p50: float
    p90: float
    spread: float
    p_delay: float          # P(delay >= 1 day)
    p_on_time: float        # P(arrive by deadline)
    exposure: float
    exp_cost: float         # freight + expected delay cost
    delay_cost_rate: float  # USD/day for the whole shipment
    violations: list = field(default_factory=list)
    dominated_by: str | None = None
    score: float = float("nan")
    contrib: dict = field(default_factory=dict)

    @property
    def path_str(self):
        return " → ".join(self.path) + f" ({self.mode})"


def _seed(route_id: str, seed: int) -> int:
    return (zlib.crc32(route_id.encode()) ^ seed) & 0xFFFFFFFF


def route_arrays(legs: pd.DataFrame, params: str = "est"):
    """Extract per-leg arrays. params='est' (decision) or 'true' (evaluation only)."""
    sfx = "_est" if params == "est" else "_true"
    return dict(
        p=legs["p_delay" + sfx].to_numpy(), mu=legs["mean_delay" + sfx].to_numpy(),
        geo=legs["geo" + sfx].to_numpy(), cong=legs["congestion" + sfx].to_numpy(),
    )


def exposure_index(geo, cong) -> float:
    """Structural exposure: 1 - prod(1 - 0.5*(0.6*geo + 0.4*cong)). More legs/riskier lanes -> higher."""
    r = 0.5 * (0.6 * np.asarray(geo) + 0.4 * np.asarray(cong))
    return float(1 - np.prod(1 - r))


def compute_metrics(shipment, route_legs: pd.DataFrame, n_sims: int = N_SIMS, seed: int = 0,
                    params: str = "est", uncertainty: bool = True, perturb: dict | None = None) -> RouteMetrics:
    """Metrics for one route. `perturb` (p_mult, mu_mult arrays) is used for input-sensitivity runs."""
    rid = route_legs["route_id"].iloc[0]
    a = route_arrays(route_legs, params)
    p, mu = a["p"].copy(), a["mu"].copy()
    if perturb:
        p = np.clip(p * perturb["p"], 0.005, 0.9)
        mu = mu * perturb["mu"]
    teu, rate = shipment["teu"], shipment["delay_cost_per_day_per_teu"] * shipment["teu"]
    nominal = float(route_legs["days"].sum())
    freight = float(route_legs["cost_per_teu"].sum() * teu)
    if uncertainty:
        d = simulate_delay(p, mu, a["geo"], n_sims, np.random.default_rng(_seed(rid, seed)))
    else:                                                   # deterministic ablation: no delay model
        d = np.zeros(1)
    tot = nominal + d
    p50, p90 = np.percentile(tot, [50, 90])
    path = [route_legs["origin_node"].iloc[0]] + list(route_legs["dest_node"])
    return RouteMetrics(
        route_id=rid, path=path, mode=route_legs["mode"].iloc[0], freight=freight, nominal_days=nominal,
        exp_delay=float(d.mean()), exp_days=float(tot.mean()), p50=float(p50), p90=float(p90),
        spread=float(p90 - p50), p_delay=float((d >= 1).mean()), p_on_time=float((tot <= shipment["deadline_days"]).mean()),
        exposure=exposure_index(a["geo"], a["cong"]), exp_cost=freight + float(d.mean()) * rate, delay_cost_rate=rate,
    )


# ------------------------------------------------------------------ constraints / pareto / score
def apply_constraints(ms: list, shipment, min_on_time: float):
    for m in ms:
        m.violations = []
        if m.freight > shipment["budget_usd"]:
            m.violations.append(("budget", m.freight, shipment["budget_usd"]))
        if m.p_on_time < min_on_time:
            m.violations.append(("deadline", m.p_on_time, min_on_time))


def pareto_mark(ms: list):
    """Mark routes dominated on (exp_cost, exp_days, spread, exposure); all minimised."""
    key = lambda m: np.array([m.exp_cost, m.exp_days, m.spread, m.exposure])
    for m in ms:
        m.dominated_by = None
        for o in ms:
            if o is not m and np.all(key(o) <= key(m)) and np.any(key(o) < key(m)):
                m.dominated_by = o.route_id
                break


def normalise(ms: list) -> dict:
    """Min-max over the candidate set with a floor on the range (see config.NORM_FLOOR)."""
    out = {}
    for k, attr in dict(cost="exp_cost", time="exp_days", spread="spread", exposure="exposure").items():
        v = np.array([getattr(m, attr) for m in ms])
        floor = C.NORM_FLOOR[k] * (v.min() if k in ("cost", "time") else 1.0)
        out[k] = (v - v.min()) / max(v.max() - v.min(), floor, 1e-9)
    return out


def score_routes(ms: list, weights: dict):
    norm = normalise(ms)
    for i, m in enumerate(ms):
        m.contrib = {k: weights[k] * float(norm[k][i]) for k in C.CRITERIA}
        m.score = sum(m.contrib.values())


def weights_for(profile: str, override: dict | None = None) -> dict:
    w = {k: C.PROFILES[profile][k] for k in C.CRITERIA}
    if override:
        w.update(override)
    s = sum(w.values())
    return {k: v / s for k, v in w.items()}


@dataclass
class Recommendation:
    shipment: dict
    weights: dict
    min_on_time: float
    metrics: list                 # all routes, scored
    candidates: list              # routes eligible (feasible, or relaxed set)
    chosen: RouteMetrics
    relaxed: str | None           # None, "deadline" or "budget+deadline"
    stability: dict = field(default_factory=dict)


RELAX_TOL = 0.10   # best-effort mode: keep routes within 10 pp of the best achievable P(on time)


def choose(ms: list, weights: dict, shipment, min_on_time: float):
    """Return (chosen, candidate_set, relaxed_flag). Scores are computed on the candidate set.

    Normal case : candidates = routes satisfying budget AND P(on time) >= threshold.
    Fallback    : if none does, never return nothing.  Keep budget-compliant routes (all routes if none
                  are) and, among them, only those within RELAX_TOL of the best achievable P(on time);
                  i.e. get as close to the deadline requirement as possible, then use the weighted score.
    """
    apply_constraints(ms, shipment, min_on_time)
    feas = [m for m in ms if not m.violations]
    relaxed = None
    if not feas:
        within = [m for m in ms if not any(v[0] == "budget" for v in m.violations)]
        relaxed = "deadline" if within else "budget+deadline"
        pool = within or list(ms)
        best_p = max(m.p_on_time for m in pool)
        feas = [m for m in pool if m.p_on_time >= best_p - RELAX_TOL]
    score_routes(feas, weights)
    chosen = min(feas, key=lambda m: m.score)
    return chosen, feas, relaxed


def recommend(shipment, legs: pd.DataFrame, weights: dict | None = None, profile: str | None = None,
              n_sims: int = N_SIMS, seed: int = 0, uncertainty: bool = True) -> Recommendation:
    """Main entry point: shipment (Series/dict) + legs table -> Recommendation."""
    shipment = dict(shipment)
    profile = profile or shipment["profile"]
    w = weights_for(profile, weights)
    min_on_time = C.PROFILES[profile]["min_on_time"]
    sub = legs[legs.shipment_id == shipment["shipment_id"]]
    ms = [compute_metrics(shipment, g.sort_values("leg_idx"), n_sims, seed, "est", uncertainty)
          for _, g in sub.groupby("route_id", sort=True)]
    pareto_mark(ms)
    chosen, cands, relaxed = choose(ms, w, shipment, min_on_time)
    ranked = sorted(cands, key=lambda m: m.score)
    return Recommendation(shipment, w, min_on_time, ms, ranked, chosen, relaxed)
