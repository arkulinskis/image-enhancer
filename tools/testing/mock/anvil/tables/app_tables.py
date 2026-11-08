from . import Table, TYPES

for _n in TYPES:
    globals()[_n] = Table(_n)


def _all():
    return [globals()[n] for n in TYPES]
