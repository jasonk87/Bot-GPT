import os
import pytest
from playwright.sync_api import Page, expect

def test_deletion_e2e(page: Page):
    """
    End-to-end test for deleting files and conversations.
    - Logs in
    - Creates a conversation
    - Uploads a file
    - Deletes the file
    - Deletes the conversation
    """
    # Go to the page and log in
    page.goto("http://localhost:5001")
    page.locator("#login-username").fill("testuser1")
    page.locator("#login-password").fill("password")
    page.locator('#login-form button[type="submit"]').click()
    expect(page.locator("#new-chat-btn")).to_be_visible()

    # Create a conversation by starting a new chat and sending a message
    page.locator("#new-chat-btn").click()
    page.locator("#chat-input").fill("This conversation will be deleted.")
    page.locator("#send-button").click()
    expect(page.locator(".bot-bubble")).to_be_visible(timeout=20000)
    conversation_id = page.locator(".conversation-item.active").get_attribute("data-id")
    assert conversation_id is not None

    # Upload a file
    page.locator("#upload-btn").click()
    expect(page.locator("#upload-modal")).to_be_visible()
    page.locator("#file-input").set_input_files("jules-scratch/verification/dummy_file.txt")
    page.locator("#confirm-upload-btn").click()
    expect(page.locator("#upload-modal")).to_be_hidden(timeout=10000)

    # Go to the files tab and verify the file exists
    page.locator("#files-tab-btn").click()
    file_item = page.locator(".file-item", has_text="dummy_file.txt")
    expect(file_item).to_be_visible(timeout=10000)

    # Delete the file
    file_item.hover()
    file_item.locator(".delete-btn").click()
    expect(page.locator("#delete-modal")).to_be_visible()
    page.locator("#confirm-delete-btn").click()
    expect(page.locator("#delete-modal")).to_be_hidden()
    expect(file_item).to_be_hidden()

    # Go back to the chats tab and delete the conversation
    page.locator("#chats-tab-btn").click()
    convo_item = page.locator(f".conversation-item[data-id='{conversation_id}']")
    convo_item.hover()
    convo_item.locator(".delete-btn").click()
    expect(page.locator("#delete-modal")).to_be_visible()
    page.locator("#confirm-delete-btn").click()
    expect(page.locator("#delete-modal")).to_be_hidden()
    expect(convo_item).to_be_hidden()
