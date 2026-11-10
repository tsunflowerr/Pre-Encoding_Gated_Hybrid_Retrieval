from scripts_c.select_thresholds import _grid


def test_tied_validation_scores_skip_and_oov_is_counted() -> None:
    rows = [
        {"domain": domain, "score": score, "force_dense": forced, "U_B": 0.2, "U_H": 0.3}
        for domain, score, forced in (
            ("programmers", 0.8, False),
            ("programmers", 0.8, False),
            ("unix", 0.1, False),
            ("unix", 0.05, True),
        )
    ]
    grid = _grid(rows, [0.0, 0.5, 1.0])
    assert [point["actual_dense_count"] for point in grid] == [1, 1, 4]
    assert grid[1]["threshold"] == 0.8
    assert grid[1]["domains"]["unix"]["dense_count"] == 1
