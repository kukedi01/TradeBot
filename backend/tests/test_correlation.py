from app.risk.correlation import (
    HIGH_CORRELATION_THRESHOLD,
    MIN_SIZE_MULTIPLIER,
    compute_correlation_matrix_from_returns,
    correlation_size_multiplier,
    returns_from_closes,
)


def test_returns_from_closes_computes_pct_change():
    returns = returns_from_closes([100.0, 110.0, 99.0])
    assert returns == [0.1, -0.1]


def test_returns_from_closes_skips_zero_denominator():
    returns = returns_from_closes([0.0, 5.0])
    assert returns == []


class TestCorrelationMatrix:
    def test_identical_series_are_perfectly_correlated(self):
        returns = {"A": [0.01, -0.02, 0.03, 0.01], "B": [0.01, -0.02, 0.03, 0.01]}
        matrix = compute_correlation_matrix_from_returns(returns)
        assert matrix["A"]["B"] == 1.0
        assert matrix["A"]["A"] == 1.0

    def test_inverse_series_are_perfectly_anticorrelated(self):
        returns = {"A": [0.01, -0.02, 0.03, 0.01], "B": [-0.01, 0.02, -0.03, -0.01]}
        matrix = compute_correlation_matrix_from_returns(returns)
        assert round(matrix["A"]["B"], 6) == -1.0

    def test_missing_returns_default_to_zero_correlation(self):
        matrix = compute_correlation_matrix_from_returns({"A": [0.01, 0.02], "B": []})
        assert matrix["A"]["B"] == 0.0
        assert matrix["B"]["A"] == 0.0


class TestCorrelationSizeMultiplier:
    def test_no_existing_holdings_leaves_size_untouched(self):
        multiplier = correlation_size_multiplier(
            "ETH/EUR", holdings={}, prices={"ETH/EUR": 2000.0}, correlation_matrix={}
        )
        assert multiplier == 1.0

    def test_below_threshold_correlation_leaves_size_untouched(self):
        matrix = {"ETH/EUR": {"BTC/EUR": HIGH_CORRELATION_THRESHOLD - 0.01}}
        multiplier = correlation_size_multiplier(
            "ETH/EUR",
            holdings={"BTC": 1.0},
            prices={"ETH/EUR": 2000.0, "BTC/EUR": 60000.0},
            correlation_matrix=matrix,
        )
        assert multiplier == 1.0

    def test_perfect_correlation_shrinks_to_the_floor(self):
        matrix = {"ETH/EUR": {"BTC/EUR": 1.0}}
        multiplier = correlation_size_multiplier(
            "ETH/EUR",
            holdings={"BTC": 1.0},
            prices={"ETH/EUR": 2000.0, "BTC/EUR": 60000.0},
            correlation_matrix=matrix,
        )
        assert round(multiplier, 3) == MIN_SIZE_MULTIPLIER

    def test_weighted_by_held_value_across_multiple_assets(self):
        # BTC dominates the held value and is highly correlated; XRP is a
        # tiny position and uncorrelated -- the weighted result should sit
        # much closer to BTC's contribution.
        matrix = {"ETH/EUR": {"BTC/EUR": 1.0, "XRP/EUR": 0.0}}
        multiplier = correlation_size_multiplier(
            "ETH/EUR",
            holdings={"BTC": 1.0, "XRP": 1.0},
            prices={"ETH/EUR": 2000.0, "BTC/EUR": 60000.0, "XRP/EUR": 1.0},
            correlation_matrix=matrix,
        )
        assert multiplier < 1.0
