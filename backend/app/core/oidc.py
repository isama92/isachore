"""OpenID Connect single sign-on: everything that talks to the identity provider.

The security boundary for SSO. The router (app/api/v1/oidc.py) owns the policy - who
is allowed in, and what a refusal looks like - while this module owns the protocol:
discovery, the authorization-code exchange with PKCE, ID token signature and claim
verification, and reading the account's email back out.

Optional, like SMTP and encryption: with no provider configured ``oidc_configured()``
is false, the sign-in button never renders and the endpoints 404. Unlike those two,
a *half* configured provider refuses boot outside a dev environment
(app/core/startup.py), because the failure would otherwise land on somebody's first
sign-in attempt instead of at deploy time.

Two library choices worth knowing, because both have a wrong-looking neighbour:

- **authlib, but only ``integrations.httpx_client``.** Not
  ``authlib.integrations.starlette_client``, which is the obvious import and the wrong
  one: it keeps ``state`` and ``nonce`` in a Starlette session, so adopting it would
  mean adding ``SessionMiddleware`` and a second signed-cookie mechanism competing
  with this codebase's established "random token in an httpOnly cookie, SHA-256 hash
  in Postgres" pattern. Here the flow's state lives in ``oidc_login_states`` and the
  caller passes it back in.
- **joserfc for the JOSE work, not ``authlib.jose``.** They are the same author's old
  and new APIs; ``authlib.jose`` emits a deprecation warning pointing here and is
  scheduled to go away in authlib 2.0, which would silently take ID token
  verification with it.

Every failure surfaces as ``OidcError``, so the router has exactly one thing to catch
and can keep its own error vocabulary (the ``sso_error`` codes) separate from the
provider's.
"""

import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from app.core.config import settings
from app.core.security import generate_token

logger = logging.getLogger(__name__)

# Shared error detail when an SSO action is attempted without a provider configured.
NO_OIDC_DETAIL = "Single sign-on is not configured on this server"

# Discovery documents and JWKS are cached for an hour. Both are effectively static,
# and re-fetching two documents on every sign-in would put the provider on the
# critical path twice more than it needs to be. Key rotation does not wait for the
# TTL: an ID token signed by a key we have never seen forces a refresh (see
# _verify_id_token), which is the case the TTL would otherwise handle far too slowly.
_CACHE_TTL = 3600.0
_HTTP_TIMEOUT = 10.0

# Fallback when the provider's metadata omits id_token_signing_alg_values_supported.
# RS256 is the one algorithm the OIDC spec requires every provider to implement.
_DEFAULT_ALGORITHMS = ("RS256",)

# The signing algorithms we will verify against, whatever the provider's metadata
# advertises. This is an allowlist rather than a blocklist because the interesting
# entries are the ones nobody thinks of: `none` disables verification altogether (and
# joserfc will decode such a token, warning rather than refusing), and the HS* family is
# symmetric, so it verifies with a *shared secret* rather than a published key - which
# for a client holding a client secret is the classic algorithm-confusion setup. Since
# the advertised list is provider-controlled data, intersecting is what keeps a hostile
# or compromised discovery document from choosing how its own tokens get checked.
_ALLOWED_ALGORITHMS = frozenset(
    {
        "RS256",
        "RS384",
        "RS512",
        "ES256",
        "ES384",
        "ES512",
        "PS256",
        "PS384",
        "PS512",
        "EdDSA",
    }
)

# Clock skew allowed on exp/iat, in seconds. Matches authlib's own default for the
# same job; without some leeway a provider whose clock is a few seconds ahead makes
# every sign-in fail on `iat` in the future.
_CLAIMS_LEEWAY = 120

# Caches keyed by issuer rather than held in a bare module global, so that changing
# the configured issuer (which tests do constantly, and an operator does once) cannot
# be served a document fetched for the previous one.
_metadata_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_jwks_cache: dict[str, tuple[float, KeySet]] = {}


class OidcError(Exception):
    """The provider could not be talked to, or said something unacceptable.

    Deliberately one exception for the whole module: the router turns any of it into
    the same `sso_error=provider` redirect, because the distinctions that matter to a
    user (no account, unverified email) are the router's own and the ones that matter
    to an operator belong in the log, not in a query string.
    """


@dataclass(frozen=True, slots=True)
class OidcIdentity:
    """Who the provider says just signed in.

    ``subject`` and ``issuer`` are the durable identity - the pair a local account is
    linked by. ``email`` is how a *first* sign-in finds the account to link to, and is
    optional because a provider can be configured without the email scope; the router
    treats a missing one as "no account".
    """

    subject: str
    issuer: str
    email: str | None


