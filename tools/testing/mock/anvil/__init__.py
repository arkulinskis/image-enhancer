"""A small, strict stand-in for the parts of Anvil the server code uses, for local tests and the dev server.

Only what our apps need is here. If server code needs more of Anvil, add it here (keep it strict:
the point is to fail locally where Anvil would fail live).
"""


class Media(object):
    def __init__(self, content_type="application/octet-stream", content=b"", name=None):
        self.content_type, self._bytes, self.name = content_type, content, name
        self.url = None

    def get_bytes(self):
        return self._bytes

    @property
    def length(self):
        return len(self._bytes or b"")


class BlobMedia(Media):
    pass


class URLMedia(Media):
    def __init__(self, url):
        Media.__init__(self, "application/octet-stream", b"", None)
        self.url = url
