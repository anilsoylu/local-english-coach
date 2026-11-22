"""Headless browser test of the UI: a full session on a phone (dark) and a desktop (light), then the report screen,
the home screen's past sessions, "Generate report", and the lifecycle edge cases from docs/state-machines.md.

Each run gets its own server and temp DB, so both start at the native language onboarding. The phone picks
Türkçe on screen; the desktop sets it through the API and reloads, so the server profile alone drives the UI.

Usage: uv run --with playwright tests/ui-test.py [screenshot_dir]
First time only: uv run --with playwright playwright install --with-deps chromium
Starts its own server on a temp DB. Look at the screenshots; the JSON lists console errors and overflow.
"""
import asyncio
import json
import re
import sys
import time
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
SESSION_GET = re.compile(r"/api/session/\d+$")  # the stored session, fetched on load


async def wait_reply(page, n_coach):
    """n coach messages on screen and none still streaming."""
    await page.wait_for_function(
        f"document.querySelectorAll('{COACH}').length >= {n_coach} && !document.querySelector('[aria-busy=true]')",
        timeout=60000,
    )


async def send(page, text):
    await page.fill(TEXTAREA, text)
    await page.press(TEXTAREA, "Enter")


async def report_ready(page, timeout=240000):
    """The report card is settled: ready, missing or timed out, no longer waiting."""
    await page.wait_for_function(
        "document.querySelector('[data-testid=report]') && !document.querySelector('[data-testid=waiting]')",
        timeout=timeout,
    )


async def end_session(page):
    await page.click('[data-testid="end"]')
    await page.click('[data-testid="end"]')  # the first tap only arms the button; the second confirms


async def stored_sid(page):
    return await page.evaluate("localStorage.getItem('sid')")


