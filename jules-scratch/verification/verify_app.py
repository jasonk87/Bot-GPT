import time
from playwright.sync_api import sync_playwright, Page, expect

def verify_app(page: Page):
    """
    This script verifies that a user can register and see the main app screen.
    """
    # 1. Navigate to the application.
    page.goto("http://localhost:5000")

    # 2. Register a new user.
    page.get_by_role("button", name="Register").first.click()
    page.locator("#register-form").get_by_label("Username").fill("testuser_jules")
    page.locator("#register-form").get_by_label("Password").fill("password123")
    page.locator("#register-form").get_by_role("button", name="Register").click()

    # Wait for the main app to be visible after registration.
    expect(page.locator("#main-app")).to_be_visible(timeout=10000)


    # 3. Take a screenshot of the main application view.
    page.screenshot(path="jules-scratch/verification/verification.png")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        verify_app(page)
        browser.close()

if __name__ == "__main__":
    main()
