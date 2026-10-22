# Shipment Route Recommender — cost, time and risk under uncertainty

Take-home assignment for **Aiqon (AI Internship, Round 2)**. Given a shipment and 3–5 candidate routes, the
system **evaluates** every route, **recommends** one, and **explains** why it beats the alternatives —
including how confident that decision is.

> Quick start (≈ 1 minute, CPU only):
> ```bash
> pip install -r requirements.txt
> python -m routeopt.cli recommend --shipment SHP-001      # one decision + explanation
> python -m routeopt.cli evaluate                          # full evaluation -> outputs/
> python -m pytest -q tests                                # 10 tests
> streamlit run app.py                                     # optional interactive demo
> ```
> The technical report is in `report/Technical_Report.pdf`.

## What "optimal" means here
Route choice is a **decision under uncertainty**, not a prediction task, so the system is a transparent
multi-criteria decision framework instead of a black-box model (there are no labelled "correct routes" anyway).

1. **Hard constraints** – freight ≤ budget, and a *chance constraint* `P(arrive by deadline) ≥ threshold`
   (threshold depends on the shipment profile).
2. **Four criteria** (all "lower is better", estimated by Monte-Carlo over delay uncertainty):
   expected landed cost (freight + expected delay cost) · expected transit time · schedule spread (P90−P50) ·
   structural exposure (geopolitical + congestion).
3. **Profile-weighted score** on min–max-normalised criteria. Profiles (`balanced`, `urgent`, `cost_sensitive`,
   `high_value`) encode what the shipper cares about; weights can be overridden per request.
4. **Best-effort fallback** – if no route satisfies the constraints the system still answers, picks the routes
   closest to the deadline, and flags the case for a planner.
5. **Explanation + robustness** – text generated from the numbers: trade-off vs the cheapest/fastest option, why each
   alternative lost (excluded / dominated / lower score), how often the same route wins when weights or delay
   estimates are perturbed, and the weight change that would flip the decision.

## Repository layout
```
routeopt/
  config.py       all assumptions: port network, delay model, profiles, cargo types
  data_gen.py     synthetic data generator (shipments.csv, legs.csv)
  simulate.py     Monte-Carlo delay model
  scoring.py      metrics -> constraints -> Pareto -> weighted score -> recommendation
  sensitivity.py  weight stability, flip thresholds, delay-estimate stability
  explain.py      operator-facing explanations
  evaluate.py     baselines, regret vs simulated ground truth, ablation, multi-seed check, figures
  cli.py          command line interface
app.py            optional Streamlit demo
tests/            pytest suite
data/             generated dataset (reproducible, seed 42)
outputs/          results: recommendations.csv, explanations.txt (all 35), evaluation_*.csv, results.json, figures/
report/           2–3 page technical report (PDF) + the script that builds it
```

## Usage
```bash
python -m routeopt.cli generate                              # regenerate data (seed 42)
python -m routeopt.cli recommend --shipment SHP-017
python -m routeopt.cli recommend --shipment SHP-017 --profile high_value
python -m routeopt.cli recommend --shipment SHP-001 --weights cost=0.7,time=0.1   # custom priorities
python -m routeopt.cli recommend --shipment SHP-001 --deadline 40 --budget 9000   # what-if
python -m routeopt.cli evaluate                              # policies vs ground truth + figures
python -m routeopt.cli multiseed --n 10                      # repeat on 10 independent datasets
```
Example output (abridged):
```
RECOMMENDED: SHP-001-R2 — CHE → CMB → CPT → NYC (sea)
  Freight $8,443 | expected transit 37.7 d (P50 36.1, P90 42.9) | P(delay≥1d) 50% | P(on time) 98%
WHY THIS ROUTE
  • Compared with the cheapest option (R1 …), it costs $600 (8%) more in freight; cuts delay probability from 59% to 50%;
    pulls in worst-case (P90) arrival from 45.9 to 42.9 days. Expected delay cost is lower by $345 …
ROBUSTNESS
  Same route wins in 97% of weight perturbations and 85% of delay-estimate perturbations → ROBUST.
```

## Synthetic data (how routes and trade-offs are constructed)
* **Network**: 3 Indian origins → 9 transshipment hubs → 5 destinations, 44 sea lanes + direct air.
  Red Sea / Gulf of Aden lanes are shorter and cheaper but carry high geopolitical risk and disruption shocks;
  Cape of Good Hope lanes are slower and costlier but calm; air is ~4–5× the cost and ~10× faster; every
  transshipment adds dwell time, handling cost and delay exposure. This creates real trade-offs by construction.
* **Per shipment**: 35 shipments, 3–5 routes each (137 routes, 385 legs), built to include cheap, fast and low-risk archetypes (within the 3–5 limit),
  plus air when the cargo allows it. Cargo types (standard, commodity, perishable, electronics,
  pharma) set delay cost per day, cargo value and default profile.
* **Ground truth vs estimates**: each leg has hidden true parameters (`*_true`) and noisy estimates (`*_est`:
  log-normal error σ≈0.25 on delay probability, σ≈0.2 on delay duration, ±0.05 on indices). **The decision system
  only reads `*_est`** (enforced by a test); `evaluate.py` uses `*_true` to simulate real outcomes.
* **Deadlines/budgets** are calibrated from each shipment's own routes; ~17 % of shipments are deliberately
  (near-)infeasible to exercise the fallback.

## Key assumptions & limitations (details in the report)
Synthetic, stylised network; legs are independent; one static snapshot (no re-routing); weights are expert-set
(not learned); the evaluation loss shares the delay-cost concept with the scorer, so absolute regret numbers are
optimistic — relative comparisons between policies are the meaningful part; 35 shipments is small (hence the
10-seed check).

## Reproducibility
Everything is seeded (`config.SEED = 42`); `python -m routeopt.cli all` regenerates data, results, figures.
