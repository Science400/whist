"""
Capture screenshots of all WHIST page types (desktop + mobile).

Usage:
    uv run python scripts/screenshot.py

Requirements:
    - App running at http://localhost:8000
    - playwright installed: uv run playwright install chromium
"""

import asyncio
from pathlib import Path

import httpx
from playwright.async_api import async_playwright, Page

BASE = "http://localhost:8000"
SCREENSHOTS = Path(__file__).parent.parent / "screenshots"

VIEWPORT_DESKTOP = {"width": 1280, "height": 800}
VIEWPORT_MOBILE = {"width": 390, "height": 844}


async def fetch_ids() -> dict:
    """Query the live API to get real show/season/episode/person IDs."""
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        shows_resp = await client.get("/shows")
        shows_resp.raise_for_status()
        shows = shows_resp.json()

        active = [
            s for s in shows
            if s.get("user_status") in ("airing", "watching", "finished")
            and s.get("watched_count", 0) > 0
        ]
        if not active:
            raise RuntimeError("No active shows with watch history found")

        show = active[0]
        show_id = show["tmdb_id"]

        season_resp = await client.get(f"/shows/{show_id}/season-progress")
        season_resp.raise_for_status()
        seasons = season_resp.json()

        season_num = 1
        ep_num = 1
        for s in seasons:
            watched_eps = [e for e in s.get("episodes", []) if e.get("watched")]
            if watched_eps:
                season_num = s["season_number"]
                ep_num = watched_eps[0]["number"]
                break

        cast_resp = await client.get(f"/shows/{show_id}/cast")
        cast_resp.raise_for_status()
        cast = cast_resp.json()

        with_history = sorted(
            [m for m in cast if m.get("seen_in_count", 0) > 0],
            key=lambda m: m["seen_in_count"],
            reverse=True,
        )
        person_id = with_history[0]["person_tmdb_id"] if with_history else cast[0]["person_tmdb_id"]

    return {
        "show_id": show_id,
        "show_title": show["title"],
        "season_number": season_num,
        "episode_number": ep_num,
        "person_id": person_id,
    }


async def wait_for_content(page: Page, selector: str | None = None):
    try:
        await page.wait_for_selector(".loading", state="hidden", timeout=8000)
    except Exception:
        pass
    if selector:
        try:
            await page.wait_for_selector(selector, timeout=8000)
        except Exception:
            pass
    await page.wait_for_timeout(600)


async def shot(page: Page, url: str, filename: str, wait_sel: str | None = None):
    await page.goto(url, wait_until="networkidle")
    await wait_for_content(page, wait_sel)
    path = SCREENSHOTS / filename
    await page.screenshot(path=str(path), full_page=True)
    print(f"  {filename}")


async def capture_all(ids: dict):
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)

    sid = ids["show_id"]
    sn = ids["season_number"]
    en = ids["episode_number"]
    pid = ids["person_id"]

    pages = [
        ("/",                                          "schedule",  ".schedule-card, .empty-state"),
        ("/library",                                   "library",   ".poster-grid, .empty-state"),
        ("/add",                                       "add",       ".search-input"),
        (f"/show/{sid}",                               "show",      ".show-title"),
        (f"/show/{sid}/season/{sn}",                   "season",    ".episode-list"),
        (f"/show/{sid}/season/{sn}/episode/{en}",      "episode",   "h1"),
        (f"/person/{pid}",                             "person",    ".person-hero"),
        ("/settings",                                  "settings",  None),
    ]

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()

        ctx = await browser.new_context(viewport=VIEWPORT_DESKTOP, color_scheme="dark")
        pg = await ctx.new_page()
        print("Desktop:")
        for route, stem, sel in pages:
            await shot(pg, f"{BASE}{route}", f"desktop-{stem}.png", sel)
        await ctx.close()

        ctx = await browser.new_context(
            viewport=VIEWPORT_MOBILE,
            color_scheme="dark",
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            has_touch=True,
        )
        pg = await ctx.new_page()
        print("Mobile:")
        for route, stem, sel in pages:
            await shot(pg, f"{BASE}{route}", f"mobile-{stem}.png", sel)
        await ctx.close()

        await browser.close()


async def main():
    print("Fetching IDs from API...")
    ids = await fetch_ids()
    print(f"  Show: {ids['show_title']} (id={ids['show_id']})")
    print(f"  Season {ids['season_number']}, Episode {ids['episode_number']}")
    print(f"  Person id={ids['person_id']}")
    print()

    print("Capturing screenshots...")
    await capture_all(ids)
    print(f"\nSaved to: {SCREENSHOTS}/")


if __name__ == "__main__":
    asyncio.run(main())
