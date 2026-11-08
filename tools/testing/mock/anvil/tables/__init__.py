"""A strict in-memory version of Anvil's data tables.

The schema comes from tools/sync_to_anvil.py (TABLES), the same definition that is pushed to Anvil,
so a wrong column name or a value of the wrong type fails here just like it would live.
Supports: add_row, search (keyword matches, q.* queries, order_by), get, get_by_id, delete_all_rows,
row[col], row.update(), row.delete(), row.get_id(), dict(row), link_single, link_multiple, media.
"""
import datetime as _dt
import itertools
import json as _json
import pathlib as _pl
import sys as _sys

import os as _os

if _os.environ.get("ANVIL_APP_YAML"):
    # A "git" app (APP_MAKER/tools/gitapp_test.py): the schema is the app's own anvil.yaml (needs PyYAML).
    import yaml as _yaml
    _schema = (_yaml.safe_load(open(_os.environ["ANVIL_APP_YAML"], encoding="utf-8")) or {}).get("db_schema") or {}
    if isinstance(_schema, list):
        _schema = {t["name"]: t for t in _schema}
    _TABLES = {n: [(c["name"], c["type"]) + ((c["target"],) if c.get("target") else ()) for c in (t.get("columns") or [])]
               for n, t in _schema.items()}
else:
    _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[4]))  # tools/
    from sync_to_anvil import TABLES as _TABLES  # noqa: E402

_ids = itertools.count(1)
USERS_BUILTIN = [("email", "string"), ("enabled", "bool"), ("signed_up", "datetime"), ("last_login", "datetime"),
                 ("password_hash", "string"), ("confirmed_email", "bool"), ("n_password_failures", "number")]
TYPES = {}
for _name, _cols in _TABLES.items():
    TYPES[_name] = {c[0]: c[1] for c in ((USERS_BUILTIN if _name == "users" else []) + list(_cols))}
if "users" not in TYPES:
    TYPES["users"] = dict(USERS_BUILTIN)


class TableError(Exception):
    pass


class NoSuchColumnError(KeyError):
    pass


class _Query(object):
    """A q.* query: test(value) says whether a cell value matches."""
    def __init__(self, test, kw=None, combine=None):
        self.test, self.kw, self.combine = test, kw, combine


def _matches(row, col, want):
    have = row[col]
    if isinstance(want, _Query):
        return want.test(have)
    if TYPES[row._t.name].get(col) == "link_multiple" and isinstance(want, (list, tuple)):
        return all(any(w is h for h in (have or [])) for w in want)
    return have == want


def _row_matches(row, positional, kw):
    for k, v in kw.items():
        if not _matches(row, k, v):
            return False
    for p in positional:
        if isinstance(p, _Query) and p.combine:
            if not p.combine(row):
                return False
    return True


