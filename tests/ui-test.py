"""Headless browser test of the UI: a full session on a phone (dark) and a desktop (light).

Each run gets its own server and temp DB, so both start at the native language onboarding. The phone picks
Türkçe on screen; the desktop sets it through the API and reloads, so the server profile alone drives the UI.

Usage: uv run --with playwright tests/ui-test.py [screenshot_dir]
First time only: uv run --with playwright playwright install --with-deps chromium
Starts its own server on a temp DB. Look at the screenshots; the JSON lists console errors and overflow.
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.harness import test_server  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "tests/screenshots"

MESSAGES = [
    "Sorry, the demo is not ready, we have problem with payment API.",
    "I think I need two more day, maybe Monday is ok?",
]


COACH = '[data-slot="message"][data-from="assistant"]'
TEXTAREA = "footer textarea"


async def wait_reply(page, n_coach):
    """n coach messages on screen and none still streaming."""
    await page.wait_for_function(
        f"document.querySelectorAll('{COACH}').length >= {n_coach} && !document.querySelector('[aria-busy=true]')",
        timeout=60000,
    )


async def send(page, text):
    await page.fill(TEXTAREA, text)
    await page.press(TEXTAREA, "Enter")


async def run(p, base, name, viewport, scheme, mobile):
    browser = await p.chromium.launch()
    ctx = await browser.new_context(viewport=viewport, color_scheme=scheme, is_mobile=mobile, has_touch=mobile,
                                    device_scale_factor=2 if mobile else 1)
    page = await ctx.new_page()
    problems = []
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)

    await page.goto(base + "/")
    await page.wait_for_selector('[data-language="tr"]')  # first visit: pick the native language
    await page.wait_for_timeout(500)
    await page.screenshot(path=f"{OUT}/{name}-0-language.png")
    if mobile:
        await page.click('[data-language="tr"]')
    else:
        httpx.put(f"{base}/api/profile", json={"native_language": "tr"}, timeout=10).raise_for_status()
        await page.reload()
    await page.wait_for_selector("[data-scenario]")
    turkish_ui = await page.is_visible("text=Bugün ne konuşalım?")
    html_lang = await page.get_attribute("html", "lang")
    # The header button opens the same list, with the current language marked; Back returns.
    await page.click('[data-testid="language"]')
    current_marked = await page.is_visible('[data-language="tr"][aria-current="true"]')
    await page.click("header button")
    await page.wait_for_selector("[data-scenario]")
    await page.wait_for_timeout(500)  # let the cards finish their entrance
    await page.screenshot(path=f"{OUT}/{name}-1-start.png")

    await page.click('[data-scenario="upwork-delay"]')
    await page.wait_for_selector(TEXTAREA)
    await wait_reply(page, 1)
    attrs = await page.eval_on_selector(TEXTAREA, "e => [e.spellcheck, e.getAttribute('autocorrect'), e.getAttribute('autocomplete'), getComputedStyle(e).fontSize]")
    warm = await page.locator('section[aria-label="Bugün kullanmayı dene"] li').count()
    await page.screenshot(path=f"{OUT}/{name}-2-session.png")

    n = 1
    for m in MESSAGES:
        await send(page, m)
        n += 1
        await wait_reply(page, n)
    await page.click('[data-testid="help"]')
    n += 1
    await wait_reply(page, n)
    await send(page, "Müşteriye nasıl söylerim bilmiyorum.")
    n += 1
    await wait_reply(page, n)
    await page.wait_for_timeout(500)  # the send button swaps its icon with a short animation
    await page.screenshot(path=f"{OUT}/{name}-3-chat.png")

    before = await page.locator('[data-slot="message"]').count()
    await page.reload()  # a reload or a laptop waking up must bring the session back
    await page.wait_for_selector(TEXTAREA)
    await page.wait_for_timeout(500)
    resumed = await page.locator('[data-slot="message"]').count() == before

    await page.click('[data-testid="end"]')
    await page.click('[data-testid="end"]')  # the first tap only arms the button; the second confirms
    await page.wait_for_selector('[data-testid="report"] h3, [data-testid="report"] .tabular-nums', timeout=240000)
    await page.wait_for_timeout(800)
    await page.screenshot(path=f"{OUT}/{name}-4-report.png")

    overflow = await page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    coach = await page.locator(COACH).all_inner_texts()
    new_visible = await page.is_visible('[data-testid="new"]')
    report_text = await page.inner_text('[data-testid="report"]')
    if not mobile:  # CJK and Cyrillic rendering of the scenario screen
        await page.click('[data-testid="new"]')  # otherwise a reload shows the ended session's report again
        for lang in ("ja", "ru"):
            httpx.put(f"{base}/api/profile", json={"native_language": lang}, timeout=10).raise_for_status()
            await page.reload()
            await page.wait_for_selector("[data-scenario]")
            await page.wait_for_timeout(500)
            await page.screenshot(path=f"{OUT}/{name}-5-start-{lang}.png")
    await browser.close()
    return {
        "name": name, "turkish_ui": turkish_ui, "html_lang": html_lang, "current_language_marked": current_marked,
        "textarea_attrs": attrs, "warmup_items": warm, "resumed_after_reload": resumed,
        "horizontal_overflow_px": overflow, "new_session_button": new_visible,
        "coach_replies": coach, "report_excerpt": report_text[:600], "problems": problems,
    }


async def main():
    Path(OUT).mkdir(parents=True, exist_ok=True)
    results = []
    async with async_playwright() as p:
        for port, args in [(8798, ("mobile", {"width": 390, "height": 844}, "dark", True)),
                           (8797, ("desktop", {"width": 1280, "height": 800}, "light", False))]:
            with test_server(port=port) as (base, _log):
                results.append(await run(p, base, *args))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    bad = [r["name"] for r in results if r["problems"] or r["horizontal_overflow_px"] > 0 or not r["resumed_after_reload"]
           or not r["turkish_ui"] or r["html_lang"] != "tr" or not r["current_language_marked"]]
    print("FAIL: " + ", ".join(bad) if bad else "PASS")
    sys.exit(1 if bad else 0)


asyncio.run(main())