async def run(p, base, name, viewport, scheme, mobile):
    browser = await p.chromium.launch()
    ctx = await browser.new_context(viewport=viewport, color_scheme=scheme, is_mobile=mobile, has_touch=mobile,
                                    device_scale_factor=2 if mobile else 1)
    page = await ctx.new_page()
    problems = []
    # While `failing` is set, the test makes requests fail on purpose: their HTTP errors and the browser's console
    # line about them are expected. Anything else is a problem.
    failing = {"on": False}

    def note(problem):
        if not failing["on"]:
            problems.append(problem)

    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("console", lambda m: note(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("response", lambda r: note(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)
    api = httpx.Client(base_url=base, timeout=60)

    await page.goto(base + "/")
    await page.wait_for_selector('[data-language="tr"]')  # first visit: pick the native language
    await page.wait_for_timeout(500)
    await page.screenshot(path=f"{OUT}/{name}-0-language.png")
    if mobile:
        await page.click('[data-language="tr"]')
    else:
        api.put("/api/profile", json={"native_language": "tr"}).raise_for_status()
        await page.reload()
    await page.wait_for_selector("[data-scenario]")
    turkish_ui = await page.is_visible("text=Bugün ne konuşalım?")
    html_lang = await page.get_attribute("html", "lang")
    # The header button opens the same list, with the current language marked; Back (or the app name) returns.
    await page.click('[data-testid="language"]')
    current_marked = await page.is_visible('[data-language="tr"][aria-current="true"]')
    await page.click('[data-testid="app-home"]')
    await page.wait_for_selector("[data-scenario]")
    await page.wait_for_timeout(500)  # let the cards finish their entrance
    await page.screenshot(path=f"{OUT}/{name}-1-start.png")

    await page.click('[data-scenario="upwork-delay"]')
    await page.wait_for_selector(TEXTAREA)
    await wait_reply(page, 1)
    attrs = await page.eval_on_selector(TEXTAREA, "e => [e.spellcheck, e.getAttribute('autocorrect'), e.getAttribute('autocomplete'), getComputedStyle(e).fontSize]")
    warm = await page.locator('section[aria-label="Bugün kullanmayı dene"] li').count()
    no_home_link_in_chat = await page.locator('[data-testid="app-home"]').count() == 0
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
    sid = await stored_sid(page)

    # Server unreachable on reload: home for now, but the session is kept and comes back once the server answers.
    before = await page.locator('[data-slot="message"]').count()
    failing["on"] = True
    await page.route(SESSION_GET, lambda route: route.abort())
    await page.reload()
    await page.wait_for_selector("[data-scenario]")
    await page.wait_for_timeout(500)
    sid_kept_offline = await stored_sid(page) == sid
    await page.unroute(SESSION_GET)
    failing["on"] = False
    await page.reload()  # a reload or a laptop waking up must bring the session back
    await page.wait_for_selector(TEXTAREA)
    await page.wait_for_timeout(500)
    resumed = await page.locator('[data-slot="message"]').count() == before

    # A failed End stays in the chat with an error instead of waiting for a report that never comes.
    failing["on"] = True
    await page.route("**/end", lambda route: route.fulfill(status=500))
    await end_session(page)
    await page.wait_for_function(f"document.querySelectorAll('[data-slot=\"message\"]').length === {before + 1}")
    end_failure_stays_in_chat = await page.is_visible(TEXTAREA)
    await page.unroute("**/end")
    failing["on"] = False

    # The stats come from code, so they show at once; the model's part follows under a running seconds counter.
    t0 = time.perf_counter()
    await end_session(page)
    await page.wait_for_selector('[data-testid="stats"]', timeout=10000)
    stats_after_s = round(time.perf_counter() - t0, 2)
    stats_while_waiting = await page.is_visible('[data-testid="waiting"]')
    await page.screenshot(path=f"{OUT}/{name}-4-waiting.png")
    elapsed_before = await page.inner_text('[data-testid="elapsed"]')
    await page.wait_for_timeout(2100)
    elapsed_counts = await page.is_visible('[data-testid="waiting"]') \
        and await page.inner_text('[data-testid="elapsed"]') != elapsed_before
    await report_ready(page)
    await page.wait_for_timeout(800)
    await page.screenshot(path=f"{OUT}/{name}-4-report.png")
    report_screen = not await page.is_visible(TEXTAREA) and await page.is_visible('[data-testid="home"]') \
        and await page.is_visible('[data-testid="new"]')
    conversation_collapsed = await page.get_attribute('[data-testid="show-conversation"]', "aria-expanded") == "false"
    await page.click('[data-testid="show-conversation"]')
    await page.wait_for_timeout(600)
    await page.screenshot(path=f"{OUT}/{name}-5-report-conversation.png")
    overflow = await page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    coach = await page.locator(COACH).all_inner_texts()
    report_text = await page.inner_text('[data-testid="report"]')
    await page.reload()  # the ended session's report comes back after a reload
    await report_ready(page, timeout=30000)
    report_after_reload = await page.is_visible('[data-testid="new"]') and not await page.is_visible(TEXTAREA)

    # Home lists the session; opening it shows the same report with its conversation.
    await page.click('[data-testid="home"]')
    row = f'[data-session="{sid}"] button'
    await page.wait_for_selector(row)
    await page.locator('[data-testid="history"]').scroll_into_view_if_needed()
    await page.wait_for_timeout(500)
    await page.screenshot(path=f"{OUT}/{name}-6-home.png")
    sid_cleared_on_home = await stored_sid(page) is None
    await page.click(row)
    await report_ready(page, timeout=30000)
    await page.click('[data-testid="show-conversation"]')
    # The whole stored conversation, without the "could not end" notice the live chat showed.
    coach_turns = sum(t["role"] == "assistant" for t in api.get(f"/api/session/{sid}").json()["turns"])
    past_report_opens = await page.inner_text('[data-testid="report"]') == report_text \
        and await page.locator(COACH).count() == coach_turns

    # New session starts the same scenario right away; the app name is not a link in the chat.
    await page.click('[data-testid="new"]')
    await page.wait_for_selector(TEXTAREA)
    await wait_reply(page, 1)
    title = next(s["title"] for s in api.get("/api/scenarios").json() if s["id"] == "upwork-delay")
    new_session_same_scenario = await page.locator(COACH).count() == 1 and title in await page.inner_text("header")

    # A tap during the first load wins: the stored session that arrives afterwards doesn't replace the new chat.
    await page.evaluate(f"localStorage.setItem('sid', '{sid}')")

    async def slow(route):
        await asyncio.sleep(2)
        await route.continue_()

    await page.route(SESSION_GET, slow)
    await page.reload()
    await page.click('[data-scenario="smalltalk"]')
    await page.wait_for_selector(TEXTAREA)
    await page.wait_for_timeout(2500)
    tap_during_load_wins = await page.is_visible(TEXTAREA) and await page.locator(COACH).count() == 1 \
        and await stored_sid(page) != sid
    await page.unroute(SESSION_GET)

    # A message to a session the server already ended goes to its report instead of "Connection error".
    api.post(f"/api/session/{await stored_sid(page)}/end").raise_for_status()
    failing["on"] = True  # the 409
    await send(page, "Hello there.")
    await report_ready(page, timeout=30000)
    failing["on"] = False
    stale_send_goes_to_report = not await page.is_visible(TEXTAREA)

    # A session left without a report gets "Generate report" on the home screen.
    abandoned = api.post("/api/session", json={"scenario": "smalltalk"}).json()["session_id"]
    api.post(f"/api/session/{abandoned}/message", json={"text": "I go to beach yesterday."}).read()
    await page.click('[data-testid="app-home"]')
    await page.click(f'[data-session="{abandoned}"] [data-testid="generate"]')
    await report_ready(page, timeout=60000)
    generated = api.get(f"/api/session/{abandoned}/report").json()["ready"]

    if not mobile:  # CJK and Cyrillic rendering of the scenario screen
        await page.click('[data-testid="home"]')  # otherwise a reload shows the report again
        for lang in ("ja", "ru"):
            api.put("/api/profile", json={"native_language": lang}).raise_for_status()
            await page.reload()
            await page.wait_for_selector("[data-scenario]")
            await page.wait_for_timeout(500)
            await page.screenshot(path=f"{OUT}/{name}-7-start-{lang}.png")
    await browser.close()
    return {
        "name": name, "turkish_ui": turkish_ui, "html_lang": html_lang, "current_language_marked": current_marked,
        "textarea_attrs": attrs, "warmup_items": warm, "no_home_link_in_chat": no_home_link_in_chat,
        "sid_kept_offline": sid_kept_offline, "resumed_after_reload": resumed,
        "end_failure_stays_in_chat": end_failure_stays_in_chat, "stats_while_waiting": stats_while_waiting,
        "stats_after_s": stats_after_s, "elapsed_counts": elapsed_counts, "report_screen": report_screen,
        "conversation_collapsed": conversation_collapsed, "horizontal_overflow_px": overflow,
        "report_after_reload": report_after_reload, "sid_cleared_on_home": sid_cleared_on_home,
        "past_report_opens": past_report_opens, "new_session_same_scenario": new_session_same_scenario,
        "tap_during_load_wins": tap_during_load_wins, "stale_send_goes_to_report": stale_send_goes_to_report,
        "generate_report": generated, "coach_replies": coach, "report_excerpt": report_text[:600],
        "problems": problems,
    }


CHECKS = ["turkish_ui", "current_language_marked", "warmup_items", "no_home_link_in_chat", "sid_kept_offline",
          "resumed_after_reload", "end_failure_stays_in_chat", "stats_while_waiting", "elapsed_counts", "report_screen",
          "conversation_collapsed",
          "report_after_reload", "sid_cleared_on_home", "past_report_opens", "new_session_same_scenario",
          "tap_during_load_wins", "stale_send_goes_to_report", "generate_report"]


async def main():
    Path(OUT).mkdir(parents=True, exist_ok=True)
    results = []
    async with async_playwright() as p:
        for port, args in [(8798, ("mobile", {"width": 390, "height": 844}, "dark", True)),
                           (8797, ("desktop", {"width": 1280, "height": 800}, "light", False))]:
            with test_server(port=port) as (base, _log):
                results.append(await run(p, base, *args))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    bad = [r["name"] for r in results if r["problems"] or r["horizontal_overflow_px"] > 0 or r["html_lang"] != "tr"
           or r["textarea_attrs"] != [False, "off", "off", "16px"] or not all(r[k] for k in CHECKS)]
    print("FAIL: " + ", ".join(bad) if bad else "PASS")
    sys.exit(1 if bad else 0)


asyncio.run(main())
