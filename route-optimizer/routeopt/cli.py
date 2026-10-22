"""Command line interface.

  python -m routeopt.cli generate
  python -m routeopt.cli recommend --shipment SHP-003 [--profile urgent] [--deadline 30] [--budget 9000]
                                   [--weights cost=0.5,time=0.3] [--no-stability]
  python -m routeopt.cli evaluate
  python -m routeopt.cli multiseed [--n 10]
  python -m routeopt.cli all
"""
import argparse

from . import data_gen, evaluate, scoring, sensitivity
from .explain import explain


def _parse_weights(txt):
    if not txt:
        return None
    return {k: float(v) for k, v in (kv.split("=") for kv in txt.split(","))}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="routeopt", description="Shipment route recommendation under cost/time/risk trade-offs")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate", help="(re)generate the synthetic dataset")
    r = sub.add_parser("recommend", help="recommend a route for one shipment and explain why")
    r.add_argument("--shipment", required=True, help="shipment id, e.g. SHP-003")
    r.add_argument("--profile", choices=["balanced", "urgent", "cost_sensitive", "high_value"], help="override the shipment's profile")
    r.add_argument("--weights", help="override weights, e.g. cost=0.5,time=0.3 (renormalised)")
    r.add_argument("--deadline", type=float, help="what-if: override deadline (days)")
    r.add_argument("--budget", type=float, help="what-if: override budget (USD)")
    r.add_argument("--no-stability", action="store_true", help="skip sensitivity analysis (faster)")
    sub.add_parser("evaluate", help="run full evaluation; writes outputs/")
    m = sub.add_parser("multiseed", help="repeat policy comparison on N independent synthetic datasets")
    m.add_argument("--n", type=int, default=10)
    sub.add_parser("all", help="generate + evaluate + multiseed")
    a = ap.parse_args(argv)

    if a.cmd in ("generate", "all"):
        s, l = data_gen.generate()
        print(f"Generated {len(s)} shipments / {l.route_id.nunique()} routes -> data/")
    if a.cmd == "recommend":
        ships, legs = data_gen.load()
        row = ships[ships.shipment_id == a.shipment]
        if row.empty:
            raise SystemExit(f"Unknown shipment {a.shipment}. Available: {ships.shipment_id.iloc[0]} .. {ships.shipment_id.iloc[-1]}")
        sh = row.iloc[0].copy()
        if a.deadline is not None:
            sh["deadline_days"] = a.deadline
        if a.budget is not None:
            sh["budget_usd"] = a.budget
        rec = scoring.recommend(sh, legs, weights=_parse_weights(a.weights), profile=a.profile)
        if not a.no_stability:
            sensitivity.assess(rec, legs)
        print(explain(rec))
    if a.cmd == "multiseed":
        import pandas as pd
        pd.set_option("display.width", 200)
        print(evaluate.multi_seed(a.n).round(2).to_string())
    if a.cmd in ("evaluate", "all"):
        ships, legs = data_gen.load()
        res = evaluate.run(ships, legs)
        import pandas as pd
        pd.set_option("display.width", 200)
        print("\n" + pd.DataFrame(res["summary"]).set_index("policy").to_string())
        if a.cmd == "all":
            print(evaluate.multi_seed().round(2).to_string())
        print("\nWrote outputs/: results.json, recommendations.csv, explanations.txt, evaluation_*.csv, figures/")


if __name__ == "__main__":
    main()
