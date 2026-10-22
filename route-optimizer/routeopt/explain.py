"""Operator-facing explanations, generated from the numbers (no hand-written justifications)."""
from __future__ import annotations

from . import config as C
from .scoring import Recommendation, RouteMetrics

NICE = dict(cost="expected landed cost", time="expected transit time",
            spread="schedule predictability (P90-P50 spread)", exposure="geopolitical/congestion exposure")


def _usd(x):
    return f"${x:,.0f}"


def _pct(a, b):
    return 100 * (a - b) / b if b else 0.0


def _label(m: RouteMetrics, rec: Recommendation):
    tags = []
    cands = rec.candidates
    if m.route_id == min(rec.metrics, key=lambda x: x.freight).route_id:
        tags.append("cheapest")
    if m.route_id == min(rec.metrics, key=lambda x: x.exp_days).route_id:
        tags.append("fastest")
    if m.route_id == min(rec.metrics, key=lambda x: x.exposure).route_id:
        tags.append("lowest exposure")
    return ", ".join(tags)


def _compare(a: RouteMetrics, b: RouteMetrics, rec: Recommendation, ref_name: str) -> str:
    """Sentence: chosen route `a` versus reference route `b` (only material differences are mentioned)."""
    dfr, dd, dp = a.freight - b.freight, a.exp_days - b.exp_days, a.p_delay - b.p_delay
    parts = []
    if abs(dfr) >= 1:
        parts.append(f"costs {_usd(abs(dfr))} ({abs(_pct(a.freight, b.freight)):.0f}%) {'more' if dfr > 0 else 'less'} in freight")
    if abs(dd) >= 0.5:
        parts.append(f"{'adds' if dd > 0 else 'saves'} {abs(dd):.1f} days of expected transit")
    if abs(dp) >= 0.03:
        parts.append(f"{'raises' if dp > 0 else 'cuts'} delay probability from {b.p_delay:.0%} to {a.p_delay:.0%}")
    if abs(a.p90 - b.p90) >= 1.0:
        parts.append(f"{'pushes out' if a.p90 > b.p90 else 'pulls in'} worst-case (P90) arrival from {b.p90:.1f} to {a.p90:.1f} days")
    if not parts:
        parts.append("is practically equivalent on freight, time and delay risk")
    sent = f"Compared with {ref_name} ({b.route_id[-2:]}: {b.path_str}), it " + "; ".join(parts) + "."
    saved = (b.exp_cost - b.freight) - (a.exp_cost - a.freight)
    if saved > 0.02 * a.freight and abs(dfr) >= 1:
        sent += f" Expected delay cost is lower by {_usd(saved)} (at {_usd(a.delay_cost_rate)}/day for this cargo)."
    return sent


