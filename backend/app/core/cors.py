"""Environment-aware CORS configuration (Security Phase D spec §10).

`build_cors_kwargs` is a pure function (no FastAPI import — it returns
plain keyword arguments for `CORSMiddleware`) so it's independently
`pytest --noconftest`-testable. `origins` always comes from
`Settings.cors_allow_origins` — never hardcoded here, never `["*"]` in
this codebase (asserted below), so the same function is correct for
both local dev (configured to `localhost`/`127.0.0.1` origins) and
production (configured to the real trusted frontend origin(s)); nothing
about the *behavior* differs by environment, only what operators put in
`CORS_ALLOW_ORIGINS`. The one thing this function enforces regardless
of environment: credentials are never combined with a wildcard origin
(the browser spec forbids it, and permitting it here would silently
produce a CORS configuration Chrome/Firefox reject anyway).
"""

_SAFE_METHODS = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
_SAFE_HEADERS = ["Authorization", "Content-Type", "X-Correlation-ID"]


def build_cors_kwargs(*, allow_origins: list[str], allow_credentials: bool) -> dict[str, object]:
    if allow_credentials and "*" in allow_origins:
        raise ValueError("CORS: cannot combine allow_credentials=True with a wildcard origin")

    return {
        "allow_origins": allow_origins,
        "allow_credentials": allow_credentials,
        # Only the methods/headers this API actually uses — not "*".
        # Every route in this codebase is GET/POST/PATCH/DELETE; OPTIONS
        # is the CORS preflight method itself.
        "allow_methods": _SAFE_METHODS,
        "allow_headers": _SAFE_HEADERS,
        # The correlation id middleware (app/core/middleware.py) sets
        # this response header; browsers hide non-simple response
        # headers from JS unless explicitly exposed.
        "expose_headers": ["X-Correlation-ID"],
    }
