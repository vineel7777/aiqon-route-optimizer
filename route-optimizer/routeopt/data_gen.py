"""Synthetic dataset generator.

Produces two CSVs in data/:
  shipments.csv : one row per shipment (origin, destination, cargo, profile, deadline, budget)
  legs.csv      : one row per leg of every candidate route (3-5 routes per shipment)

Construction (see report, section 2):
  1. Candidate routes are enumerated on a port graph (sea lanes via transshipment hubs + optional
     direct air), then 3-5 *diverse* ones are kept: cheapest, fastest, lowest-risk, air, + random.
     This guarantees genuine trade-offs (cheap-slow-risky vs. fast-expensive vs. balanced).
  2. Every leg has hidden GROUND-TRUTH parameters (*_true) and noisy ESTIMATES (*_est).
     The decision system only ever reads *_est; evaluate.py uses *_true to simulate outcomes.
  3. Deadline and budget are calibrated per shipment from its own route set, so some shipments
     have tight deadlines, some tight budgets and a few are genuinely infeasible.
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _adjacency():
    adj = defaultdict(list)
    for a, b, d, c, p, g in C.SEA_EDGES:
        adj[a].append((b, d, c, p, g))
        adj[b].append((a, d, c, p, g))
    return adj


def _enumerate_sea_paths(origin, dest, adj, max_legs=4):
    """All simple paths origin -> dest whose intermediate nodes are transshipment hubs."""
    out = []

    def dfs(node, path):
        if len(path) - 1 >= max_legs:
            return
        for nxt, *_ in adj[node]:
            if nxt in path:
                continue
            if nxt == dest:
                out.append(path + [nxt])
            elif nxt in C.HUBS:
                dfs(nxt, path + [nxt])

    dfs(origin, [origin])
    return out


def _edge(a, b):
    for x, y, d, c, p, g in C.SEA_EDGES:
        if {x, y} == {a, b}:
            return d, c, p, g
    raise KeyError((a, b))


def _static_stats(path):
    """Nominal (noise-free) days/cost/risk of a sea path, used only for choosing candidates."""
    days = cost = 0.0
    risk_surv = 1.0
    for i, (a, b) in enumerate(zip(path[:-1], path[1:])):
        d, c, p, g = _edge(a, b)
        cong = C.NODES[b][2]
        days += d + (C.NODES[b][3] if b in C.HUBS else 0)
        cost += c + (C.NODES[b][4] if b in C.HUBS else 0)
        risk_surv *= 1 - 0.5 * (0.6 * g + 0.4 * cong)
    return days, cost, 1 - risk_surv


def _candidate_routes(origin, dest, air_ok, rng, n_target):
    adj = _adjacency()
    paths = _enumerate_sea_paths(origin, dest, adj)
    stats = {tuple(p): _static_stats(p) for p in paths}
    best = min(s[0] for s in stats.values())
    for factor in (1.6, 2.2, 5.0):                     # prune silly detours, relax if too few remain
        keep = [p for p in paths if stats[tuple(p)][0] <= factor * best]
        if len(keep) >= 3 or factor == 5.0:
            break
    chosen: list[tuple] = []

    def add(p):
        if p is not None and tuple(p) not in [tuple(c) for c in chosen]:
            chosen.append(tuple(p))

    add(min(keep, key=lambda p: stats[tuple(p)][1]))      # cheapest
    add(min(keep, key=lambda p: stats[tuple(p)][0]))      # fastest sea
    add(min(keep, key=lambda p: stats[tuple(p)][2]))      # lowest structural risk
    rest = [p for p in keep if tuple(p) not in chosen]
    rng.shuffle(rest)
    sea_target = n_target - (1 if air_ok else 0)
    for p in rest:
        if len(chosen) >= sea_target:
            break
        add(p)
    chosen = chosen[: max(sea_target, 3 if not air_ok else 2)]
    routes = [(list(p), "sea") for p in chosen]
    if air_ok:
        routes.append(([origin, dest], "air"))
    return routes


def _build_legs(shipment_id, route_id, path, mode, rng, season, geo_season):
    rows = []
    for i, (a, b) in enumerate(zip(path[:-1], path[1:])):
        intermediate = b in C.HUBS
        if mode == "sea":
            d, c, p0, g0 = _edge(a, b)
            cong0 = C.NODES[b][2]
        else:
            d, c = C.AIR["US" if b in C.US_DESTS else "EU"]
            p0, g0 = C.AIR_BASE_P, C.AIR_GEO
            cong0 = C.NODES[b][2] * 0.4
        # ground truth for this shipment (date/season specific)
        cong_t = float(np.clip(cong0 * season[b], 0.02, 0.95))
        geo_t = float(np.clip(g0 * geo_season[(a, b)], 0.0, 0.95))
        p_t = float(np.clip(p0 + C.P_CONG_COEF * cong_t + C.P_GEO_COEF * geo_t, 0.02, 0.60))
        if mode == "sea":
            mu_t = C.MU_BASE + C.MU_CONG * cong_t + C.MU_GEO * geo_t
        else:
            mu_t = C.AIR_MU_BASE + C.AIR_MU_CONG * cong_t
        dwell = C.NODES[b][3] * (1 + cong_t) if intermediate else 0.0
        handling = C.NODES[b][4] if intermediate else 0
        cost = (c * (1 + 0.10 * cong_t) + handling) * rng.uniform(0.97, 1.05)
        # estimates the planner sees (noisy, unbiased in log-space)
        p_e = float(np.clip(p_t * rng.lognormal(0, C.EST_NOISE_P), 0.01, 0.70))
        mu_e = float(mu_t * rng.lognormal(0, C.EST_NOISE_MU))
        cong_e = float(np.clip(cong_t + rng.normal(0, C.EST_NOISE_INDEX), 0, 1))
        geo_e = float(np.clip(geo_t + rng.normal(0, C.EST_NOISE_INDEX), 0, 1))
        rows.append(dict(
            shipment_id=shipment_id, route_id=route_id, leg_idx=i, origin_node=a, dest_node=b, mode=mode,
            cost_per_teu=round(cost, 2), days=round(d + dwell, 2),
            p_delay_est=round(p_e, 4), mean_delay_est=round(mu_e, 3), congestion_est=round(cong_e, 3), geo_est=round(geo_e, 3),
            p_delay_true=round(p_t, 4), mean_delay_true=round(mu_t, 3), congestion_true=round(cong_t, 3), geo_true=round(geo_t, 3),
        ))
    return rows


def generate(n_shipments: int = C.N_SHIPMENTS, seed: int = C.SEED, write: bool = True):
    rng = np.random.default_rng(seed)
    types = list(C.CARGO)
    shares = np.array([C.CARGO[t]["share"] for t in types])
    ship_rows, leg_rows = [], []
    for k in range(1, n_shipments + 1):
        sid = f"SHP-{k:03d}"
        origin, dest = rng.choice(C.ORIGINS), rng.choice(C.DESTS)
        ctype = str(rng.choice(types, p=shares / shares.sum()))
        spec = C.CARGO[ctype]
        profile = spec["profile"]
        if ctype == "standard" and rng.random() < 0.20:
            profile = "urgent"                                  # some standard cargo is rush
        teu = int(rng.integers(1, 9))
        n_routes = int(rng.integers(3, 6))                      # 3-5 route options
        routes = _candidate_routes(origin, dest, spec["air"] and rng.random() < 0.8, rng, n_routes)
        season = {n: float(rng.uniform(0.8, 1.3)) for n in C.NODES}
        geo_season = defaultdict(lambda: float(rng.uniform(0.8, 1.25)))
        nominal, freight = [], []
        for j, (path, mode) in enumerate(routes):
            rid = f"{sid}-R{j + 1}"
            legs = _build_legs(sid, rid, path, mode, rng, season, geo_season)
            leg_rows.extend(legs)
            nominal.append((mode, sum(l["days"] for l in legs)))
            freight.append(sum(l["cost_per_teu"] for l in legs) * teu)
        sea_days = [d for m, d in nominal if m == "sea"]
        sea_ref = min(sea_days) + 4.0                          # fastest sea route + typical delay allowance
        cheapest = min(freight)
        air_fr = [f for (m, _), f in zip(nominal, freight) if m == "air"]
        fly_it = bool(air_fr) and ((profile == "urgent" and rng.random() < 0.5) or (profile == "high_value" and rng.random() < 0.3))
        if fly_it:                                             # shipper is willing to pay for air
            dl, bd = rng.uniform(6, 14), min(air_fr) * rng.uniform(1.1, 1.6)
        elif profile == "urgent":                              # expedited sea: tight deadline, modest budget
            dl, bd = sea_ref * rng.uniform(0.95, 1.3), cheapest * rng.uniform(1.5, 3.0)
        elif profile == "high_value":
            dl, bd = sea_ref * rng.uniform(1.15, 1.7), cheapest * rng.uniform(1.5, 4.0)
        elif profile == "cost_sensitive":
            dl, bd = sea_ref * rng.uniform(1.25, 1.8), cheapest * rng.uniform(1.15, 1.6)
        else:
            dl, bd = sea_ref * rng.uniform(1.1, 1.6), cheapest * rng.uniform(1.3, 2.5)
        ship_rows.append(dict(
            shipment_id=sid, origin=origin, destination=dest, teu=teu, cargo_type=ctype, profile=profile,
            cargo_value_per_teu=spec["value"], delay_cost_per_day_per_teu=spec["delay_cost"],
            deadline_days=int(math.ceil(dl)), budget_usd=int(round(bd, -1)),
            n_routes=len(routes),
        ))
    ships, legs = pd.DataFrame(ship_rows), pd.DataFrame(leg_rows)
    if write:
        DATA_DIR.mkdir(exist_ok=True)
        ships.to_csv(DATA_DIR / "shipments.csv", index=False)
        legs.to_csv(DATA_DIR / "legs.csv", index=False)
    return ships, legs


def load(data_dir: Path = DATA_DIR):
    return pd.read_csv(data_dir / "shipments.csv"), pd.read_csv(data_dir / "legs.csv")


if __name__ == "__main__":
    s, l = generate()
    print(f"{len(s)} shipments, {l.route_id.nunique()} routes, {len(l)} legs -> {DATA_DIR}")
