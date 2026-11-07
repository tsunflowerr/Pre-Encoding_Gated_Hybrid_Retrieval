from pathlib import Path

import numpy as np
import pytest

from pegh.v4 import gate as g
from pegh.v4.workspace import Workspace


def _ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "v4", tmp_path / "v3", tmp_path / "dev", tmp_path / "dense")


def test_workspace_reuses_seen_artifacts_and_isolates_new_ones(tmp_path):
    ws = _ws(tmp_path)
    assert ws.dense("minilm", "unix") == ws.dev_dense_root / "unix"
    assert ws.dense("bge_small_q", "gis") == ws.v3_root / "artifacts/dense/bge_small/gis"
    assert ws.dense("arctic_xs_q", "unix") == ws.root / "artifacts/dense/arctic_xs/unix"
    assert ws.dense("minilm", "tex") == ws.root / "artifacts/dense/minilm/tex"
    assert ws.quality("bm25", "programmers").is_relative_to(ws.dev_root)
    assert ws.quality("bge_small", "unix").is_relative_to(ws.v3_root)
    assert ws.quality("bge_small_q", "unix").is_relative_to(ws.root)
    assert ws.tiers("bge_small", "android").is_relative_to(ws.v3_root)
    assert ws.tiers("bge_small_q", "android").is_relative_to(ws.root)
    assert ws.raw("stats") == ws.root / "data/raw/stats"
    with pytest.raises(ValueError):
        ws.raw("cooking")


def test_gate_round_trip_and_domain_normalization():
    rng = np.random.default_rng(0)
    xs = [rng.normal(loc=i, size=(80, 21)) for i in range(3)]
    bm25 = [np.where(x[:, 0] > x[:, 0].mean(), 0.0, 0.5) for x in xs]
    for spec in g.CANDIDATES:
        if spec.groups != ("v1",):
            continue
        gate = g.fit(spec, xs, bm25)
        again = g.LinearGate.from_json(gate.to_json())
        stats = g.domain_stats(xs[0])
        assert np.allclose(gate.score(xs[0], stats), again.score(xs[0], stats))
        assert again.sha256 == gate.sha256
    domain_gate = g.fit(g.GateSpec("fail", ("v1",), "domain"), xs, bm25)
    with pytest.raises(ValueError):
        domain_gate.score(xs[0])


def test_budget_routing_is_exact_and_threshold_matches_quantile():
    score = np.array([0.9, 0.1, 0.5, 0.7, 0.3, 0.8])
    forced = np.array([False, True, False, False, False, False])
    ids = [f"q{i}" for i in range(6)]
    chosen = g.route_top(score, forced, ids, 0.5)
    assert chosen.sum() == 3 and chosen[1] and chosen[0] and chosen[5]
    t = g.quantile_threshold(score, forced, 0.5)
    assert (forced | (score > t)).sum() == 3


@pytest.mark.parametrize("budget", [0.0, 0.25, 0.5, 0.8, 1.0])
@pytest.mark.parametrize("scores", [[1.0, 1.0, 1.0, 1.0], [2.0, 1.0, 1.0, 0.0]])
def test_serialized_budget_policy_matches_exact_routing_including_ties(budget, scores):
    import json

    score = np.asarray(scores)
    forced = np.array([False, True, False, False])
    ids = ["unix:q4", "unix:q3", "unix:q2", "unix:q1"]
    policy = g.BudgetPolicy.from_json(
        json.loads(
            json.dumps(g.calibrate_budget(score, forced, ids, budget).to_json(), allow_nan=False)
        )
    )
    observed = [policy.use_dense(s, q, bool(f)) for s, q, f in zip(score, ids, forced, strict=True)]
    np.testing.assert_array_equal(observed, g.route_top(score, forced, ids, budget))
    assert policy.forced_count == 1 and policy.calibration_count == 4


