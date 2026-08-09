"""The API reference asks nothing of anybody but this origin.

Two separate problems were closed by pointing `get_redoc_html` inward, and both are the sort
that come back quietly, because the page looks identical either way:

- **supply chain** - the bundle used to come from a floating `redoc@2` range on jsDelivr with
  no `integrity` attribute, executing same-origin with the SPA where it could call the API
  with the reader's cookie;
- **AVG / GDPR** - Montserrat and Roboto came from Google Fonts, so every signed-in reader's
  IP went to Google for typography alone.

So these assert the *property* - no outbound reference in any src or href - rather than the
specific URLs that used to be wrong. A future FastAPI adding a fourth external reference to that
template would slip past a test naming only jsdelivr and Google.

What is NOT tested here is the bundle actually being on disk: it is fetched into the image at
build time, and pytest runs on a bare runner in CI where /opt/redoc does not exist. The
Dockerfile's own sha256 check is the guard there - a mismatch or a failed download fails the
build - and the prod smoke test in the README covers the page end to end.
"""

import re

from httpx import AsyncClient

from app.api.v1.docs import BUNDLE_URL

# Anything that would leave this origin, in a `src` or `href`. Also catches
# protocol-relative `//cdn.example/x`, which a naive `https?://` check reads as a path.
#
# Attributes only, which covers every reference `get_redoc_html` emits today (two, both
# checked below by name) but would not see an `@import url(https://...)` inside the inline
# <style> block. Named rather than fixed because the template is FastAPI's, not ours: if it
# ever grows one, this is where to widen.
EXTERNAL = re.compile(r'(?:src|href)\s*=\s*["\'](?:[a-z]+:)?//', re.I)


async def test_the_reference_page_makes_no_third_party_request(client: AsyncClient) -> None:
    response = await client.get("/redoc")

    assert response.status_code == 200
    external = EXTERNAL.findall(response.text)
    assert not external, f"the reference page references something off-origin: {external}"


async def test_the_reference_page_loads_the_vendored_bundle(client: AsyncClient) -> None:
    """The positive half. Without it, the assertion above would pass just as happily on a
    page that referenced no script at all - which is what a mistyped `redoc_js_url` would
    produce, and it renders as a blank page rather than an error."""
    response = await client.get("/redoc")

    assert f'src="{BUNDLE_URL}"' in response.text
    assert BUNDLE_URL.startswith("/api/v1/"), "the bundle has to sit under the proxied prefix"


async def test_google_fonts_are_switched_off(client: AsyncClient) -> None:
    """Named explicitly as well as covered by the blanket check above, because this one is a
    parameter that defaults to True: `with_google_fonts=False` is an easy thing to lose in a
    refactor, and the page looks fine without the fonts, so nothing else would notice."""
    assert "fonts.googleapis.com" not in (await client.get("/redoc")).text


async def test_the_reference_page_is_not_published_under_the_api_prefix(
    client: AsyncClient,
) -> None:
    """A gate rule, not a routing preference.

    The prod nginx gates one exact location (`= /docs`, rewritten to this page) and proxies
    everything under `/api/` with no gate at all. Moving the page under the API prefix for
    tidiness would therefore publish the whole reference anonymously, straight past the
    auth_request - so the absence of a route there is load-bearing and asserted.
    """
    assert (await client.get("/api/v1/docs/redoc")).status_code == 404


async def test_the_reference_is_absent_from_the_schema(client: AsyncClient) -> None:
    """Neither route is an operation, and the asset one especially should not appear: it
    would be the only path in the document nothing can call meaningfully."""
    paths = (await client.get("/openapi.json")).json()["paths"]
    assert "/redoc" not in paths
    assert BUNDLE_URL not in paths
