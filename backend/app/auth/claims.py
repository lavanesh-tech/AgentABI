"""Pure JWT claims model — no SQLAlchemy/FastAPI/Pydantic import here,
same testability choice `app/trajectory/`/`app/replay/` made (Phases 6/7):
stdlib dataclasses only, unit-testable without a database or web
framework.

Deliberately minimal claim set. `sub` is the user id (a string, per JWT
convention — RFC 7519 requires `sub` to be a StringOrURI). `org_id` is
the organization the token was issued *for* — informational context for
routing a request, not an authorization grant. **Role is intentionally
NOT a claim.** A token's role would go stale the moment a user is
promoted/demoted in `OrganizationMember` after issuance, letting a
still-valid JWT carry a permission that no longer exists — the opposite
of "prefer security/correctness over convenience" (Phase A spec §4).
`app/api/deps/auth.py`'s `get_current_user` always reloads the current
role from the database; nothing trusts a role embedded in a token.
"""

from dataclasses import dataclass

REQUIRED_CLAIM_KEYS = frozenset({"sub", "iss", "aud", "iat", "exp"})


@dataclass(frozen=True)
class JWTClaims:
    sub: str
    iss: str
    aud: str
    iat: int
    exp: int
    org_id: str | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "sub": self.sub,
            "iss": self.iss,
            "aud": self.aud,
            "iat": self.iat,
            "exp": self.exp,
        }
        if self.org_id is not None:
            payload["org_id"] = self.org_id
        return payload
