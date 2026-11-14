"""The tiny call client_code/session_guard.py makes when someone comes back to a long-idle tab: if the server session
has expired, the call raises SessionExpiredError and the page reloads quietly instead of showing Anvil's box."""
import anvil.server


@anvil.server.callable
def session_ping():
    return True
