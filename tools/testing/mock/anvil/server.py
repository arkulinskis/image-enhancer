"""Enough of anvil.server for the tests and the dev server.

@callable functions are registered in CALLABLES, so tests and the dev server can call them by name
exactly like the browser does (require_user is enforced). `session` is per browser session: the dev
server swaps it with use_session(sid).
"""
CALLABLES = {}   # name -> (function, require_user)
ENDPOINTS = {}   # path -> function
BACKGROUND = {}  # name -> function


class PermissionDenied(Exception):
    pass


class SessionExpiredError(Exception):
    pass


class AppOfflineError(Exception):
    pass


class InternalError(Exception):
    pass


class NoServerFunctionError(Exception):
    pass


class HttpError(Exception):
    def __init__(self, status=500, content=""):
        Exception.__init__(self, "HTTP %s" % status)
        self.status, self.content = status, content


def callable(*args, **kwargs):
    """@anvil.server.callable, @anvil.server.callable("name"), @anvil.server.callable(require_user=True)."""
    def register(f, name=None):
        CALLABLES[name or f.__name__] = (f, kwargs.get("require_user"))
        return f
    if args and hasattr(args[0], "__call__"):
        return register(args[0])
    name = args[0] if args and isinstance(args[0], str) else None
    return lambda f: register(f, name)


def call(name, *args, **kwargs):
    """Server-to-server call (and what tests use): runs the registered function with Anvil's rules."""
    if name not in CALLABLES:
        raise NoServerFunctionError("No server function matching %r has been registered" % name)
    f, need = CALLABLES[name]
    if need:
        import anvil.users
        u = anvil.users.get_user()
        if u is None or (hasattr(need, "__call__") and not need(u)):
            raise PermissionDenied("You must be logged in to call this server function")
    return f(*args, **kwargs)


call_s = call


def http_endpoint(path, **kw):
    def deco(f):
        ENDPOINTS[path] = f
        return f
    return deco


def route(path, **kw):
    return http_endpoint(path, **kw)


class HttpResponse(object):
    def __init__(self, status=200, body="", headers=None):
        self.status, self.body, self.headers = status, body, headers or {}


class _Request(object):
    def __init__(self):
        self.headers, self.remote_address, self.origin, self.body, self.query_params = {}, "127.0.0.1", "http://localhost", None, {}
        self.method = "GET"

    def body_json(self):
        import json
        return json.loads(self.body or "null")


request = _Request()


def background_task(f):
    BACKGROUND[f.__name__] = f
    return f


class _Task(object):
    def __init__(self, result): self._r = result
    def get_return_value(self): return self._r
    def is_completed(self): return True
    def is_running(self): return False


def launch_background_task(name, *args, **kwargs):
    return _Task(BACKGROUND[name](*args, **kwargs))


def portable_class(cls=None, name=None):
    if cls is None or isinstance(cls, str):
        return lambda c: c
    return cls


ORIGIN = ["https://app-test.anvil.app"]


def get_app_origin(*a):
    return ORIGIN[0]


class _Session(object):
    """Like Anvil's anvil.server.session: item access, get(), `in`, pop() and `del`."""
    def __init__(self):
        self._all = {None: {}}
        self._sid = None

    def use(self, sid):
        self._sid = sid
        self._all.setdefault(sid, {})

    def clear_all(self):
        self._all = {None: {}}
        self._sid = None

    @property
    def _d(self):
        return self._all.setdefault(self._sid, {})

    def __getitem__(self, k): return self._d[k]
    def __setitem__(self, k, v): self._d[k] = v
    def __delitem__(self, k): del self._d[k]
    def __contains__(self, k): return k in self._d
    def get(self, k, default=None): return self._d.get(k, default)
    def pop(self, k, *default): return self._d.pop(k, *default)


session = _Session()


class UplinkDisconnectedError(Exception):
    pass


class _Caller(object):
    """Who called the current server function: tests set CONTEXT to act as the PC (trusted) or a browser."""
    def __init__(self, type_="browser", trusted=False):
        self.type, self.is_trusted = type_, trusted


class _Context(object):
    def __init__(self):
        self.type, self.remote_caller, self.background_task_id = "server_module", _Caller(), None


context = _Context()


def as_pc(flag=True):
    context.remote_caller = _Caller("uplink", True) if flag else _Caller()


def list_background_tasks(all_environments=False):
    return []


def get_api_origin(*a):
    return ORIGIN[0] + "/_/api"
