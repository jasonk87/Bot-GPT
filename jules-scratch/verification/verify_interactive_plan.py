import re
from playwright.sync_api import Page, expect

def test_interactive_plan(page: Page):
    page.goto("http://127.0.0.1:5000")

    # Register a new user
    page.get_by_role("button", name="Register").click()
    page.get_by_label("Username").click()
    page.get_by_label("Username").fill("testuser3")
    page.get_by_label("Password").click()
    page.get_by_label("Password").fill("password")
    page.get_by_role("button", name="Register").click()

    # Start a new chat
    page.get_by_role("button", name="New Chat").click()

    # Send a message that will trigger a plan
    page.get_by_placeholder("Type your message here...").click()
    page.get_by_placeholder("Type your message here...").fill("create a plan to write a file")
    page.get_by_role("button", name="Send").click()

    # Wait for the plan to appear and take a screenshot
    expect(page.locator("#plan-actions")).to_be_visible()
    page.screenshot(path="jules-scratch/verification/verification.png")