def oidc_configured() -> bool:
    """Whether enough is set to run the flow: the issuer plus both client
    credentials. ``oidc_provider_name`` is deliberately excluded - it only labels a
    button, so a deploy that forgot it should still be able to sign in."""
    return bool(settings.oidc_issuer and settings.oidc_client_id and settings.oidc_client_secret)


def redirect_uri() -> str:
    """Where the provider sends the browser back, and so also the value an operator
    has to register with the provider (Admin > Server settings displays it).

    Derived from ``app_base_url`` rather than configured separately: that setting
    already exists to name the public origin of the SPA, and one fewer url to keep in
    step is one fewer way to get a mismatch that only shows up as the provider
    refusing the callback. It resolves correctly in dev too, because the Vite dev
    server proxies /api to the backend.
    """
    return f"{settings.app_base_url.rstrip('/')}/api/v1/auth/oidc/callback"


def reset_caches() -> None:
    """Drop the cached discovery documents and key sets. For tests, which change the
    configured issuer between cases; nothing in the app calls this."""
    _metadata_cache.clear()
    _jwks_cache.clear()


def _require_configured() -> str:
    if not oidc_configured():
        raise OidcError(NO_OIDC_DETAIL)
    # str() rather than an assert: oidc_configured() has already proved the setting is
    # a non-empty string, and an assert for the type checker's benefit alone would be
    # stripped under python -O.
    return str(settings.oidc_issuer).rstrip("/")


def _client(**kwargs: Any) -> AsyncOAuth2Client:
    return AsyncOAuth2Client(
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        scope=settings.oidc_scopes,
        redirect_uri=redirect_uri(),
        # Ask for PKCE. Authlib then derives the S256 challenge from the verifier we
        # pass to create_authorization_url and echoes the verifier at the token
        # endpoint, which is what binds the callback's `code` to the browser that
        # started the flow.
        code_challenge_method="S256",
        timeout=_HTTP_TIMEOUT,
        **kwargs,
    )


async def discover() -> dict[str, Any]:
    """The provider's OIDC metadata, cached.

    Also the one place the configured issuer is checked against what the provider
    calls itself, which OIDC Discovery requires: a mismatch means the url is pointing
    somewhere other than where its tokens will claim to come from, and every
    signature check downstream would fail with a much less obvious message.

    Trailing slashes are ignored on both sides of that comparison. Authentik's issuer
    conventionally ends in one and plenty of operators will paste it either way, so
    being strict here would reject a correct configuration over punctuation. The
    provider's own spelling is what gets used for the `iss` claim check, since that is
    what it signs.
    """
    issuer = _require_configured()
    cached = _metadata_cache.get(issuer)
    if cached is not None and time.monotonic() - cached[0] < _CACHE_TTL:
        return cached[1]

    url = f"{issuer}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(url)
            response.raise_for_status()
            metadata = response.json()
    # InvalidURL is deliberately NOT an httpx.HTTPError, so it needs naming: httpx raises it
    # for a url that is too long, carries a control character, has an invalid port or a bad
    # IDNA host - all reachable here from a mistyped OIDC_ISSUER.
    except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
        logger.warning("OIDC discovery failed for %s: %s", url, exc)
        raise OidcError(f"could not fetch OIDC metadata from {url}") from exc

    # `200 OK` says nothing about the shape. A captive portal, an error page rendered as
    # JSON, or a proxy substituting its own body all produce valid JSON that is not an
    # object, and every `metadata.get(...)` below (here and in the callers) would then raise
    # AttributeError - a 500 out of the endpoint rather than the "provider" refusal this is
    # meant to become.
    if not isinstance(metadata, dict):
        raise OidcError(f"OIDC metadata from {url} is not a JSON object")

    advertised = str(metadata.get("issuer", ""))
    if advertised.rstrip("/") != issuer:
        logger.error(
            "OIDC issuer mismatch: OIDC_ISSUER is %r but the provider calls itself %r",
            settings.oidc_issuer,
            advertised,
        )
        raise OidcError("the provider's metadata advertises a different issuer")

    _metadata_cache[issuer] = (time.monotonic(), metadata)
    return metadata


