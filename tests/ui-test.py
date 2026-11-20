"""Headless browser test of the UI: a full session on a phone (dark) and a desktop (light).

Usage: uv run --with playwright tests/ui-test.py [screenshot_dir]
First time only: uv run --with playwright playwright install --with-deps chromium
Starts its own server on a temp DB. Look at the screenshots; the JSON lists console errors and overflow.
"""
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.harness import test_server  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "tests/screenshots"
BASE = ""

MESSAGES = [
    "Sorry, the demo is not ready, we have problem with payment API.",
    "I think I need two more day, maybe Monday is ok?",
]


async def wait_reply(page, n_coach):
    await page.wait_for_function(
        f"document.querySelectorAll('.msg.coach').length >= {n_coach} && !document.querySelector('.typing')",
        timeout=60000,
    )


async def run(p, name, viewport, scheme, mobile):
    browser = await p.chromium.launch()
    ctx = await browser.new_context(viewport=viewport, color_scheme=scheme, is_mobile=mobile, has_touch=mobile,
                                    device_scale_factor=2 if mobile else 1)
    page = await ctx.new_page()
    problems = []
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)

    await page.goto(BASE + "/")
    await page.wait_for_selector("#scenario option", state="attached")
    await page.screenshot(path=f"{OUT}/{name}-1-start.png")

    attrs = await page.eval_on_selector("#input", "e => [e.spellcheck, e.getAttribute('autocorrect'), e.getAttribute('autocomplete')]")
    await page.select_option("#scenario", "upwork-delay")
    await page.click("#start")
    await wait_reply(page, 1)
    await page.check("#timerToggle")
    warm = await page.locator(".warm li").count()
    await page.screenshot(path=f"{OUT}/{name}-2-session.png")

    n = 1
    for m in MESSAGES:
        await page.fill("#input", m)
        await page.wait_for_timeout(1200)  # let the timer tick
        await page.press("#input", "Enter")
        n += 1
        await wait_reply(page, n)
    await page.click("#help")
    n += 1
    await wait_reply(page, n)
    await page.fill("#input", "Müşteriye nasıl söylerim bilmiyorum.")
    await page.click("#send")
    n += 1
    await wait_reply(page, n)
    timer_visible = await page.is_visible("#timer")
    await page.screenshot(path=f"{OUT}/{name}-3-chat.png", full_page=True)

    before = await page.locator(".msg").count()
    await page.reload()  # a reload or a laptop waking up must bring the session back
    await page.wait_for_selector("#composer:not(.hidden)")
    resumed = await page.locator(".msg").count() == before

    await page.click("#end")
    await page.wait_for_selector(".report", timeout=240000)
    await page.wait_for_timeout(800)
    await page.screenshot(path=f"{OUT}/{name}-4-report.png", full_page=True)

    overflow = await page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    coach = await page.locator(".msg.coach").all_inner_texts()
    start_visible = await page.is_visible("#start")
    report_text = await page.inner_text(".report")
    await browser.close()
    return {
        "name": name, "autocorrect_attrs": attrs, "warmup_items": warm, "timer_visible_after_reply": timer_visible, "resumed_after_reload": resumed,
        "horizontal_overflow_px": overflow, "start_button_back": start_visible,
        "coach_replies": coach, "report_excerpt": report_text[:600], "problems": problems,
    }


async def main():
    global BASE
    Path(OUT).mkdir(parents=True, exist_ok=True)
    with test_server(port=8798) as (base, _log):
        BASE = base
        async with async_playwright() as p:
            results = [
                await run(p, "mobile", {"width": 390, "height": 844}, "dark", True),
                await run(p, "desktop", {"width": 1280, "height": 800}, "light", False),
            ]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    bad = [r["name"] for r in results if r["problems"] or r["horizontal_overflow_px"] > 0 or not r["resumed_after_reload"]]
    print("FAIL: " + ", ".join(bad) if bad else "PASS")
    sys.exit(1 if bad else 0)


asyncio.run(main())
