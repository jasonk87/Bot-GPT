from playwright.sync_api import sync_playwright
import time
import os

# Define the path to the database
db_path = 'Bot-GPT/instance/users.db'

def run(playwright):
    # Ensure a clean slate by deleting the database if it exists
    if os.path.exists(db_path):
        os.remove(db_path)

    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={'width': 375, 'height': 667},
        is_mobile=True,
    )
    page = context.new_page()

    # Give the server time to start up
    time.sleep(5)

    # Navigate to the root, which contains the auth forms
    page.goto('http://127.0.0.1:5000/')

    # Click the 'Register' tab to show the registration form
    page.click('.auth-tab-btn[data-tab="register"]')

    # Fill out the registration form
    page.fill('#register-username', 'testuser')
    page.fill('#register-password', 'password')

    # Submit the registration form
    page.click('#register-form button[type="submit"]')

    # Wait for the main app to be visible after successful registration
    page.wait_for_selector('#main-app:not(.hidden)')

    # Now click the canvas button and take a screenshot
    page.click('#canvas-toggle-btn')
    page.screenshot(path='jules-scratch/verification/verification.png')

    browser.close()

with sync_playwright() as playwright:
    run(playwright)