async def _key_set(metadata: dict[str, Any], *, force: bool = False) -> KeySet:
    """The provider's public signing keys, cached alongside its metadata."""
    issuer = _require_configured()
    cached = _jwks_cache.get(issuer)
    if cached is not None and not force and time.monotonic() - cached[0] < _CACHE_TTL:
        return cached[1]

    url = metadata.get("jwks_uri")
    if not url:
        raise OidcError("the provider's metadata has no jwks_uri")
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(str(url))
            response.raise_for_status()
            key_set = KeySet.import_key_set(response.json())
    # None of the four extra classes is defensive padding. import_key_set raises TypeError for
    # a JSON array or scalar and KeyError for an object with no "keys" member, which is exactly
    # what a provider answering `{"error": "..."}` with status 200 sends; and InvalidURL is
    # deliberately outside httpx.HTTPError, so a `jwks_uri` that is too long or carries a
    # control character needs naming too. None of them is a JoseError, so without them a
    # common provider bug becomes a 500 rather than the "provider" refusal.
    except (
        httpx.HTTPError,
        httpx.InvalidURL,
        ValueError,
        TypeError,
        KeyError,
        JoseError,
    ) as exc:
        # %r on the url: it comes from the provider's discovery document, so it is the one
        # value here this process did not choose.
        logger.warning("OIDC jwks fetch failed for %r: %s", url, exc)
        raise OidcError(f"could not fetch signing keys from {url}") from exc

    _jwks_cache[issuer] = (time.monotonic(), key_set)
    return key_set


async def begin(*, state: str) -> tuple[str, str, str]:
    """Start a flow: the url to send the browser to, plus the ``nonce`` and PKCE
    ``code_verifier`` that ``complete`` will need to check what comes back.

    The caller stores those two server-side and passes them back in, which is the
    whole reason this returns three things rather than one url. ``state`` is passed
    *in* rather than generated here, because the caller already has one: it doubles as
    the value of the cookie that binds this flow to this browser, so it has to be the
    caller's own token to hash into ``oidc_login_states``.
    """
    metadata = await discover()
    endpoint = metadata.get("authorization_endpoint")
    if not endpoint:
        raise OidcError("the provider's metadata has no authorization_endpoint")

    nonce = generate_token()
    # 43 characters of unreserved token, which is exactly the PKCE minimum length.
    code_verifier = generate_token()
    async with _client() as client:
        url, _ = client.create_authorization_url(
            str(endpoint), state=state, code_verifier=code_verifier, nonce=nonce
        )
    return url, nonce, code_verifier


def describe_token(id_token: str) -> str:
    """How a token was put together, for a log line when it will not verify.

    A bare `id_token did not verify: DecodeError` says only that something is wrong, and the
    five things it could be (an unsigned token, a symmetric one, an encrypted one, a key id we
    do not hold, a mangled string) each need a different fix on the provider. This turns that
    into `3 segments, alg=RS256 kid=abc123` and names the keys we had to check it against, so
    the answer is in the log instead of in a bisect.

    **Only the header, never the payload.** The JOSE header describes how the token was made -
    algorithm, key id, media types - and is public by construction. The payload is the
    identity: `sub`, `email`, and whatever else the provider was asked for, so it is exactly
    what must not end up in a log that ships off-box under someone else's retention. The
    signature is left out too, being the one part an attacker would want.
    """
    segments = id_token.split(".")
    shape = f"{len(segments)} segments"
    if len(segments) < 2:
        return shape
    try:
        # A compact JOSE header is base64url with the padding stripped; put it back.
        raw = segments[0]
        header = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except (ValueError, TypeError, json.JSONDecodeError):
        return f"{shape}, unreadable header"
    if not isinstance(header, dict):
        return f"{shape}, header is not an object"
    # `enc` only appears on an encrypted token, and five segments is the other half of that
    # tell, so an operator who set an Encryption Key on the provider by mistake reads it here
    # rather than wondering why a working provider produces garbage.
    named = " ".join(f"{k}={header[k]}" for k in ("alg", "enc", "kid", "typ", "cty") if k in header)
    return f"{shape}, {named}" if named else shape


def describe_keys(key_set: KeySet) -> str:
    """The key ids we were checking against, so a `kid` mismatch is visible on one line."""
    try:
        kids = [key.kid or "<no kid>" for key in key_set.keys]
    except Exception:  # pragma: no cover - defensive, a KeySet always has .keys
        return "unknown"
    return ", ".join(kids) if kids else "none published"


