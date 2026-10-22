"""Optional demo:  streamlit run app.py   (pip install streamlit)"""
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from routeopt import config as C, data_gen, scoring, sensitivity
from routeopt.explain import explain

st.set_page_config(page_title="Shipment Route Recommender", layout="wide")
st.title("🚢 Shipment route recommender")
st.caption("Multi-criteria decision support under delay uncertainty — synthetic data")


@st.cache_data
def load():
    return data_gen.load()


ships, legs = load()
sid = st.sidebar.selectbox("Shipment", ships.shipment_id)
sh = ships[ships.shipment_id == sid].iloc[0].copy()
st.sidebar.markdown(f"**{sh.origin} → {sh.destination}**, {sh.teu} TEU {sh.cargo_type}")
profile = st.sidebar.selectbox("Priority profile", list(C.PROFILES), index=list(C.PROFILES).index(sh.profile))
base = scoring.weights_for(profile)
st.sidebar.markdown("**Weights** (auto-normalised)")
w = {k: st.sidebar.slider(k, 0.0, 1.0, float(round(base[k], 2)), 0.05) for k in C.CRITERIA}
sh["deadline_days"] = st.sidebar.number_input("Deadline (days)", 1, 120, int(sh.deadline_days))
sh["budget_usd"] = st.sidebar.number_input("Budget (USD)", 100, 500_000, int(sh.budget_usd), 100)

if sum(w.values()) == 0:
    st.warning("Set at least one weight above zero."); st.stop()
rec = scoring.recommend(sh, legs, weights=w, profile=profile)
sensitivity.assess(rec, legs, n_data=40)
ch = rec.chosen

c = st.columns(5)
c[0].metric("Recommended", ch.route_id[-2:]); c[1].metric("Freight", f"${ch.freight:,.0f}")
c[2].metric("Expected days", f"{ch.exp_days:.1f}", f"P90 {ch.p90:.1f}", delta_color="off")
c[3].metric("P(on time)", f"{ch.p_on_time:.0%}"); c[4].metric("Robustness", rec.stability["label"], f"{rec.stability['overall']:.0%}", delta_color="off")
if rec.relaxed:
    st.error(f"No route satisfies all constraints ({rec.relaxed} relaxed) — showing best available option.")

left, right = st.columns([3, 2])
with left:
    df = pd.DataFrame([dict(route=m.route_id[-2:], path=m.path_str, freight=round(m.freight), exp_days=round(m.exp_days, 1),
                            p90=round(m.p90, 1), p_delay=f"{m.p_delay:.0%}", p_on_time=f"{m.p_on_time:.0%}", exposure=round(m.exposure, 2),
                            score=None if m.score != m.score else round(m.score, 3),
                            status="✅ recommended" if m is ch else ("excluded: " + ", ".join(v[0] for v in m.violations)
                                   if m not in rec.candidates else ("dominated" if m.dominated_by else "considered")))
                       for m in rec.metrics])
    st.dataframe(df.sort_values("score", na_position="last"), width="stretch", hide_index=True)
    st.text(explain(rec))
with right:
    fig, ax = plt.subplots(figsize=(5, 3.6))
    for m in rec.metrics:
        col = "#c0392b" if m not in rec.candidates else "#1f6f8b"
        ax.hlines(m.freight, m.p50, m.p90, color=col, alpha=.7); ax.scatter(m.exp_days, m.freight, s=50 + 500 * m.exposure, color=col, alpha=.6, edgecolor="k")
        ax.annotate(m.route_id[-2:], (m.p90, m.freight), xytext=(4, -3), textcoords="offset points", fontsize=8)
    ax.scatter(ch.exp_days, ch.freight, marker="*", s=280, color="#f1c40f", edgecolor="k", zorder=3)
    ax.set_xlabel("Transit days (dot = expected, line = P50–P90)"); ax.set_ylabel("Freight (USD)"); ax.spines[["top", "right"]].set_visible(False)
    st.pyplot(fig)
