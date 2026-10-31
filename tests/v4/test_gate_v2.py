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
