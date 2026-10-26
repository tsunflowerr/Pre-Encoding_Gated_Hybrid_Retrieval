import numpy as np
import pytest

from scripts_shared.report_release import paired_speedups


def test_speedup_bootstrap_keeps_methods_paired_and_domain_counts_fixed():
    result = paired_speedups(
        {
            "programmers": np.array([[10.0, 20.0, 5.0], [20.0, 40.0, 10.0]]),
            "unix": np.array([[100.0, 200.0, 50.0]]),
        },
        samples=100,
        seed=42,
    )
    assert result["h_star"]["mean_speedup_percent"] == pytest.approx(50)
    assert result["s_star"]["mean_speedup_percent"] == pytest.approx(75)
    assert result["h_star"]["speedup_two_sided_95_percent"] == pytest.approx([50, 50])
    assert result["s_star"]["speedup_two_sided_95_percent"] == pytest.approx([75, 75])


def test_speedup_bootstrap_rejects_unpaired_dimensions():
    with pytest.raises(ValueError, match="three-method"):
        paired_speedups({"unix": np.ones((5, 2))}, samples=10)
