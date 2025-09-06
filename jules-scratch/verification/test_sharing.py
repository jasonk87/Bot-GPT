import os
import pytest
from playwright.sync_api import Page, expect

def test_sharing_e2e(page: Page):
    """
    End-to-end test for sharing a conversation.
    - Logs in as user1
    - Creates a conversation
    - Shares the conversation with user2
    - Logs in as user2
    - Verifies that the shared conversation is visible
    """
    # Go to the page and log in as testuser1
    page.goto("http://localhost:5001")
    page.locator("#login-username").fill("testuser1")
    page.locator("#login-password").fill("password")
    page.locator('#login-form button[type="submit"]').click()
    expect(page.locator("#new-chat-btn")).to_be_visible()

    # Start a new chat to create a conversation
    page.locator("#new-chat-btn").click()
    # Send a message to ensure the conversation is saved
    page.locator("#chat-input").fill("Hello, this is a test conversation.")
    page.locator("#send-button").click()
    # Wait for the bot's response to ensure the conversation is fully established
    expect(page.locator(".bot-bubble")).to_be_visible(timeout=20000)

    # Get the conversation ID from the active conversation item
    conversation_id = page.locator(".conversation-item.active").get_attribute("data-id")
    assert conversation_id is not None

    # Click the share button on the active conversation
    page.locator(".conversation-item.active .share-btn").click()
    expect(page.locator("#share-modal")).to_be_visible()

    # Find and click the user to share with
    page.locator("#share-user-list div", has_text="testuser2").click()
    # The modal should close automatically after sharing
    expect(page.locator("#share-modal")).to_be_hidden(timeout=10000)

    # Log out
    page.locator("#logout-btn").click()
    expect(page.locator("#login-form")).to_be_visible()

    # Log in as testuser2
    page.locator("#login-username").fill("testuser2")
    page.locator("#login-password").fill("password")
    page.locator('#login-form button[type="submit"]').click()
    expect(page.locator("#new-chat-btn")).to_be_visible()

    # Verify that the shared conversation is visible
    shared_conversation = page.locator(f".conversation-item[data-id='{conversation_id}']")
    expect(shared_conversation).to_be_visible()
