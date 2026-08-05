"""A tiny calculator package — experiment B fixture (pre-registered)."""


def _acc(values, start=0.0):
    total = start
    for v in values:
        total += v
    return total


def add(a, b):
    return a + b


def divide(a, b):
    # BUG (deliberate, fixture): zero denominator crashes instead of
    # returning the documented 0.0 sentinel.
    return a / b


def total(values):
    return _acc(values)
