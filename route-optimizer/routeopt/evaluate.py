"""Evaluation: compare the system with baselines against SIMULATED GROUND TRUTH.

Ground truth: for every route we simulate outcomes with the hidden *_true parameters (4000 draws).
Realised loss to the shipper (independent of the scoring weights, so the test is not circular):

    loss = freight + delay_cost_rate * delay_days            (cost of delay: spoilage, stock-outs, ...)
                   + holding_rate  * total_days              (capital tied up in transit)
                   + 3 * delay_cost_rate * days_late         (contractual lateness fee beyond deadline)

Policies compared (all see only *_est data):
  ours          : constraints + Monte-Carlo metrics + profile-weighted score   (this project)
  ours_det      : same but NO uncertainty model (nominal days, no delay risk)  (ablation)
  cheapest      : min freight          fastest : min nominal transit days
  lowest_risk   : min exposure index   random  : expected value over uniformly random route choice
Regret = (loss of chosen route - loss of best route in hindsight) / loss of best route.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from . import scoring as S
from . import sensitivity as SE
from .explain import explain
from .simulate import simulate_delay

OUT = Path(__file__).resolve().parent.parent / "outputs"
N_TRUE = 4000


def true_outcomes(shipment, route_legs, n=N_TRUE, seed=777) -> dict:
    a = S.route_arrays(route_legs, "true")
    rid = route_legs["route_id"].iloc[0]
    rng = np.random.default_rng(S._seed(rid, seed))
    d = simulate_delay(a["p"], a["mu"], a["geo"], n, rng)
    teu = shipment["teu"]
    rate = shipment["delay_cost_per_day_per_teu"] * teu
    hold = teu * shipment["cargo_value_per_teu"] * C.HOLDING_RATE_ANNUAL / 365
    nominal = float(route_legs["days"].sum())
    freight = float(route_legs["cost_per_teu"].sum() * teu)
    tot = nominal + d
    late = np.maximum(0, tot - shipment["deadline_days"])
    loss = freight + rate * d + hold * tot + C.LATE_FEE_MULT * rate * late
    return dict(loss=float(loss.mean()), p_on_time=float((tot <= shipment["deadline_days"]).mean()),
                days=float(tot.mean()), p90=float(np.percentile(tot, 90)), freight=freight)


def run(shipments: pd.DataFrame, legs: pd.DataFrame, n_stability: int = 60, verbose: bool = True) -> dict:
    OUT.mkdir(exist_ok=True)
    (OUT / "figures").mkdir(exist_ok=True)
    rows, recs, explanations = [], [], []
    for _, sh in shipments.iterrows():
        sid = sh["shipment_id"]
        rec = S.recommend(sh, legs)
        det = S.recommend(sh, legs, uncertainty=False)
        SE.assess(rec, legs, n_data=n_stability)
        recs.append(rec)
        explanations.append(explain(rec))
        truth = {rid: true_outcomes(sh, g.sort_values("leg_idx"))
                 for rid, g in legs[legs.shipment_id == sid].groupby("route_id")}
        ms = rec.metrics
        picks = {
            "ours": rec.chosen.route_id,
            "ours_det": det.chosen.route_id,
            "cheapest": min(ms, key=lambda m: m.freight).route_id,
            "fastest": min(ms, key=lambda m: m.nominal_days).route_id,
            "lowest_risk": min(ms, key=lambda m: m.exposure).route_id,
        }
        best_loss = min(t["loss"] for t in truth.values())
        best_id = min(truth, key=lambda r: truth[r]["loss"])
        cheapest_fr = min(t["freight"] for t in truth.values())
        pol = dict(picks)
        for name, rid in list(pol.items()) + [("random", None)]:
            if rid is None:                                          # expected value of uniform random choice
                vals = list(truth.values())
                loss = np.mean([v["loss"] for v in vals]); pot = np.mean([v["p_on_time"] for v in vals])
                fr = np.mean([v["freight"] for v in vals]); days = np.mean([v["days"] for v in vals])
                p90 = np.mean([v["p90"] for v in vals])
                bv = np.mean([v["freight"] > sh["budget_usd"] for v in vals]); match = 1 / len(vals)
                ok = np.mean([(v["p_on_time"] >= rec.min_on_time) and (v["freight"] <= sh["budget_usd"]) for v in vals])
            else:
                t = truth[rid]
                loss, pot, fr, days, p90 = t["loss"], t["p_on_time"], t["freight"], t["days"], t["p90"]
                bv = float(fr > sh["budget_usd"]); match = float(rid == best_id)
                ok = float((pot >= rec.min_on_time) and (fr <= sh["budget_usd"]))
            rows.append(dict(shipment_id=sid, profile=sh["profile"], policy=name, loss=loss,
                             regret_pct=100 * (loss - best_loss) / best_loss, oracle_match=match, true_p_on_time=pot,
                             freight=fr, freight_vs_cheapest_pct=100 * (fr / cheapest_fr - 1), exp_days=days, p90_days=p90,
                             budget_violation=bv, meets_requirements=ok,
                             stability=rec.stability["overall"] if name == "ours" else np.nan,
                             relaxed=rec.relaxed is not None))
        if verbose:
            print(f"  {sid}: {rec.chosen.route_id} (stability {rec.stability['overall']:.0%}, {rec.stability['label']})")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "evaluation_per_shipment.csv", index=False)

    agg = df.groupby("policy").agg(
        mean_regret_pct=("regret_pct", "mean"), median_regret_pct=("regret_pct", "median"),
        oracle_match=("oracle_match", "mean"), mean_true_p_on_time=("true_p_on_time", "mean"),
        meets_requirements=("meets_requirements", "mean"), budget_violation=("budget_violation", "mean"),
        freight_vs_cheapest_pct=("freight_vs_cheapest_pct", "mean"), mean_days=("exp_days", "mean"), mean_p90=("p90_days", "mean"),
    ).reindex(["ours", "ours_det", "cheapest", "fastest", "lowest_risk", "random"])
    agg.to_csv(OUT / "evaluation_summary.csv")
    by_prof = df[df.policy.isin(["ours", "cheapest", "fastest"])].pivot_table(
        index="profile", columns="policy", values="regret_pct", aggfunc="mean")
    by_prof.to_csv(OUT / "evaluation_by_profile.csv")

    # ---- stability vs regret, profile sensitivity, constraint handling
    ours = df[df.policy == "ours"].copy()
    ours["label"] = pd.cut(ours.stability, [-1, 0.6, 0.8, 1.01], labels=["close call", "moderate", "robust"])
    stab = ours.groupby("label", observed=True).agg(n=("regret_pct", "size"), mean_regret_pct=("regret_pct", "mean")).reset_index()
    switch = _profile_switch_rate(shipments, legs)
    pareto_frac = float(np.mean([np.mean([m.dominated_by is not None for m in r.metrics]) for r in recs]))
    # ours without hard constraints? (shows what the constraint layer buys)
    res = dict(
        n_shipments=len(shipments), n_routes=int(legs.route_id.nunique()),
        summary=agg.round(3).reset_index().to_dict("records"), by_profile=by_prof.round(2).reset_index().to_dict("records"),
        stability=dict(mean=float(ours.stability.mean()), share_robust=float((ours.stability >= 0.8).mean()),
                       share_close=float((ours.stability < 0.6).mean()), vs_regret=stab.round(2).to_dict("records")),
        profile_switch_rate=switch, relaxed_count=int(sum(r.relaxed is not None for r in recs)),
        pareto_dominated_share=pareto_frac,
        decision_mix=_decision_mix(recs),
    )
    json.dump(res, open(OUT / "results.json", "w"), indent=2, default=float)
    _write_recommendations(recs)
    (OUT / "explanations.txt").write_text(("\n\n" + "=" * 100 + "\n\n").join(explanations))
    _figures(df, agg, recs, ours)
    return res


def _decision_mix(recs):
    mix = dict(cheapest=0, fastest=0, air=0, balanced_other=0)
    for r in recs:
        ch = r.chosen
        if ch.mode == "air":
            mix["air"] += 1
        elif ch.route_id == min(r.metrics, key=lambda m: m.freight).route_id:
            mix["cheapest"] += 1
        elif ch.route_id == min(r.metrics, key=lambda m: m.exp_days).route_id:
            mix["fastest"] += 1
        else:
            mix["balanced_other"] += 1
    return mix


def _profile_switch_rate(shipments, legs) -> dict:
    """Fraction of shipments whose recommended route changes when a different profile is applied."""
    profs = list(C.PROFILES)
    res = {}
    base = {}
    for p in profs:
        base[p] = {sh["shipment_id"]: S.recommend(sh, legs, profile=p).chosen.route_id for _, sh in shipments.iterrows()}
    for i, a in enumerate(profs):
        for b in profs[i + 1:]:
            res[f"{a}~{b}"] = float(np.mean([base[a][k] != base[b][k] for k in base[a]]))
    res["mean"] = float(np.mean(list(res.values())))
    return res


def _write_recommendations(recs):
    rows = []
    for r in recs:
        c, sh = r.chosen, r.shipment
        cheap = min(r.metrics, key=lambda m: m.freight)
        rows.append(dict(
            shipment_id=sh["shipment_id"], profile=sh["profile"], cargo=sh["cargo_type"], deadline=sh["deadline_days"],
            budget=sh["budget_usd"], chosen_route=c.route_id, path=c.path_str, freight=round(c.freight),
            premium_vs_cheapest_pct=round(100 * (c.freight / cheap.freight - 1), 1), exp_days=round(c.exp_days, 1),
            p90_days=round(c.p90, 1), p_delay=round(c.p_delay, 3), p_on_time=round(c.p_on_time, 3),
            constraints_relaxed=r.relaxed or "", weight_stability=round(r.stability["weight"]["stability"], 3),
            data_stability=round(r.stability["data"]["stability"], 3), robustness=r.stability["label"]))
    pd.DataFrame(rows).to_csv(OUT / "recommendations.csv", index=False)


def _figures(df, agg, recs, ours):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    names = {"ours": "Ours", "ours_det": "Ours\n(no uncertainty)", "cheapest": "Cheapest", "fastest": "Fastest",
             "lowest_risk": "Lowest\nrisk", "random": "Random"}
    cols = ["#1f6f8b" if k == "ours" else "#9aa5b1" for k in agg.index]
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.1))
    ax[0].bar([names[k] for k in agg.index], agg.mean_regret_pct, color=cols)
    ax[0].set_ylabel("Mean regret vs. hindsight-best (%)"); ax[0].set_title("Decision quality (lower is better)", fontsize=10)
    ax[1].bar([names[k] for k in agg.index], 100 * agg.meets_requirements, color=cols)
    ax[1].set_ylabel("Shipments meeting budget + on-time\nrequirement (true outcomes, %)"); ax[1].set_title("Constraint satisfaction (higher is better)", fontsize=10)
    for a in ax:
        a.tick_params(axis="x", labelsize=7.5); a.spines[["top", "right"]].set_visible(False)
    plt.tight_layout(); plt.savefig(OUT / "figures/fig_policy_comparison.png", dpi=200); plt.close()

    # illustrative shipment: system pays a freight premium over the cheapest route for lower worst-case delay
    def interesting(r):
        ch, ch0 = r.chosen, min(r.metrics, key=lambda m: m.freight)
        return (len(r.metrics) >= 4 and r.relaxed is None and ch.freight > 1.03 * ch0.freight and ch.p90 < ch0.p90 - 2
                and ch.mode == "sea" and max(m.freight for m in r.metrics) < 2.5 * ch.freight)
    pick = next((r for r in recs if interesting(r)), next((r for r in recs if len(r.metrics) >= 4), recs[0]))
    fig, ax = plt.subplots(figsize=(4.8, 3.4))
    for m in pick.metrics:
        excl = m not in pick.candidates
        col = "#c0392b" if excl else "#1f6f8b"
        ax.hlines(m.freight, m.p50, m.p90, color=col, lw=1.6, alpha=0.7, zorder=1)
        ax.scatter(m.exp_days, m.freight, s=50 + 500 * m.exposure, alpha=0.6 if not excl else 0.3,
                   color=col, edgecolor="k", linewidth=0.5, zorder=2)
        ax.annotate(m.route_id[-2:] + (" (excluded)" if excl else ""), (m.p90, m.freight), xytext=(5, -3),
                    textcoords="offset points", fontsize=8)
    c = pick.chosen
    ax.scatter(c.exp_days, c.freight, marker="*", s=280, color="#f1c40f", edgecolor="k", zorder=3)
    ax.set_xlabel("Transit days: dot = expected, line = P50 to P90"); ax.set_ylabel("Freight cost (USD)")
    ax.set_title(f"{pick.shipment['shipment_id']} ({pick.shipment['profile']}): star = recommended\n"
                 f"bubble size = exposure" + ("; red = excluded" if any(m not in pick.candidates for m in pick.metrics) else ""), fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout(); plt.savefig(OUT / "figures/fig_tradeoff_example.png", dpi=200); plt.close()

    fig, ax = plt.subplots(figsize=(4.2, 3.3))
    ax.hist(ours.stability, bins=np.linspace(0, 1, 11), color="#1f6f8b", edgecolor="white")
    ax.axvline(0.8, ls="--", color="k", lw=0.8); ax.axvline(0.6, ls=":", color="k", lw=0.8)
    ax.set_xlabel("Decision stability (min of weight / data perturbation)"); ax.set_ylabel("Shipments")
    ax.set_title("How robust are the recommendations?", fontsize=9); ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout(); plt.savefig(OUT / "figures/fig_stability.png", dpi=200); plt.close()
    (OUT / "figures" / "example_shipment.txt").write_text(pick.shipment["shipment_id"])


def multi_seed(n_seeds: int = 10, verbose: bool = True) -> pd.DataFrame:
    """Repeat the policy comparison on independent synthetic datasets (different seeds) to check
    that conclusions are not an artefact of one random draw. Stability analysis is skipped for speed."""
    from . import data_gen
    recs = []
    for seed in range(1, n_seeds + 1):
        ships, legs = data_gen.generate(seed=seed, write=False)
        rows = []
        for _, sh in ships.iterrows():
            rec, det = S.recommend(sh, legs), S.recommend(sh, legs, uncertainty=False)
            truth = {rid: true_outcomes(sh, g.sort_values("leg_idx")) for rid, g in legs[legs.shipment_id == sh["shipment_id"]].groupby("route_id")}
            best = min(t["loss"] for t in truth.values())
            ms = rec.metrics
            picks = {"ours": rec.chosen.route_id, "ours_det": det.chosen.route_id,
                     "cheapest": min(ms, key=lambda m: m.freight).route_id, "fastest": min(ms, key=lambda m: m.nominal_days).route_id,
                     "lowest_risk": min(ms, key=lambda m: m.exposure).route_id}
            for name, rid in picks.items():
                t = truth[rid]
                rows.append(dict(seed=seed, policy=name, regret_pct=100 * (t["loss"] - best) / best,
                                 meets=float(t["p_on_time"] >= rec.min_on_time and t["freight"] <= sh["budget_usd"]),
                                 feasible=float(rec.relaxed is None)))
        recs.append(pd.DataFrame(rows))
        if verbose:
            print(f"  seed {seed} done")
    df = pd.concat(recs)
    per_seed = df.groupby(["seed", "policy"]).agg(regret=("regret_pct", "mean"), meets=("meets", "mean")).reset_index()
    out = per_seed.groupby("policy").agg(mean_regret_pct=("regret", "mean"), sd_regret_pct=("regret", "std"),
                                         mean_meets=("meets", "mean")).reindex(["ours", "ours_det", "cheapest", "fastest", "lowest_risk"])
    feas = df[df.policy == "ours"].groupby("seed").feasible.mean().mean()
    out.attrs["feasible_share"] = feas
    wins = per_seed.pivot(index="seed", columns="policy", values="regret")
    out["ours_better_in_n_seeds"] = [(wins["ours"] < wins[p]).sum() if p != "ours" else np.nan for p in out.index]
    out.to_csv(OUT / "multiseed_summary.csv")
    json.dump(dict(n_seeds=n_seeds, feasible_share=float(feas), table=out.round(3).reset_index().to_dict("records")),
              open(OUT / "multiseed.json", "w"), indent=2, default=float)
    return out
