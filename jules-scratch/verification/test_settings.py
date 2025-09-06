import os
import pytest
from playwright.sync_api import Page, expect

def test_settings_e2e(page: Page):
    """
    End-to-end test for user settings.
    - Logs in
    - Changes the default model and persona
    - Saves the settings
    - Verifies the settings are updated
    - Logs out and logs back in
    - Verifies the settings are loaded correctly
    """
    # Go to the page and log in
    page.goto("http://localhost:5001")
    page.locator("#login-username").fill("testuser1")
    page.locator("#login-password").fill("password")
    page.locator('#login-form button[type="submit"]').click()
    expect(page.locator("#new-chat-btn")).to_be_visible()

    # Open the settings modal
    page.locator("#settings-btn").click()
    expect(page.locator("#settings-modal")).to_be_visible()

    # Change the settings
    model_select = page.locator("#model-select")
    persona_select = page.locator("#persona-select")

    # Select the second model and persona (assuming there are at least two)
    model_select.select_option(index=1)
    persona_select.select_option(index=1)

    new_model = model_select.evaluate("el => el.value")
    new_persona = persona_select.evaluate("el => el.value")

    # Save the settings
    page.locator("#save-settings-btn").click()
    expect(page.locator("#settings-modal")).to_be_hidden()

    # Verify the model display has been updated
    expect(page.locator("#current-model-display")).to_have_text(new_model)

    # Log out
    page.locator("#logout-btn").click()
    expect(page.locator("#login-form")).to_be_visible()

    # Log back in
    page.locator("#login-username").fill("testuser1")
    page.locator("#login-password").fill("password")
    page.locator('#login-form button[type="submit"]').click()
    expect(page.locator("#new-chat-btn")).to_be_visible()

    # Verify the settings are loaded correctly
    page.locator("#settings-btn").click()
    expect(page.locator("#settings-modal")).to_be_visible()

    expect(page.locator("#model-select")).to_have_value(new_model)
    expect(page.locator("#persona-select")).to_have_value(new_persona)
