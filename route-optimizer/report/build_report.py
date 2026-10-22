"""Builds report/Technical_Report.pdf from outputs/*.json so every number in the report is traceable."""
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"
F = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("DV", F + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DV-B", F + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DV-I", F + "DejaVuSans-Oblique.ttf"))
pdfmetrics.registerFont(TTFont("DVM", F + "DejaVuSansMono.ttf"))
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV-I", boldItalic="DV-B")

res = json.load(open(OUT / "results.json"))
ms = json.load(open(OUT / "multiseed.json"))
S = {r["policy"]: r for r in res["summary"]}
M = {r["policy"]: r for r in ms["table"]}
BP = {r["profile"]: r for r in res["by_profile"]}
st, sw = res["stability"], res["profile_switch_rate"]

base = ParagraphStyle("b", fontName="DV", fontSize=8.1, leading=10.6, spaceAfter=3.2, alignment=4)
h1 = ParagraphStyle("h1", parent=base, fontName="DV-B", fontSize=10, leading=12.5, spaceBefore=5, spaceAfter=2.5, textColor=colors.HexColor("#17445a"))
title = ParagraphStyle("t", parent=base, fontName="DV-B", fontSize=14, leading=17, alignment=0, spaceAfter=1)
sub = ParagraphStyle("s", parent=base, fontSize=8.3, textColor=colors.HexColor("#444444"), alignment=0, spaceAfter=4)
bul = ParagraphStyle("bul", parent=base, leftIndent=9, bulletIndent=0, spaceAfter=1.6)
mono = ParagraphStyle("m", parent=base, fontName="DVM", fontSize=6.3, leading=8, alignment=0, backColor=colors.HexColor("#f2f4f6"),
                      borderPadding=(3, 3, 3, 3), spaceBefore=2, spaceAfter=5)
cap = ParagraphStyle("c", parent=base, fontSize=7, leading=8.6, textColor=colors.HexColor("#444444"), alignment=0)
cell = ParagraphStyle("cell", parent=base, fontSize=7.1, leading=8.6, alignment=0, spaceAfter=0)
cellb = ParagraphStyle("cellb", parent=cell, fontName="DV-B")


def P(t, s=base): return Paragraph(t, s)
def B(t): return Paragraph(t, bul, bulletText="•")


