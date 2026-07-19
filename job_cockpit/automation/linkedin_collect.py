from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))

from agents import create_job  # noqa: E402
from storage import Store  # noqa: E402


PROFILE_DIR = ROOT / "browser_profiles" / "linkedin"


async def main_async(args: argparse.Namespace) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Playwright is not installed. Install optional dependencies first:")
        print("  python -m pip install -r job_cockpit/requirements-optional.txt")
        print("  python -m playwright install chromium")
        return 2

    store = Store(args.db)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1360, "height": 920},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        created = 0

        for query in args.query:
            for location in args.location:
                for page_index in range(args.pages):
                    url = linkedin_search_url(query, location, page_index * 25, args.remote)
                    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    if await needs_login_or_security(page):
                        print("LinkedIn needs login or a security check.")
                        print("Log in / solve the check in the visible browser, then press Enter here.")
                        await wait_for_enter()
                    await page.wait_for_timeout(2500)
                    await page.mouse.wheel(0, 1800)
                    await page.wait_for_timeout(1200)
                    jobs = await extract_jobs(page)
                    for job in jobs:
                        try:
                            create_job(
                                store,
                                {
                                    "source": "LinkedIn assisted search",
                                    "source_url": url,
                                    "title": job.get("title", ""),
                                    "company": job.get("company", ""),
                                    "location": job.get("location", location),
                                    "remote": "remote" if args.remote else "",
                                    "url": job.get("url", ""),
                                    "description": job.get("description", "") or job.get("title", ""),
                                },
                            )
                            created += 1
                        except Exception as exc:  # noqa: BLE001
                            store.log("warning", "LinkedIn job import skipped", {"error": str(exc), "url": job.get("url", "")})
                    print(f"{query} / {location} page {page_index + 1}: imported {len(jobs)} visible jobs")

        await context.close()
        print(f"LinkedIn assisted import finished. Imported attempts: {created}")
        return 0


def linkedin_search_url(query: str, location: str, start: int, remote: bool) -> str:
    params = {
        "keywords": query,
        "location": location,
        "start": str(start),
    }
    if remote:
        params["f_WT"] = "2"
    return "https://www.linkedin.com/jobs/search/?" + urlencode(params)


async def needs_login_or_security(page) -> bool:
    url = page.url.lower()
    if "login" in url or "checkpoint" in url:
        return True
    selectors = [
        'input[name="session_key"]',
        'input[name="session_password"]',
        'iframe[src*="captcha"]',
        '[id*="captcha" i]',
        '[class*="captcha" i]',
    ]
    for selector in selectors:
        try:
            if await page.locator(selector).count() > 0:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def extract_jobs(page) -> list[dict[str, str]]:
    return await page.evaluate(
        """
        () => {
          const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
          const anchors = Array.from(document.querySelectorAll('a[href*="/jobs/view/"]'));
          const seen = new Set();
          const jobs = [];
          for (const anchor of anchors) {
            const url = new URL(anchor.href, location.href);
            url.search = "";
            const cleanUrl = url.toString();
            if (seen.has(cleanUrl)) continue;
            seen.add(cleanUrl);
            const card = anchor.closest("li, .job-card-container, .jobs-search-results__list-item, div") || anchor;
            const title = normalize(anchor.innerText) || normalize(card.querySelector("[aria-label], strong")?.innerText);
            if (!title || title.length < 4) continue;
            const company =
              normalize(card.querySelector(".job-card-container__primary-description")?.innerText) ||
              normalize(card.querySelector(".base-search-card__subtitle")?.innerText) ||
              "";
            const locationText =
              normalize(card.querySelector(".job-card-container__metadata-item")?.innerText) ||
              normalize(card.querySelector(".job-search-card__location")?.innerText) ||
              "";
            const description = normalize(card.innerText).slice(0, 1200);
            jobs.push({title, company, location: locationText, url: cleanUrl, description});
          }
          return jobs.slice(0, 40);
        }
        """
    )


async def wait_for_enter() -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, input)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect visible LinkedIn job cards using a local logged-in browser session.")
    parser.add_argument("--db", default=str(ROOT / "cockpit.db"))
    parser.add_argument("--query", action="append", default=["data analyst", "data scientist", "product analyst"])
    parser.add_argument("--location", action="append", default=["Remote", "Europe", "Germany"])
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--remote", action="store_true", default=True)
    return parser


def main() -> None:
    raise SystemExit(asyncio.run(main_async(build_parser().parse_args())))


if __name__ == "__main__":
    main()
