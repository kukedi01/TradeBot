from app.strategies.indicators import bollinger_bands, macd_series, rsi, rsi_series, sma


class TestSma:
    def test_returns_none_below_period(self):
        assert sma([1.0, 2.0], period=5) is None

    def test_computes_trailing_average(self):
        assert sma([1.0, 2.0, 3.0, 4.0], period=2) == 3.5


class TestRsi:
    def test_returns_none_without_enough_history(self):
        assert rsi([1.0] * 5, period=14) is None

    def test_all_gains_is_maximally_overbought(self):
        prices = [100.0 + i for i in range(15)]
        assert rsi(prices, period=14) == 100.0

    def test_mixed_moves_land_between_extremes(self):
        prices = [100.0, 102.0, 101.0, 103.0, 102.0, 104.0, 103.0, 105.0, 104.0, 106.0, 105.0, 107.0, 106.0, 108.0, 107.0]
        value = rsi(prices, period=14)
        assert 0.0 < value < 100.0


class TestBollingerBands:
    def test_returns_none_below_period(self):
        assert bollinger_bands([1.0, 2.0], period=20) == (None, None, None)

    def test_middle_band_is_the_sma(self):
        prices = [100.0] * 20
        upper, middle, lower = bollinger_bands(prices, period=20)
        assert middle == 100.0
        # Zero variance in a flat series collapses the bands onto the middle.
        assert upper == 100.0
        assert lower == 100.0

    def test_bands_widen_with_volatility(self):
        flat = [100.0] * 20
        volatile = [100.0, 110.0] * 10
        _, _, flat_lower = bollinger_bands(flat, period=20)
        volatile_upper, _, volatile_lower = bollinger_bands(volatile, period=20)
        assert volatile_upper > flat_lower
        assert (volatile_upper - volatile_lower) > 0


class TestRsiSeries:
    def test_same_length_as_input_with_leading_nones(self):
        prices = [100.0 + i * 0.5 for i in range(30)]
        series = rsi_series(prices, period=14)
        assert len(series) == len(prices)
        assert all(v is None for v in series[:14])
        assert all(v is not None for v in series[14:])


class TestMacdSeries:
    def test_same_length_lists_with_leading_nones(self):
        prices = [100.0 + i * 0.3 for i in range(30)]
        macd_line, signal_line, histogram = macd_series(prices, fast_period=6, slow_period=13, signal_period=5)
        assert len(macd_line) == len(signal_line) == len(histogram) == len(prices)
        # The slow EMA can't produce a value before its own period elapses.
        assert all(v is None for v in macd_line[:12])
        assert macd_line[-1] is not None

    def test_histogram_is_macd_minus_signal(self):
        prices = [100.0 + i * 0.3 for i in range(30)]
        macd_line, signal_line, histogram = macd_series(prices)
        for m, s, h in zip(macd_line, signal_line, histogram):
            if m is None or s is None:
                assert h is None
            else:
                assert round(h, 9) == round(m - s, 9)

    def test_insufficient_history_returns_all_none(self):
        macd_line, signal_line, histogram = macd_series([100.0, 101.0], fast_period=6, slow_period=13, signal_period=5)
        assert all(v is None for v in macd_line)
        assert all(v is None for v in signal_line)