def explain(rec: Recommendation) -> str:
    sh, ch = rec.shipment, rec.chosen
    L = []
    L.append(f"SHIPMENT {sh['shipment_id']}: {sh['origin']}→{sh['destination']}, {sh['teu']} TEU {sh['cargo_type']} | "
             f"profile={sh['profile']} | deadline {sh['deadline_days']} d | budget {_usd(sh['budget_usd'])}")
    wtxt = ", ".join(f"{k} {v:.0%}" for k, v in rec.weights.items())
    L.append(f"Priorities: {wtxt}; must reach on time with ≥{rec.min_on_time:.0%} probability.")
    L.append("")
    tag = _label(ch, rec)
    L.append(f"RECOMMENDED: {ch.route_id} — {ch.path_str}" + (f"  [{tag}]" if tag else ""))
    L.append(f"  Freight {_usd(ch.freight)} | expected transit {ch.exp_days:.1f} d (P50 {ch.p50:.1f}, P90 {ch.p90:.1f}) | "
             f"P(delay≥1d) {ch.p_delay:.0%} | P(on time) {ch.p_on_time:.0%} | exposure {ch.exposure:.2f}")
    if rec.relaxed:
        best_p = max(m.p_on_time for m in rec.metrics)
        L.append(f"  ⚠ NO route met all hard constraints ({rec.relaxed.replace('+', ' and ')}). Best-effort mode: kept the routes closest to the "
                 f"deadline (best achievable P(on time) is {best_p:.0%} vs {rec.min_on_time:.0%} required), then applied the weighted score. "
                 f"Recommend planner review: renegotiate deadline/budget or consider a faster mode.")
    L.append("")
    L.append("WHY THIS ROUTE")
    pool = rec.metrics
    cheapest, fastest = min(pool, key=lambda m: m.freight), min(pool, key=lambda m: m.exp_days)
    if ch.route_id == cheapest.route_id == fastest.route_id:
        L.append("  • It is both the cheapest and the fastest option, so no cost-vs-time trade-off was needed.")
    elif ch.route_id == cheapest.route_id:
        L.append("  • It is also the cheapest option by freight.")
    else:
        L.append("  • " + _compare(ch, cheapest, rec, "the cheapest option"))
    if ch.route_id != fastest.route_id and fastest.route_id != cheapest.route_id:
        L.append("  • " + _compare(ch, fastest, rec, "the fastest option"))
    elif ch.route_id == fastest.route_id and ch.route_id != cheapest.route_id:
        L.append("  • It is also the fastest option by expected transit time.")
    ru = next((m for m in rec.candidates if m.route_id != ch.route_id), None)
    if ru:
        adv = {k: ru.contrib[k] - ch.contrib[k] for k in C.CRITERIA}
        top = max(adv, key=adv.get)
        margin = ru.score - ch.score
        L.append(f"  • Runner-up is {ru.route_id} ({ru.path_str}); it loses by {margin:.3f} score points, mainly on {NICE[top]}.")
    L.append("")
    L.append("ALTERNATIVES CONSIDERED")
    for m in sorted(rec.metrics, key=lambda m: (m.score != m.score, m.score)):
        if m.route_id == ch.route_id:
            continue
        info = f"{m.path_str}: freight {_usd(m.freight)}, E[time] {m.exp_days:.1f} d, P(on time) {m.p_on_time:.0%}"
        if m not in rec.candidates:
            why = "; ".join(f"over budget ({_usd(v[1])} > {_usd(v[2])})" if v[0] == "budget"
                            else (f"on-time probability {v[1]:.0%} is well below the best achievable ({max(x.p_on_time for x in rec.metrics):.0%})"
                                  if rec.relaxed else f"on-time probability {v[1]:.0%} below required {v[2]:.0%}") for v in m.violations)
            if rec.relaxed and not m.violations:
                why = f"on-time probability {m.p_on_time:.0%} is well below the best achievable ({max(x.p_on_time for x in rec.metrics):.0%})"
            L.append(f"  ✗ {m.route_id} {info} — EXCLUDED: {why}.")
        else:
            if m.dominated_by:
                why = f"dominated by {m.dominated_by[-2:]} (which is at least as good on cost, time, predictability and exposure)"
            else:
                worst = max(C.CRITERIA, key=lambda k: m.contrib[k] - ch.contrib[k])
                why = f"lower overall score ({m.score:.2f} vs {ch.score:.2f}); weakest on {NICE[worst]}"
            L.append(f"  – {m.route_id} {info} — {why}.")
    st = rec.stability
    if st:
        L.append("")
        L.append("ROBUSTNESS")
        L.append(f"  Same route wins in {st['weight']['stability']:.0%} of weight perturbations and "
                 f"{st['data']['stability']:.0%} of delay-estimate perturbations → {st['label'].upper()}.")
        if st["flips"]:
            f = st["flips"][0]
            L.append(f"  Decision would switch to {f['new_route'][-2:]} if the {f['criterion']} weight moved from "
                     f"{f['from_w']:.0%} to {f['to_w']:.0%}.")
        else:
            L.append("  No single-weight change flips the decision.")
        if st["label"] == "close call":
            L.append("  ⚠ Close call between options — operator judgement recommended.")
    return "\n".join(L)