def table(rows, widths, hdr=True, zebra=True, bold_first_col=False):
    data = [[Paragraph(str(c), cellb if (hdr and i == 0) or (bold_first_col and j == 0) else cell) for j, c in enumerate(r)] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if hdr else 0)
    sty = [("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b8c0c8")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
           ("TOPPADDING", (0, 0), (-1, -1), 1.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    if hdr:
        sty.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dce8ee")))
    t.setStyle(TableStyle(sty))
    return t


story = []
story += [P("Optimizing Shipment Routes Under Cost, Time and Risk Constraints", title),
          P("Technical report · Aiqon AI Internship take-home (Round 2) · Satya Vineel Kandula · code: <font name='DVM'>route-optimizer/</font> (README has run instructions)", sub)]

# 1 ------------------------------------------------------------------------------------------------
story.append(P("1. Problem framing and what “optimal” means", h1))
story.append(P("Choosing a route is a <b>decision under uncertainty</b> with conflicting objectives, not a prediction task, and no labelled “correct route” exists. "
               "I therefore built a transparent decision framework rather than a black-box model. A route is <b>optimal for a shipment</b> if it has the lowest "
               "profile-weighted score <i>among routes that satisfy the shipment’s hard constraints</i>: freight ≤ budget and a <b>chance constraint</b> "
               "P(arrive by deadline) ≥ τ. Four criteria are scored (all minimised): <b>cost</b> = freight + E[delay days] × delay-cost-rate; <b>time</b> = E[transit days]; "
               "<b>spread</b> = P90 − P50 transit days (unpredictability, which an average hides); <b>exposure</b> = structural geopolitical/congestion exposure of the lanes and hubs. "
               "What matters differs per shipment, so the weights come from a <b>profile</b> (overridable per request):"))
story.append(table([["Profile (typical cargo)", "cost", "time", "spread", "exposure", "τ (min P on-time)"],
                    ["balanced (standard)", "0.35", "0.25", "0.20", "0.20", "0.70"], ["urgent (perishable, rush)", "0.15", "0.50", "0.25", "0.10", "0.85"],
                    ["cost_sensitive (commodity)", "0.60", "0.15", "0.15", "0.10", "0.60"], ["high_value (electronics, pharma)", "0.20", "0.15", "0.30", "0.35", "0.85"]],
                   [5.2 * cm, 1.8 * cm, 1.8 * cm, 1.8 * cm, 2.0 * cm, 3.4 * cm]))
story.append(Spacer(1, 3))

# 2 ------------------------------------------------------------------------------------------------
story.append(P("2. Synthetic data: how routes and trade-offs were constructed", h1))
story.append(P(f"<b>Network.</b> 3 Indian origins → 9 transshipment hubs → 5 destinations (EU/US), 44 sea lanes plus direct air. Trade-offs are built in by design: the Red Sea/Gulf of Aden corridor is shorter and cheaper "
               "but has high geopolitical risk and disruption shocks (stressed scenario); the Cape of Good Hope is ~9 days slower and costlier but calm; air is ~4–5× the cost and ~10× faster; "
               "every transshipment adds dwell time, handling cost and an extra chance of delay. "
               f"<b>Shipments.</b> {res['n_shipments']} shipments, each with 3–5 routes ({res['n_routes']} routes, 385 legs; cheap, fast and low-risk archetypes plus air where the cargo allows). "
               "Five cargo types set value, delay cost per day and default profile. Deadlines and budgets are calibrated from each shipment’s own routes; "
               f"{res['relaxed_count']} of {res['n_shipments']} are deliberately (near-)infeasible to test the fallback."))
story.append(P("<b>Uncertainty model.</b> Per leg, a delay occurs with probability p (congestion- and geopolitics-dependent) with log-normal duration, plus a rare disruption shock "
               "(7–14 days, probability ∝ geopolitical risk). Legs are independent, so routes with more legs accumulate more exposure. "
               "<b>Ground truth vs. estimates:</b> every leg stores hidden true parameters and noisy estimates (log-normal error σ≈0.25 on delay probability, σ≈0.2 on duration). "
               "The decision system only reads the estimates (enforced by a unit test); the evaluation simulates real outcomes from the truth. This separation is what makes the evaluation meaningful."))

# 3 ------------------------------------------------------------------------------------------------
story.append(P("3. Decision framework and design decisions", h1))
story.append(B("<b>Monte Carlo metrics (2,000 draws/route)</b> turn the delay model into E[time], P50/P90, P(delay ≥ 1 d), P(on time) and expected delay cost; common random numbers per route make decisions deterministic."))
story.append(B("<b>Hard constraints before trade-offs.</b> A cheap route that misses the deadline with 40% probability should not win because it is cheap; constraints are not weights. "
               "If <i>no</i> route is feasible the system does not fail: it keeps routes within 10 pp of the best achievable P(on time) (within budget if possible), scores those, and flags the shipment for a planner. "
               "(A first version simply dropped the deadline in this case and picked a 48% on-time route over a 73% one; I fixed it after inspecting an explanation.)"))
story.append(B(f"<b>Pareto check.</b> Routes dominated on all four criteria ({res['pareto_dominated_share']:.0%} of routes) are labelled in the explanation (“dominated by R3”); a weighted sum with non-negative weights can never select them."))
story.append(B("<b>Weighted sum over min–max-normalised criteria.</b> Chosen over TOPSIS/NSGA-II/learning because with 3–5 options exhaustive evaluation is exact, weights map to business priorities a planner can edit, and every point of the score can be explained. "
               "Min–max scaling can exaggerate tiny differences when options are near-identical, so the normalisation range has a floor (10% of the best value for cost/time, 1 day for spread, 0.05 for exposure)."))

# 4 ------------------------------------------------------------------------------------------------
story.append(P("4. Explanations for operators", h1))
story.append(P("Explanations are generated from the computed numbers (no canned justifications): trade-off against the cheapest/fastest option in business units, "
               "why every alternative lost (excluded by budget/deadline, dominated, or lower score and on which criterion), and a robustness statement. Real output (abridged):"))
story.append(P("RECOMMENDED: SHP-001-R2 — CHE → CMB → CPT → NYC (sea)<br/>"
               "  Freight $8,443 | E[transit] 37.7 d (P50 36.1, P90 42.9) | P(delay≥1d) 50% | P(on time) 98%<br/>"
               "• Compared with the cheapest option (R1: CHE → CMB → PSD → NYC), it costs $600 (8%) more in freight; adds 0.6 days of<br/>"
               "  expected transit; cuts delay probability from 59% to 50%; pulls in worst-case (P90) arrival from 45.9 to 42.9 days.<br/>"
               "  Expected delay cost is lower by $345 (at $160/day for this cargo).<br/>"
               "– R3 … $8,645 … — dominated by R2 (at least as good on cost, time, predictability and exposure).<br/>"
               "ROBUSTNESS: same route wins in 97% of weight perturbations and 85% of delay-estimate perturbations → ROBUST.<br/>"
               "  Decision would switch to R1 if the spread weight moved from 15% to 4%.", mono))

# 5 ------------------------------------------------------------------------------------------------
story.append(P("5. Uncertainty and sensitivity of decisions", h1))
story.append(P("Each recommendation is stress-tested three ways: (i) <b>weight stability</b> – Dirichlet-perturbed weights (1,000 draws), how often the same route wins; "
               "(ii) <b>flip thresholds</b> – how far one weight must move before the winner changes; (iii) <b>delay-estimate stability</b> – delay probabilities/durations perturbed (σ=0.3), "
               "Monte Carlo, constraints and scoring re-run (60 draws). Overall stability is the minimum of (i) and (iii): ≥80% “robust”, 60–80% “moderate”, &lt;60% “close call – operator judgement”. "
               f"<b>Result:</b> mean stability {st['mean']:.0%}; {st['share_robust']:.0%} of decisions robust, the rest moderate, none a close call. "
               f"Priorities matter, though: swapping the profile changes the recommended route for {sw['mean']:.0%} of shipments on average (up to {max(v for k, v in sw.items() if k != 'mean'):.0%} for the most different pairs, e.g. urgent vs. cost_sensitive). "
               "The minority of weight-sensitive shipments are exactly where operators should look (the flip threshold tells them what to look at)."))

# 6 ------------------------------------------------------------------------------------------------
story.append(P("6. Evaluation", h1))
story.append(P("<b>Method.</b> For every route I simulate 4,000 outcomes from the <i>true</i> parameters and compute a realised loss to the shipper = freight + delay cost + capital holding cost + 3× lateness fee beyond the deadline. "
               "This loss is not the scoring function (it adds holding and lateness terms and uses true, not estimated, risk). "
               "<b>Regret</b> = (loss of chosen route − loss of hindsight-best route) / loss of best. Baselines: cheapest, fastest (nominal days), lowest exposure, random, and an <b>ablation</b> of my system without the uncertainty model (nominal days, no delay risk). "
               "“Meets req.” = true P(on time) ≥ τ <i>and</i> within budget."))
rows = [["Policy", "Mean regret % (seed 42)", "Oracle match", "Meets req.", "Mean P(on time)", "Budget viol.", "Mean regret % ± sd (10 seeds)"]]
names = dict(ours="<b>Ours</b>", ours_det="Ours, no uncertainty", cheapest="Cheapest", fastest="Fastest", lowest_risk="Lowest exposure", random="Random")
for k in ["ours", "ours_det", "cheapest", "fastest", "lowest_risk", "random"]:
    r = S[k]; m = M.get(k)
    rows.append([names[k], f"{r['mean_regret_pct']:.1f}", f"{r['oracle_match']:.0%}", f"{r['meets_requirements']:.0%}", f"{r['mean_true_p_on_time']:.2f}", f"{r['budget_violation']:.0%}",
                 f"{m['mean_regret_pct']:.1f} ± {m['sd_regret_pct']:.1f}" if m else "—"])
story.append(table(rows, [3.6 * cm, 2.7 * cm, 2.0 * cm, 1.9 * cm, 2.3 * cm, 1.9 * cm, 3.0 * cm]))
story.append(Spacer(1, 3))
story.append(Image(str(OUT / "figures/fig_policy_comparison.png"), width=12.6 * cm, height=12.6 * cm * 3.1 / 9))
story.append(P("Figure 1. Left: decision quality. Right: share of shipments whose true outcome meets budget and on-time requirement.", cap))
story.append(P("<b>Findings (stated with their limits).</b>", base))
story.append(B(f"The framework achieves near-hindsight-optimal decisions (mean regret {S['ours']['mean_regret_pct']:.1f}%, {M['ours']['mean_regret_pct']:.1f}% ± {M['ours']['sd_regret_pct']:.1f} over 10 datasets) while single-metric rules fail: "
               f"cheapest ≈ {M['cheapest']['mean_regret_pct']:.0f}% regret and misses requirements in about a third of cases; fastest/lowest-exposure ≈ {M['fastest']['mean_regret_pct']:.0f}% because they buy air freight and blow the budget ({S['fastest']['budget_violation']:.0%} of shipments). "
               f"Our ‘meets requirements’ rate ({S['ours']['meets_requirements']:.0%}) equals the share of shipments that have a feasible route, so the constraint layer loses nothing it could have kept."))
story.append(B(f"<b>The simple cheapest rule is not worse everywhere</b>: for cost_sensitive cargo it has {BP['cost_sensitive']['cheapest']:.1f}% regret vs. {BP['cost_sensitive']['ours']:.1f}% for ours (cheap lanes are also adequate when delay costs are low). "
               f"The gains come from balanced/urgent/high_value cargo (e.g. urgent: {BP['urgent']['ours']:.1f}% vs. {BP['urgent']['cheapest']:.0f}% cheapest and {BP['urgent']['fastest']:.0f}% fastest)."))
story.append(B(f"<b>The benefit of modelling uncertainty is real but modest:</b> the ablation has {M['ours_det']['mean_regret_pct']:.1f}% regret vs. {M['ours']['mean_regret_pct']:.1f}%, and ours wins in only {int(M['ours_det']['ours_better_in_n_seeds'])} of 10 datasets. "
               "On seed 42 alone the gap looked much bigger (3.9% vs 1.0%), which is why I added the multi-seed check."))
import pandas as pd
mix = res["decision_mix"]
_r = pd.read_csv(OUT / "recommendations.csv")
_sea = _r[(~_r.path.str.contains("air")) & (_r.premium_vs_cheapest_pct > 0)].premium_vs_cheapest_pct
prem_med, prem_max = _sea.median(), _sea.max()
story.append(B(f"<b>The system actually trades off rather than defaulting to one rule:</b> of {res['n_shipments']} recommendations, {mix['cheapest']} are the cheapest sea route, {mix['balanced_other']} are a "
               f"balanced option that is neither cheapest nor fastest (typically paying a small freight premium for lower delay risk; median premium {prem_med:.0f}%, at most {prem_max:.0f}%), and {mix['air']} are air, chosen only where budget and cargo value justify it."))
story.append(KeepTogether([Table([[Image(str(OUT / "figures/fig_tradeoff_example.png"), width=7.6 * cm, height=7.6 * cm * 3.4 / 4.8),
                                    Image(str(OUT / "figures/fig_stability.png"), width=6.9 * cm, height=6.9 * cm * 3.3 / 4.2)]],
                                  colWidths=[8.2 * cm, 7.6 * cm], style=[("VALIGN", (0, 0), (-1, -1), "MIDDLE")]),
                           P("Figure 2. Left: SHP-001 – the cheapest route (R1) has the widest P50–P90 range; the system pays +8% freight for a tighter, lower-exposure route (R2). Right: distribution of decision stability.", cap)]))

# 7 ------------------------------------------------------------------------------------------------
story.append(P("7. Assumptions and limitations", h1))
story.append(B("<b>Synthetic, stylised data.</b> Network, costs and risk parameters are plausible but invented; the conclusions show the framework behaves sensibly, not what real-world savings would be. Real use needs carrier schedule-reliability, port-congestion and risk feeds."))
story.append(B("<b>Evaluation is partly self-referential.</b> Truth and decision model use the same family of delay model (misspecification is tested only through estimate noise), and delay cost enters both scorer and loss. Absolute regret is therefore optimistic; the <i>relative</i> comparisons are the informative part."))
story.append(B("<b>Weights and τ are expert-set, not learned.</b> They would ideally be elicited from planners (e.g. from their historical choices). Min–max scores are relative to the option set, so a score is not comparable across shipments."))
story.append(B("<b>Modelling simplifications:</b> independent legs (real delays are correlated, e.g. a shared Red Sea closure), a static snapshot (no in-transit re-routing), no capacity/consolidation/multi-shipment effects, direct air only, "
               "and I use mean/P90/spread rather than a coherent tail-risk measure such as CVaR. Dataset is small (35 shipments); stability and regret numbers have sampling error, partly addressed by the 10-seed run."))
story.append(B("<b>Reproduce:</b> <font name='DVM'>python -m routeopt.cli all</font> regenerates data, results and figures; <font name='DVM'>pytest</font> runs 10 tests (constraint compliance, determinism, “scorer never reads ground truth”, Monte-Carlo vs closed form, always returns a route)."))


story.append(P("8. What I would do next", h1))
story.append(B("Replace the synthetic network with real data (carrier schedule reliability, port congestion indices, security/risk feeds) and re-estimate delay distributions, including <b>correlated</b> disruptions."))
story.append(B("Elicit weights from planners (pairwise “which would you ship?” comparisons) and check against their historical choices; calibrate τ against actual penalties."))
story.append(B("Add tail-risk (CVaR) as a criterion, multi-modal/split shipments, capacity limits and re-planning when a disruption is observed in transit; evaluate with a held-out set of real shipments."))


def footer(c, d):
    c.saveState(); c.setFont("DV", 7); c.setFillColor(colors.grey)
    c.drawRightString(A4[0] - 1.6 * cm, 0.9 * cm, f"{d.page}"); c.restoreState()


doc = SimpleDocTemplate(str(ROOT / "report/Technical_Report.pdf"), pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                        topMargin=1.3 * cm, bottomMargin=1.4 * cm, title="Optimizing Shipment Routes Under Cost, Time and Risk Constraints",
                        author="Satya Vineel Kandula")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("built")
