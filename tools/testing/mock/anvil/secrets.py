"""anvil.secrets for the tests: put fake values in SECRETS."""
SECRETS = {}


class SecretError(Exception):
    pass


def get_secret(name):
    if name not in SECRETS:
        raise SecretError("No secret called %r (add it in the Anvil editor: App Secrets)" % name)
    return SECRETS[name]
