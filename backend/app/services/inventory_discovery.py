"""Discover inventory-related URLs from robots.txt and sitemap XML (direct HTTP only)."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import httpx

from app.services.scraper import _browser_headers

logger = logging.getLogger(__name__)

_SITEMAP_LINE_RE = re.compile(
    r"^\s*Sitemap:\s*(.+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_INVENTORY_PATH_HINTS = (
    "inventory",
    "new-inventory",
    "used-inventory",
    "pre-owned",
    "showroom",
    "models",
    "searchnew",
    "searchused",
    "vehicles",
    "cars-for-sale",
    "boats-for-sale",
    "boat",
    "boats",
    "marine",
    "motorcycle",
    "motorcycles",
    "powersports",
    "new-vehicles",
    "used-vehicles",
    "vdp",
    "vehicle-details",
    "detail",
)
_MAX_SITEMAPS = 4
_MAX_URLS_PER_SITEMAP = 400
_MAX_RETURN_URLS = 12


def _origin_from_url(site_url: str) -> str:
    p = urlparse(site_url)
    if not p.scheme or not p.netloc:
        p = urlparse("https://" + site_url.lstrip("/"))
    return f"{p.scheme}://{p.netloc}"


def _parse_robots_sitemap_urls(robots_body: str) -> list[str]:
    return [m.group(1).strip() for m in _SITEMAP_LINE_RE.finditer(robots_body)]


def _loc_urls_from_sitemap_xml(xml_text: str) -> list[str]:
    urls: list[str] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return urls
    # sitemap index: <sitemap><loc>
    for el in root.iter():
        tag = el.tag.split("}")[-1].lower()
        if tag == "loc" and el.text:
            t = el.text.strip()
            if t.startswith("http"):
                urls.append(t)
    return urls


def _is_inventory_like_url(url: str) -> bool:
    u = url.lower()
    if any(h in u for h in _INVENTORY_PATH_HINTS):
        return True
    # Dealer VDP paths often end with stock or id segments
    if re.search(r"/vehicle/|/inventory/|/vdp/|/detail/", u):
        return True
    return False


async def discover_sitemap_inventory_urls(site_url: str, timeout: httpx.Timeout) -> list[str]:
    """
    Fetch robots.txt, follow sitemap entries, collect loc URLs that look like inventory or VDP.
    """
    origin = _origin_from_url(site_url)
    robots_url = urljoin(origin + "/", "robots.txt")
    candidates: list[str] = []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            r = await client.get(robots_url, headers=_browser_headers())
            if r.status_code == 200 and r.text:
                sitemap_urls = _parse_robots_sitemap_urls(r.text)
            else:
                sitemap_urls = []
        except Exception as e:
            logger.debug("robots.txt fetch failed for %s: %s", robots_url, e)
            sitemap_urls = []

        if not sitemap_urls:
            # Common default
            sitemap_urls = [urljoin(origin + "/", "sitemap.xml")]

        seen: set[str] = set()
        for sm_url in sitemap_urls[:_MAX_SITEMAPS]:
            if sm_url in seen:
                continue
            seen.add(sm_url)
            try:
                sr = await client.get(sm_url, headers=_browser_headers())
                if sr.status_code != 200:
                    continue
                locs = _loc_urls_from_sitemap_xml(sr.text)
            except Exception as e:
                logger.debug("sitemap fetch failed for %s: %s", sm_url, e)
                continue

            # If this looks like a sitemap index (nested sitemaps), fetch a few child sitemaps
            child_sitemaps = [u for u in locs if "sitemap" in u.lower() and u.endswith(".xml")]
            page_locs = [u for u in locs if u not in child_sitemaps]

            for u in page_locs[:_MAX_URLS_PER_SITEMAP]:
                if _is_inventory_like_url(u) and u not in candidates:
                    candidates.append(u)

            for child in child_sitemaps[:2]:
                if child in seen:
                    continue
                seen.add(child)
                try:
                    cr = await client.get(child, headers=_browser_headers())
                    if cr.status_code != 200:
                        continue
                    for u in _loc_urls_from_sitemap_xml(cr.text)[:_MAX_URLS_PER_SITEMAP]:
                        if _is_inventory_like_url(u) and u not in candidates:
                            candidates.append(u)
                except Exception as e:
                    logger.debug("child sitemap failed %s: %s", child, e)

            if len(candidates) >= _MAX_RETURN_URLS:
                break

    return candidates[:_MAX_RETURN_URLS]
