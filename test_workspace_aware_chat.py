import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("http://localhost:5000")

        # Register
        await page.click(".auth-tab-btn[data-tab='register']")
        await page.fill("#register-username", "testuser")
        await page.fill("#register-password", "testpassword")
        await page.click("#register-form button[type='submit']")
        await page.wait_for_selector("#new-chat-btn")

        # Create a new conversation
        await page.click("#new-chat-btn")
        await page.wait_for_selector("#chat-input")

        # Create a new file with specific content
        await page.fill("#chat-input", "create a new file named 'test.txt' with the content 'The secret word is banana.'")
        await page.click("#send-button")
        await page.wait_for_selector(".file-item")

        # Ask a question that can only be answered with knowledge of the file's content
        await page.fill("#chat-input", "What is the secret word?")
        await page.click("#send-button")
        await page.wait_for_selector(".bot-bubble:has-text('banana')")

        # Take a screenshot
        await page.screenshot(path="workspace-aware-chat.png")

        await browser.close()

asyncio.run(main())