class Row(object):
    def __init__(self, table, kw):
        self._t = table
        self._id = "[%d,%d]" % (len(table.name), next(_ids))
        self._d = {c: None for c in table.cols}
        self.update(**kw)

    def _check(self, k):
        if k not in self._t.cols:
            raise NoSuchColumnError("No such column %r in table %s" % (k, self._t.name))

    def __getitem__(self, k):
        self._check(k)
        if self._d is None:
            raise TableError("This row has been deleted")
        return self._d[k]

    def __setitem__(self, k, v):
        self.update(**{k: v})

    def update(self, **kw):
        if self._d is None:
            raise TableError("This row has been deleted")
        for k, v in kw.items():
            self._check(k)
            typ = TYPES[self._t.name].get(k)
            where = "%s.%s" % (self._t.name, k)
            if v is not None:
                if typ == "date" and (not isinstance(v, _dt.date) or isinstance(v, _dt.datetime)):
                    raise TypeError("%s needs a date, got %r" % (where, v))
                if typ == "datetime" and not isinstance(v, _dt.datetime):
                    raise TypeError("%s needs a datetime, got %r" % (where, v))
                if typ == "number" and (isinstance(v, bool) or not isinstance(v, (int, float))):
                    raise TypeError("%s needs a number, got %r" % (where, v))
                if typ == "string" and not isinstance(v, str):
                    raise TypeError("%s needs a string, got %r" % (where, v))
                if typ == "bool" and not isinstance(v, bool):
                    raise TypeError("%s needs a bool, got %r" % (where, v))
                if typ == "link_single" and not isinstance(v, Row):
                    raise TypeError("%s needs a row, got %r" % (where, v))
                if typ == "link_multiple":
                    if not isinstance(v, (list, tuple)) or not all(isinstance(x, Row) for x in v):
                        raise TypeError("%s needs a list of rows, got %r" % (where, v))
                    v = list(v)
                if typ == "media":
                    import anvil
                    if not isinstance(v, anvil.Media):
                        raise TypeError("%s needs a Media object, got %r" % (where, v))
                if typ == "simpleObject":
                    try:
                        v = _json.loads(_json.dumps(v))  # must be JSON-able; stored as a copy, like Anvil
                    except TypeError as e:
                        raise TypeError("%s needs a JSON-able value: %s" % (where, e))
            self._d[k] = v

    def get_id(self):
        return self._id

    def delete(self):
        self._t.rows.remove(self)
        self._d = None

    def keys(self):
        return list(self._t.cols)

    def items(self):
        return [(k, self[k]) for k in self._t.cols]

    def __iter__(self):
        return iter(self.items())

    def __eq__(self, o):
        return self is o

    def __ne__(self, o):
        return self is not o

    def __hash__(self):
        return id(self)

    def __repr__(self):
        return "<Row %s %s>" % (self._t.name, self._id)


class order_by(object):
    def __init__(self, col, ascending=True):
        self.col, self.asc = col, ascending


class SearchIterator(list):
    """search() result: iterate, len(), index and slice, like Anvil's."""
    pass


class Table(object):
    def __init__(self, name):
        self.name = name
        self.cols = list(TYPES[name])
        self.rows = []

    def add_row(self, **kw):
        r = Row(self, kw)
        self.rows.append(r)
        return r

    def add_rows(self, rows):
        return [self.add_row(**r) for r in rows]

    def search(self, *args, **kw):
        for k in kw:
            if k not in self.cols:
                raise NoSuchColumnError("No such column %r in table %s" % (k, self.name))
        orders = [a for a in args if isinstance(a, order_by)]
        queries = [a for a in args if isinstance(a, _Query)]
        for q in queries:
            for k in (q.kw or {}):
                if k not in self.cols:
                    raise NoSuchColumnError("No such column %r in table %s" % (k, self.name))
        out = [r for r in self.rows if _row_matches(r, queries, kw)]
        for o in reversed(orders):
            if o.col not in self.cols:
                raise NoSuchColumnError("No such column %r in table %s" % (o.col, self.name))
            present = [r for r in out if r[o.col] is not None]
            missing = [r for r in out if r[o.col] is None]
            present.sort(key=lambda r: r[o.col], reverse=not o.asc)
            out = present + missing
        return SearchIterator(out)

    def get(self, *args, **kw):
        m = self.search(*args, **kw)
        if len(m) > 1:
            raise TableError("More than one row matched this query")
        return m[0] if m else None

    def get_by_id(self, row_id, *a, **k):
        return next((r for r in self.rows if r._id == row_id), None)

    def has_row(self, row):
        return row in self.rows

    def delete_all_rows(self):
        for r in list(self.rows):
            r.delete()

    def list_columns(self):
        return [{"name": c, "type": TYPES[self.name][c]} for c in self.cols]


class _Tx(object):
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def abort(self): pass


def Transaction(relaxed=False):
    return _Tx()


def in_transaction(f=None, relaxed=False):
    """@in_transaction and @in_transaction(relaxed=True)."""
    if f is None:
        return lambda g: g
    return f


batch_update = _Tx()
batch_delete = _Tx()
