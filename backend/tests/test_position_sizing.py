from app.risk.position_sizing import kelly_fraction


def test_no_trades_yields_zero_edge():
    result = kelly_fraction([], [])
    assert result["kelly_fraction"] == 0.0
    assert result["win_rate"] == 0.0


def test_wins_with_no_losses_yet_caps_at_max_fraction():
    result = kelly_fraction(win_pnls=[10.0, 20.0], loss_pnls=[], max_fraction=0.5)
    assert result["kelly_fraction"] == 0.5


def test_losses_with_no_wins_yields_zero():
    result = kelly_fraction(win_pnls=[], loss_pnls=[10.0], max_fraction=0.5)
    assert result["kelly_fraction"] == 0.0


def test_kelly_fraction_never_exceeds_max_fraction():
    result = kelly_fraction(win_pnls=[100.0] * 9, loss_pnls=[1.0], max_fraction=0.5)
    assert result["kelly_fraction"] <= 0.5


def test_kelly_fraction_is_never_negative_on_a_losing_edge():
    result = kelly_fraction(win_pnls=[1.0], loss_pnls=[100.0] * 9, max_fraction=0.5)
    assert result["kelly_fraction"] == 0.0