def test_scalar_threshold_rejects_boundary_ties_and_policy_does_not_skip_everything():
    score, forced, ids = np.ones(4), np.zeros(4, dtype=bool), ["q4", "q2", "q3", "q1"]
    with pytest.raises(ValueError, match="boundary scores tie"):
        g.quantile_threshold(score, forced, 0.5)
    policy = g.calibrate_budget(score, forced, ids, 0.5)
    assert [q for q in ids if policy.use_dense(1.0, q)] == ["q2", "q1"]


@pytest.mark.parametrize("budget", [-0.1, 1.1, np.nan, np.inf, True])
def test_invalid_budgets_fail_before_routing(budget):
    scores, forced, ids = np.ones(4), np.zeros(4, dtype=bool), ["q1", "q2", "q3", "q4"]
    for call in (
        lambda: g.route_top(scores, forced, ids, budget),
        lambda: g.quantile_threshold(scores, forced, budget),
        lambda: g.calibrate_budget(scores, forced, ids, budget),
    ):
        with pytest.raises(ValueError, match="budget"):
            call()


def test_forced_queries_define_a_floor_above_requested_budget():
    forced = np.array([True, True, True, False])
    policy = g.calibrate_budget(np.ones(4), forced, ["q1", "q2", "q3", "q4"], 0.5)
    assert sum(policy.use_dense(1.0, f"q{i + 1}", bool(f)) for i, f in enumerate(forced)) == 3
    assert policy.forced_count / policy.calibration_count > policy.budget


def test_online_search_uses_the_same_tie_policy():
    from types import SimpleNamespace

    from contracts.types import FeatureVector, Hit, Query, Ranking
    from pegh.v4.online import V2SearchMethod

    ids = ["unix:q1", "unix:q2", "unix:q3", "unix:q4"]
    policy = g.calibrate_budget(np.ones(4), np.zeros(4, dtype=bool), ids, 0.5)

    def ranking(q):
        return Ranking(q.query_id, "unix", (Hit("unix:d1", 1.0, 1),), "c", "r")

    sparse = SimpleNamespace(
        manifest={"domain": "unix"},
        search=lambda q, k: ranking(q),
        query_stats=lambda q: SimpleNamespace(token_count=2, oov_ratio=0.0),
    )
    method = V2SearchMethod(
        "gated",
        sparse,
        trace=None,
        provenance={},
        scorer="gate_v2",
        threshold=policy.threshold,
        budget_policy=policy.to_json(),
        stats=None,
        gate=SimpleNamespace(score=lambda *args: np.ones(1)),
        extractor=SimpleNamespace(transform=lambda *args: FeatureVector((1.0,), "s")),
    )
    method.full = lambda q, r: r
    method.cheap = lambda q, r: r
    assert [method.search(Query(q, "unix", "test query")).use_dense for q in ids] == [
        True,
        True,
        False,
        False,
    ]


def test_fixed_tiers_prefers_earliest_on_ties():
    u = {"cc_alpha_0.1": np.ones(3), "rrf": np.ones(3), "bm25": np.zeros(3)}
    for a in range(2, 10):
        u[f"cc_alpha_0.{a}"] = np.ones(3)
    for a in range(1, 10):
        u[f"proxy_cc_0.{a}"] = np.zeros(3)
    tiers = g.fixed_tiers([u, u])
    assert tiers == {"h_star": "cc_alpha_0.1", "p_star": "bm25"}


def test_holm_step_down():
    import importlib.util
    import sys

    path = Path(__file__).resolve().parents[2] / "scripts_shared/experiment_v4.py"
    module_spec = importlib.util.spec_from_file_location("experiment_v4", path)
    module = importlib.util.module_from_spec(module_spec)
    sys.modules["experiment_v4"] = module
    module_spec.loader.exec_module(module)
    tests = {
        "a": {"p_value": 0.001},
        "b": {"p_value": 0.02},
        "c": {"p_value": 0.04},
        "d": {"p_value": 0.03},
    }
    module._holm(tests)
    assert tests["a"]["holm_reject"] and not tests["b"]["holm_reject"]
    assert not tests["c"]["holm_reject"] and not tests["d"]["holm_reject"]
