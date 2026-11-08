"""anvil.tables.query (import anvil.tables.query as q) for the tests."""
import re as _re

from . import _Query, _matches


def _cmp(fn):
    return lambda v: _Query(lambda have: have is not None and fn(have, v))


less_than = _cmp(lambda a, b: a < b)
less_than_or_equal_to = _cmp(lambda a, b: a <= b)
greater_than = _cmp(lambda a, b: a > b)
greater_than_or_equal_to = _cmp(lambda a, b: a >= b)


def between(min, max, min_inclusive=True, max_inclusive=False):
    def test(have):
        if have is None:
            return False
        lo = have >= min if min_inclusive else have > min
        hi = have <= max if max_inclusive else have < max
        return lo and hi
    return _Query(test)


def _like(pattern, flags):
    rx = "^" + "".join(".*" if ch == "%" else "." if ch == "_" else _re.escape(ch) for ch in pattern) + "$"
    return _Query(lambda have: isinstance(have, str) and _re.match(rx, have, flags | _re.S) is not None)


def like(pattern):
    return _like(pattern, 0)


def ilike(pattern):
    return _like(pattern, _re.I)


def full_text_match(query, raw=False):
    words = [w for w in _re.findall(r"\w+", str(query).lower())]
    return _Query(lambda have: isinstance(have, str) and all(w in have.lower() for w in words))


def _combine(kind, values, kw):
    """any_of / all_of / none_of: either on one column (q.any_of(1, 2) as a value)
    or across columns (q.any_of(title=q.ilike('%x%'), body=...) as a positional query)."""
    def test(have):
        hits = [(v.test(have) if isinstance(v, _Query) else have == v) for v in values]
        return any(hits) if kind == "any" else all(hits) if kind == "all" else not any(hits)

    def combine(row):
        hits = [_matches(row, k, v) for k, v in kw.items()]
        hits += [(v.combine(row) if isinstance(v, _Query) and v.combine else True) for v in values]
        return any(hits) if kind == "any" else all(hits) if kind == "all" else not any(hits)
    return _Query(test, kw=kw, combine=combine if (kw or any(isinstance(v, _Query) and v.combine for v in values)) else None)


def any_of(*values, **kw):
    return _combine("any", values, kw)


def all_of(*values, **kw):
    return _combine("all", values, kw)


def none_of(*values, **kw):
    return _combine("none", values, kw)


def not_(*values, **kw):
    return _combine("none", values, kw)


def fetch_only(*cols, **links):
    return None  # a hint for Anvil's loader; no effect here
