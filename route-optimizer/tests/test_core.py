import numpy as np
import pytest

from routeopt import config as C
from routeopt import data_gen, scoring as S, sensitivity as SE, simulate
from routeopt.explain import explain


@pytest.fixture(scope="module")
def data():
    return data_gen.generate(write=False)


def test_dataset_shape(data):
    ships, legs = data
    assert 20 <= len(ships) <= 50
    per = legs.groupby("shipment_id").route_id.nunique()
    assert per.between(3, 5).all()                    # 3-5 routes per shipment


def test_routes_connect_origin_to_destination(data):
    ships, legs = data
    for _, sh in ships.iterrows():
        for rid, g in legs[legs.shipment_id == sh.shipment_id].groupby("route_id"):
            g = g.sort_values("leg_idx")
            assert g.origin_node.iloc[0] == sh.origin and g.dest_node.iloc[-1] == sh.destination
            assert list(g.origin_node.iloc[1:]) == list(g.dest_node.iloc[:-1])   # contiguous legs


def test_monte_carlo_matches_closed_form():
    p, mu, geo = np.array([0.1, 0.2, 0.15]), np.array([2.0, 3.0, 4.0]), np.array([0.1, 0.5, 0.3])
    d = simulate.simulate_delay(p, mu, geo, 200_000, np.random.default_rng(0))
    assert d.mean() == pytest.approx(simulate.expected_delay(p, mu, geo), rel=0.03)


def test_scoring_never_reads_ground_truth(data):
    ships, legs = data
    sh = ships.iloc[0]
    a = S.recommend(sh, legs)
    scrambled = legs.copy()
    for c in [c for c in legs.columns if c.endswith("_true")]:
        scrambled[c] = 0.5                               # destroy all hidden truth
    b = S.recommend(sh, scrambled)
    assert a.chosen.route_id == b.chosen.route_id and a.chosen.score == pytest.approx(b.chosen.score)


def test_recommendation_is_deterministic(data):
    ships, legs = data
    assert S.recommend(ships.iloc[3], legs).chosen.route_id == S.recommend(ships.iloc[3], legs).chosen.route_id


def test_hard_constraints_respected_when_feasible(data):
    ships, legs = data
    for _, sh in ships.iterrows():
        r = S.recommend(sh, legs)
        if r.relaxed is None:
            assert r.chosen.freight <= sh.budget_usd and r.chosen.p_on_time >= r.min_on_time


def test_always_returns_a_route_even_if_infeasible(data):
    ships, legs = data
    sh = ships.iloc[0].copy(); sh["budget_usd"], sh["deadline_days"] = 1, 1
    r = S.recommend(sh, legs)
    assert r.chosen is not None and r.relaxed == "budget+deadline"


def test_dominated_route_never_wins(data):
    ships, legs = data
    for _, sh in ships.iterrows():
        r = S.recommend(sh, legs)
        assert r.chosen.dominated_by is None or r.chosen.dominated_by not in [m.route_id for m in r.candidates]


def test_weights_normalise_and_shift_decisions(data):
    w = S.weights_for("balanced", {"cost": 5.0})
    assert sum(w.values()) == pytest.approx(1.0)
    assert w["cost"] > S.weights_for("balanced")["cost"]


def test_stability_and_explanation(data):
    ships, legs = data
    r = SE.assess(S.recommend(ships.iloc[2], legs), legs, n_data=10)
    assert 0 <= r.stability["overall"] <= 1
    txt = explain(r)
    assert "RECOMMENDED" in txt and "ALTERNATIVES" in txt and "ROBUSTNESS" in txt
