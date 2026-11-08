"""anvil.email for the tests: send() appends to OUTBOX (the dev server shows it at GET /outbox)."""
OUTBOX = []


class SendFailure(Exception):
    pass


def send(**kw):
    for k in ("to", "subject"):
        if not kw.get(k):
            raise ValueError("email needs %s" % k)
    if not (kw.get("text") or kw.get("html")):
        raise ValueError("email needs text or html")
    OUTBOX.append(kw)
