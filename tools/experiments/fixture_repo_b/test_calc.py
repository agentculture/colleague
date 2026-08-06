import calc


def test_add():
    assert calc.add(2, 3) == 5


def test_total():
    assert calc.total([1.0, 2.0, 3.0]) == 6.0


def test_divide():
    assert calc.divide(6, 3) == 2


def test_divide_by_zero_returns_sentinel():
    assert calc.divide(1, 0) == 0.0
