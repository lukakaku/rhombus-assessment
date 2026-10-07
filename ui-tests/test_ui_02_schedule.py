"""UI-02: Read-only validation of the existing schedule on the baseline Luka pipeline.

Prerequisites:
- Chrome is running with local remote debugging on port 9222.
- The same Chrome profile is already authenticated to Rhombus.

Run from repository root:
  .\\.venv\\Scripts\\python.exe -m pytest ui-tests/test_ui_02_schedule.py -v -s
"""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import Error, expect, sync_playwright


RHOMBUS_URL = "https://rhombusai.com/workflow/5269"
PROJECT_NAME = "Luka"


def test_existing_schedule_is_visible_and_inactive():
    """UI-02: confirm the baseline pipeline has the expected saved schedule.

    This is intentionally read-only: it does not activate, edit, run, or delete
    the schedule.
    """
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(
                os.environ.get("RHOMBUS_CDP_URL", "http://127.0.0.1:9222"),
                timeout=10_000,
            )
        except Error as exc:
            pytest.fail(
                "Cannot connect to authenticated Chrome. "
                f"Underlying error: {exc}"
            )

        page = None
        try:
            context = browser.contexts[0]
            page = context.new_page()
            page.goto(RHOMBUS_URL, wait_until="domcontentloaded")

            expect(page).to_have_url(re.compile(r"/workflow/5269"), timeout=15_000)
            expect(
                page.get_by_role(
                    "link",
                    name=re.compile(rf"^{re.escape(PROJECT_NAME)}$")
                ).first
            ).to_be_visible(timeout=20_000)

            # Open the Schedule tab.
            schedule_tab = page.get_by_role("tab", name="Schedule")
            expect(schedule_tab).to_be_visible(timeout=20_000)
            schedule_tab.click()

            # Scope every assertion to the visible Schedule side panel so hidden
            # AI Builder/chat text elsewhere in the page cannot be matched.
            schedule_panel = page.get_by_role("complementary")
            expect(schedule_panel).to_be_visible(timeout=10_000)

            expect(schedule_panel).to_contain_text("Schedules")
            expect(
                schedule_panel.get_by_role(
                    "button",
                    name=re.compile(r"Add Schedule", re.I)
                )
            ).to_be_visible(timeout=10_000)

            # The schedule card is rendered as combined accessible text rather
            # than separate visible nodes for every label.
            expect(schedule_panel).to_contain_text("Schedule for Luka")
            expect(schedule_panel).to_contain_text("Inactive")
            expect(
                schedule_panel
            ).to_contain_text(re.compile(r"Custom:\s*\*/5\s+\*\s+\*\s+\*\s+\*"))

            # Semantic state assertion: the visible activation switch is off.
            activate_switch = schedule_panel.get_by_role(
                "switch", name="Activate schedule"
            )
            expect(activate_switch).to_be_visible(timeout=10_000)
            expect(activate_switch).not_to_be_checked()

        except Exception:
            if page:
                print(
                    f"\n[UI-02 diagnostics] "
                    f"url={page.url!r} title={page.title()!r}"
                )
                Path("test-results").mkdir(exist_ok=True)
                try:
                    page.screenshot(
                        path="test-results/UI-02-schedule-failure.png",
                        full_page=True,
                    )
                except Exception:
                    pass
            raise
        finally:
            if page:
                page.close()
            browser.close()
