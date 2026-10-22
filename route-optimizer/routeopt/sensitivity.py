"""Sensitivity / stability analysis of a recommendation.

Three complementary views (all reported to the operator):
  1. weight stability : Dirichlet-perturb the profile weights; how often does the same route win?
  2. flip thresholds  : how far must a single weight move before the winner changes?
  3. data stability   : perturb the delay-probability / delay-duration ESTIMATES (lognormal, sigma=0.3),
                        re-run Monte Carlo and the full constraint+score pipeline; how often is the
                        recommendation unchanged?  (captures uncertainty in the delay estimates)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from . import scoring as S


def _norm_matrix(ms):
    n = S.normalise(ms)
    return np.vstack([n[k] for k in C.CRITERIA])           # (K, R)


def weight_stability(rec: S.Recommendation, n: int = 1000, alpha: float = 60.0, seed: int = 0) -> dict:
    ms = rec.candidates
    N = _norm_matrix(ms)
    w0 = np.array([rec.weights[k] for k in C.CRITERIA])
    W = np.random.default_rng(seed).dirichlet(alpha * w0, size=n)
    wins = np.argmin(W @ N, axis=1)
    freq = {ms[i].route_id: float((wins == i).mean()) for i in range(len(ms))}
    return {"freq": freq, "stability": freq[rec.chosen.route_id]}


def flip_thresholds(rec: S.Recommendation) -> list:
    """For each criterion, nearest weight value (others rescaled proportionally) where the winner changes."""
    ms = rec.candidates
    N = _norm_matrix(ms)
    w0 = np.array([rec.weights[k] for k in C.CRITERIA])
    chosen_idx = [m.route_id for m in ms].index(rec.chosen.route_id)
    out = []
    for k, name in enumerate(C.CRITERIA):
        best = None
        for w_k in np.round(np.arange(0.0, 1.0001, 0.01), 2):
            if abs(w_k - w0[k]) < 1e-9:
                continue
            w = w0 * (1 - w_k) / (1 - w0[k])
            w[k] = w_k
            win = int(np.argmin(w @ N))
            if win != chosen_idx:
                d = abs(w_k - w0[k])
                if best is None or d < best["delta"]:
                    best = dict(criterion=name, from_w=float(w0[k]), to_w=float(w_k), delta=float(d),
                                new_route=ms[win].route_id, direction="up" if w_k > w0[k] else "down")
        if best:
            out.append(best)
    return sorted(out, key=lambda d: d["delta"])


def data_stability(rec: S.Recommendation, legs: pd.DataFrame, n: int = 60, sigma: float = 0.3,
                   n_sims: int = 400, seed: int = 0) -> dict:
    """Perturb delay estimates, redo MC + constraints + scoring, count how often the winner is unchanged."""
    sh, rng = rec.shipment, np.random.default_rng(seed)
    sub = legs[legs.shipment_id == sh["shipment_id"]]
    groups = {rid: g.sort_values("leg_idx") for rid, g in sub.groupby("route_id")}
    wins: dict = {}
    for t in range(n):
        ms = []
        for rid, g in groups.items():
            L = len(g)
            pert = dict(p=rng.lognormal(0, sigma, L), mu=rng.lognormal(0, sigma, L))
            ms.append(S.compute_metrics(sh, g, n_sims, seed=1000 + t, perturb=pert))
        win, _, _ = S.choose(ms, rec.weights, sh, rec.min_on_time)
        wins[win.route_id] = wins.get(win.route_id, 0) + 1
    freq = {k: v / n for k, v in wins.items()}
    return {"freq": freq, "stability": freq.get(rec.chosen.route_id, 0.0)}


def assess(rec: S.Recommendation, legs: pd.DataFrame, n_data: int = 60, seed: int = 0) -> S.Recommendation:
    ws = weight_stability(rec, seed=seed)
    ds = data_stability(rec, legs, n=n_data, seed=seed)
    flips = flip_thresholds(rec)
    st = min(ws["stability"], ds["stability"])
    rec.stability = dict(weight=ws, data=ds, flips=flips, overall=st,
                         label="robust" if st >= 0.8 else "moderate" if st >= 0.6 else "close call")
    return rec
