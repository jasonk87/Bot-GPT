import pytest
from playwright.sync_api import Page, expect

def test_streaming_and_copy_button(page: Page, test_user, live_server):
    """
    Tests that the chat streams correctly and the copy button appears on code blocks.
    """
    # Navigate to the live server URL
    page.goto(live_server.url())

    # Wait for the login form to be visible
    expect(page.locator("#login-form")).to_be_visible()

    # Log in using more specific selectors
    page.locator("#login-form").get_by_label("Username").fill("testuser")
    page.locator("#login-form").get_by_label("Password").fill("password")
    page.locator("#login-form").get_by_role("button", name="Sign In").click()

    # Wait for the main app to be visible
    expect(page.locator("#main-app")).to_be_visible()

    # Send a message
    chat_input = page.locator("#chat-input")
    send_button = page.locator("#send-button")
    chat_input.fill("Hello, please show me some code.")
    send_button.click()

    # Wait for the streaming to complete.
    # We'll look for the final part of the simulated response.
    expect(page.get_by_text("This is the end of the test.")).to_be_visible(timeout=10000)

    # Check that the copy button is now visible inside the code block
    copy_button = page.locator("button.copy-btn")
    expect(copy_button).to_be_visible()

    # Take a screenshot to visually confirm
    page.screenshot(path="streaming_test.png")
