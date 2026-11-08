"""anvil.tz for the tests: timezone objects for datetimes."""
import datetime as _dt


def tzutc():
    return _dt.timezone.utc


class tzoffset(_dt.tzinfo):
    def __init__(self, seconds=None, hours=None, minutes=None):
        total = (seconds or 0) + (hours or 0) * 3600 + (minutes or 0) * 60
        self._off = _dt.timedelta(seconds=total)

    def utcoffset(self, d): return self._off
    def dst(self, d): return _dt.timedelta(0)
    def tzname(self, d): return "UTC%+.1f" % (self._off.total_seconds() / 3600)


def tzlocal():
    return _dt.timezone.utc  # the server's "local" zone is UTC on Anvil
