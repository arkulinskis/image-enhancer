"""anvil.http for the tests. No real network: register fake replies in REPLIES (url prefix -> value or function)."""
import json as _json

REPLIES = {}
CALLS = []


class HttpError(Exception):
    def __init__(self, status=500, content=""):
        Exception.__init__(self, "HTTP %s" % status)
        self.status, self.content = status, content


def request(url, method="GET", data=None, json=False, headers=None, username=None, password=None, timeout=None):
    CALLS.append({"url": url, "method": method, "data": data, "headers": headers})
    for prefix, reply in REPLIES.items():
        if url.startswith(prefix):
            value = reply(url, method, data) if hasattr(reply, "__call__") else reply
            if isinstance(value, HttpError):
                raise value
            return _json.loads(_json.dumps(value)) if json else value
    raise HttpError(599, "no fake reply registered for %s (tools/testing/mock/anvil/http.py)" % url)


def url_encode(s):
    from urllib.parse import quote
    return quote(str(s), safe="")
