"""Schema check for the App Board: which tables and columns does the live database have?

    GET /_/api/schema-check?tables=users,items  ->  {"tables": {"users": ["email", ...], "items": null}}

null = the database has no such table. Only table and column names come back (they are in the
app's anvil.yaml on GitHub anyway), never any data. The board compares them with anvil.yaml to
spot a Schema Mismatch nobody has accepted in the Anvil editor yet.
Same file in every app: APP_MAKER/template/server_code/SchemaCheck.py (APP_MAKER/tools/schema_check.py installs it).
"""
import anvil.server
from anvil.tables import app_tables


@anvil.server.http_endpoint("/schema-check")
def schema_check(tables="", **kw):
    out = {}
    for name in [t.strip() for t in str(tables).split(",") if t.strip()][:60]:
        try:
            out[name] = sorted(c["name"] for c in getattr(app_tables, name).list_columns())
        except Exception:
            out[name] = None
    return {"tables": out}