def build_identity(
    claims: dict[str, Any], userinfo: dict[str, Any], *, issuer: str
) -> OidcIdentity:
    """Combine the verified ID token claims with the userinfo body into an identity.

    Its own function rather than three lines inside ``complete`` because the one thing it
    decides matters: `email` picks the local account a first sign-in links to. A pure
    function is one a test can state that rule against directly, instead of reaching it
    through a stubbed token exchange.
    """
    # userinfo wins where it carries an address, the id_token fills in otherwise. Providers
    # that keep the id_token minimal send email only from userinfo, so preferring the token
    # would break them outright.
    email = userinfo.get("email") or claims.get("email")
    return OidcIdentity(
        subject=str(claims["sub"]),
        issuer=issuer,
        # Lower-cased because that is how addresses are stored and matched here
        # (`NormalisedEmail` in schemas/user.py does the same on the way in), so a provider
        # sending "Jo@Example.com" still finds jo@example.com.
        email=str(email).strip().lower() if email else None,
    )


async def _verify_id_token(
    id_token: str, *, nonce: str, metadata: dict[str, Any]
) -> dict[str, Any]:
    """Check the ID token's signature and claims, returning its payload.

    The signature is checked against the provider's published keys, so an attacker who
    can reach the callback still cannot forge an identity. A token the cached key set cannot
    verify triggers exactly one forced JWKS re-fetch, which is the key rotation path:
    without it every sign-in breaks the moment the provider rotates and stays broken for up
    to an hour, until the cache expires.

    The retry is on **any** verification failure, not only `InvalidKeyIdError`. That
    exception fires only when joserfc cannot select a key *by kid*, so it misses the two
    other shapes rotation takes: a provider that omits `kid` (nothing to mismatch, so the
    single stale key is tried and fails the signature), and one that rotates the key while
    keeping the `kid` (the id matches, the key does not). Both surface as
    `BadSignatureError`, and both are fixed by exactly the same re-fetch. Retrying costs one
    HTTP call on a token that was going to be refused anyway.
    """
    advertised = metadata.get("id_token_signing_alg_values_supported") or _DEFAULT_ALGORITHMS
    if not isinstance(advertised, list):
        # Provider-controlled data: a scalar here would make the comprehension raise.
        advertised = list(_DEFAULT_ALGORITHMS)
    algorithms = [alg for alg in advertised if alg in _ALLOWED_ALGORITHMS]
    if not algorithms:
        # A provider advertising nothing we accept is a misconfiguration, not a licence to
        # accept what it does advertise. Falling back to the default means the verification
        # below fails with a signature error rather than passing on a weak algorithm.
        logger.warning("OIDC provider advertises no acceptable id_token algorithm: %s", advertised)
        algorithms = list(_DEFAULT_ALGORITHMS)

    token = None
    for force in (False, True):
        key_set = await _key_set(metadata, force=force)
        try:
            token = jwt.decode(id_token, key_set, algorithms=algorithms)
            break
        except JoseError as exc:
            if force:
                raise OidcError(
                    f"id_token did not verify: {type(exc).__name__} "
                    f"({describe_token(id_token)}; provider keys: {describe_keys(key_set)}; "
                    f"algorithms tried: {', '.join(algorithms)})"
                ) from exc
    if token is None:  # pragma: no cover - the loop either breaks or raises
        raise OidcError("id_token did not verify")

    # A JWT payload only conventionally holds a JSON object: joserfc verifies the signature
    # over whatever bytes are inside and hands back `.claims` as a list, string, number or
    # None if that is what was signed. Every read below (`registry.validate`, `.get`, and
    # `claims["sub"]` in the caller) assumes a mapping, so without this a provider whose
    # signing pipeline emitted a non-object would 500 the callback instead of landing on the
    # "provider" refusal this module promises for everything.
    if not isinstance(token.claims, dict):
        raise OidcError("id_token payload is not a JSON object")

    registry = jwt.JWTClaimsRegistry(
        leeway=_CLAIMS_LEEWAY,
        # The provider's own spelling of its issuer, which is what it signs.
        iss={"essential": True, "values": [str(metadata["issuer"])]},
        sub={"essential": True},
        aud={"essential": True, "values": [settings.oidc_client_id]},
        exp={"essential": True},
        iat={"essential": True},
    )
    try:
        registry.validate(token.claims)
    except JoseError as exc:
        raise OidcError(f"id_token claims rejected: {type(exc).__name__}") from exc

    # Checked by hand because joserfc's registry has no nonce rule: it is an OIDC
    # claim, not a JWT one. It is also the check that makes replaying a captured
    # id_token into a *fresh* flow useless, so it is not optional.
    if token.claims.get("nonce") != nonce:
        raise OidcError("id_token nonce does not match the one this flow was started with")

    # OIDC Core 3.1.3.7 goes further than JWT's `aud` rule: a token naming several
    # audiences must also carry `azp` naming *this* client. The registry above is
    # satisfied by our client id appearing anywhere in the list, so without this a token
    # minted for another client that happens to list us as a second audience would pass.
    # No mainstream provider issues multi-audience ID tokens by default, which is exactly
    # why this would go unnoticed if one ever did.
    # Two rules, and the second is the one that catches a single-audience token: OIDC says a
    # multi-audience token MUST carry `azp` naming this client, and that `azp` SHOULD be
    # verified whenever it is present at all. Checking only the first would let a token minted
    # for another client through on the strength of naming us as its sole `aud` while its
    # `azp` says who it was really for.
    audience = token.claims.get("aud")
    azp = token.claims.get("azp")
    multi_audience = isinstance(audience, list) and len(audience) > 1
    if multi_audience and azp is None:
        raise OidcError("id_token names several audiences without an azp claim")
    if azp is not None and azp != settings.oidc_client_id:
        raise OidcError("id_token azp names a different client")

    return dict(token.claims)


