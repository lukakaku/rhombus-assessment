"""UI-01: Read-only checks of the existing Luka-drift pipeline.

Based on Chrome DevTools Recorder export UI-01-pipeline-config.json.
The assessment's original S3 -> AI Builder -> GCS -> Schedule workflow
is NOT fully covered by this smoke test. This test checks only observable
existing configuration and controls; it does not create or run a pipeline.

Prerequisites: authenticated Chrome launched separately with a local CDP port:
  --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1
  --user-data-dir=<separate private Chrome profile folder>

Run from repository root:
  .\\.venv\\Scripts\\python.exe -m pytest ui-tests/test_ui_01_pipeline_config.py -v
"""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import Error, expect, sync_playwright

RHOMBUS_URL = "https://rhombusai.com/workflow/5289"
PROJECT_NAME = "Luka-drift"
GCS_SOURCE = "rhombus-gcs-luka-input-001"
GCS_DESTINATION = "rhombus-gcs-luka-001"

EDGE_LABEL = re.compile(r"^Edge from (.+?) to (.+)$")


def _end_nodes_from_edges(page):
    """Fallback: React Flow exposes each edge as a button named 'Edge from <source id> to <target id>'.
    The input node is the only source that is never a target; the output node the reverse."""
    edges = page.get_by_role("button", name=re.compile(r"^Edge from "))
    expect(edges.first).to_be_attached(timeout=20_000)  # edges render after the canvas; wait, don't assume
    labels = edges.evaluate_all("els => els.map(e => e.getAttribute('aria-label') || e.textContent)")
    pairs = [m.groups() for m in (EDGE_LABEL.match(l.strip()) for l in labels if l) if m]
    assert pairs, f"Edge buttons found but names did not parse: {labels[:3]}"
    sources, targets = {a for a, _ in pairs}, {b for _, b in pairs}
    inputs, outputs = sources - targets, targets - sources
    assert len(inputs) == 1 and len(outputs) == 1, (
        f"Expected one input and one output node, got inputs={inputs} outputs={outputs}")

    def node(node_id):
        return page.locator(
            f'[data-testid="rf__node-{node_id}"], .react-flow__node[data-id="{node_id}"]').first
    return node(inputs.pop()), node(outputs.pop())


def find_end_nodes(page):
    """Return (input_node, output_node) locators for the first and last node on the canvas.

    Primary strategy: React Flow nodes carry their visible label, so match 'Data Input' / 'Data Output'.
    Waits for the canvas to render first (nodes appear a moment after the page loads).
    The old data-testid selector matched nothing, so none is guessed here.
    """
    nodes = page.locator(".react-flow__node")
    try:
        expect(nodes.first).to_be_attached(timeout=20_000)
    except AssertionError:
        return _end_nodes_from_edges(page)
    input_node = nodes.filter(has_text=re.compile(r"^\s*Data Input")).first
    output_node = nodes.filter(has_text=re.compile(r"^\s*Data Output")).first
    return input_node, output_node


def fit_canvas(page):
    """Nodes outside the visible area may not be rendered; ask React Flow to fit them in view."""
    try:
        page.locator('.react-flow__controls-fitview, button[aria-label*="fit view" i]').first.click(timeout=2_000)
    except Error:
        pass

def test_existing_pipeline_read_only_config():
    """Check navigation, source-picker visibility, transform/output and schedule UI.

    A visible GCS item in the source picker alone does NOT prove the source
    is correctly attached or that data ingestion works. Schedule UI presence
    likewise does NOT prove an active schedule or successful scheduled runs.
    """
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(
                os.environ.get("RHOMBUS_CDP_URL", "http://127.0.0.1:9222"),
                timeout=10_000,
            )
        except Error as exc:
            pytest.fail(
                "Cannot connect to authenticated Chrome. Launch a separate, "
                "private Chrome profile with local remote debugging enabled "
                "and log in to Rhombus normally before running this test. "
                f"Underlying error: {exc}"
            )

        page = None
        try:
            # Attaches to the current Chrome profile/session; never automates Google login.
            context = browser.contexts[0]
            page = context.new_page()
            page.goto(RHOMBUS_URL, wait_until="domcontentloaded")
            try:
                page.set_viewport_size({"width": 1700, "height": 950})  # wide enough to render the whole graph
            except Error:
                pass
            expect(page).to_have_url(re.compile(r"/workflow/\d+"), timeout=15_000)
            expect(page.get_by_role("link", name=re.compile(rf"^{PROJECT_NAME}"))).to_be_visible(timeout=20_000)
            expect(page.get_by_role("tab", name=re.compile("Canvas"))).to_be_visible(timeout=20_000)
            fit_canvas(page)

            # Directly open the authenticated project workflow rather than
            # looking for a project card on Rhombus's marketing home page.
            # A visible input node below confirms the workflow actually loaded.

            # Step: inspect GCS input source picker. This is availability, not a
            # verified attachment or a successful S3 connection.

            input_node, output_node = find_end_nodes(page)
            expect(input_node).to_be_visible(timeout=20_000)
            input_node.click(force=True)

            sidebar = page.get_by_test_id("right-sidebar")
            expect(sidebar).to_be_visible(timeout=10_000)

            source_button = sidebar.get_by_role("button", name=re.compile("Third Party Sources", re.I)).first
            expect(source_button).to_be_visible(timeout=10_000)
            source_button.click()

            expect(page.get_by_text(GCS_SOURCE, exact=True).first).to_be_visible(timeout=10_000)
            try:
                page.get_by_role("button", name=re.compile("close", re.I)).last.click(timeout=3_000)
            except Error:
                page.keyboard.press("Escape")

            # Step: inspect AI Builder and Transform sections, and the existing
            # node. Visibility does not certify that a new AI-built pipeline ran.
            builder = page.get_by_text("AI Builder", exact=True).first
            expect(builder).to_be_visible()
            builder.click()
            transform = page.get_by_text("Transform", exact=True).first
            expect(transform).to_be_visible()
            transform.click()

            expect(output_node).to_be_visible(timeout=20_000)
            output_node.click(force=True)

            shown_as_text = sidebar.get_by_text(GCS_DESTINATION)
            shown_as_value = sidebar.locator(f'input[value="{GCS_DESTINATION}"]')
            expect(shown_as_text.or_(shown_as_value).first).to_be_visible(timeout=10_000)

            # Step: Schedule is a visible section. No schedule exists in this
            # project, so intentionally do not assert it is configured/running.
            schedule = page.get_by_text("Schedule", exact=True).first
            expect(schedule).to_be_visible()
            schedule.click()
        except Exception:
            # Evidence remains local and gitignored. Check image before sharing.
            if page:
                print(f"\n[UI-01 diagnostics] url={page.url!r} title={page.title()!r}")
                Path("test-results").mkdir(exist_ok=True)
                try:
                    page.screenshot(path="test-results/UI-01-failure.png", full_page=True)
                except Exception:
                    pass
            raise
        finally:
            if page:
                page.close()
            browser.close()  # Disconnect only; does not shut down the user's Chrome.