async def _fetch_userinfo(
    client: AsyncOAuth2Client, metadata: dict[str, Any], subject: str
) -> dict[str, Any]:
    """The userinfo document, or an empty dict if it cannot be used.

    Best-effort on purpose: the ID token already carries a verified identity, so a
    provider without a reachable userinfo endpoint should still be able to sign people
    in. What is *not* best-effort is the subject check - OIDC requires the two to
    agree, and a userinfo response describing a different account than the token we
    just verified is the one case where ignoring the endpoint would be dangerous
    rather than merely lossy.
    """
    endpoint = metadata.get("userinfo_endpoint")
    if not endpoint:
        return {}
    try:
        response = await client.get(str(endpoint))
        response.raise_for_status()
        info = response.json()
    except Exception as exc:
        # Deliberately broad, and narrower would be wrong: besides httpx errors and bad JSON,
        # authlib's own OAuthError family fires here (it refreshes/validates the token before
        # sending it, so a provider answering `expires_in: 0` raises from inside `get`). None
        # of those is a reason to fail a sign-in whose id_token already verified, and every
        # one of them would otherwise escape `complete()` past the router's `except OidcError`
        # as a 500.
        logger.warning("OIDC userinfo fetch failed: %s: %s", type(exc).__name__, exc)
        return {}
    if not isinstance(info, dict):
        return {}
    # A missing `sub` is treated as unusable rather than as agreement. OIDC requires the
    # endpoint to return one, so its absence means this is not a userinfo response we can
    # tie to the token we just verified - and defaulting it to `subject` would have made the
    # check below pass on exactly the bodies it exists to reject.
    if "sub" not in info:
        logger.warning("OIDC userinfo response carries no sub; ignoring it")
        return {}
    if str(info["sub"]) != subject:
        raise OidcError("userinfo describes a different subject than the id_token")
    return info


async def complete(*, code: str, code_verifier: str, nonce: str) -> OidcIdentity:
    """Finish a flow: swap the callback's ``code`` for tokens, verify them, and report
    who signed in.

    The exchange is a direct server-to-server call authenticated with the client
    secret, so the ``code`` a browser hands us is worthless to anyone who cannot also
    present that secret and the matching PKCE verifier.
    """
    metadata = await discover()
    endpoint = metadata.get("token_endpoint")
    if not endpoint:
        raise OidcError("the provider's metadata has no token_endpoint")

    async with _client() as client:
        try:
            token = await client.fetch_token(
                str(endpoint),
                grant_type="authorization_code",
                code=code,
                code_verifier=code_verifier,
                redirect_uri=redirect_uri(),
            )
        except Exception as exc:
            # Deliberately broad: authlib raises its own OAuthError family for a
            # rejected code and httpx errors for a provider that is simply down, and
            # the caller's response to every one of them is identical. The type is
            # logged so an operator can still tell those apart.
            logger.warning("OIDC token exchange failed: %s: %s", type(exc).__name__, exc)
            raise OidcError(f"token exchange failed: {type(exc).__name__}") from exc

        id_token = token.get("id_token")
        if not id_token:
            raise OidcError("the provider returned no id_token")
        claims = await _verify_id_token(str(id_token), nonce=nonce, metadata=metadata)
        subject = str(claims["sub"])
        userinfo = await _fetch_userinfo(client, metadata, subject)

    return build_identity(claims, userinfo, issuer=str(metadata["issuer"]))
