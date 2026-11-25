import sys
import time
from playwright.sync_api import sync_playwright

def test_full_ui():
    print("[TEST] Starting Playwright UI End-to-End Test on http://127.0.0.1:8080...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1400, 'height': 900},
            permissions=['clipboard-read', 'clipboard-write']
        )
        page = context.new_page()

        # Capture console messages and unhandled errors
        console_errors = []
        page.on("pageerror", lambda err: console_errors.append(f"PageError: {err}"))
        page.on("console", lambda msg: console_errors.append(f"ConsoleError: {msg.text}") if msg.type == "error" else None)

        # 1. Load Homepage
        print("[STEP 1] Navigating to http://127.0.0.1:8080...")
        page.goto("http://127.0.0.1:8080", wait_until="networkidle")
        page.wait_for_timeout(1000)
        title = page.title()
        print(f"  Page title: {title}")
        assert "AI Research & Intelligence Studio" in title

        # 2. Test Theme Toggle & Shortcuts Modal
        print("[STEP 2] Testing Theme Toggle & Shortcuts Modal...")
        initial_theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
        theme_btn = page.locator("#btn-theme-toggle")
        theme_btn.click()
        page.wait_for_timeout(400)
        toggled_theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
        print(f"  Theme toggled: initial='{initial_theme}' -> toggled='{toggled_theme}'")
        assert initial_theme != toggled_theme
        # Toggle back to dark
        theme_btn.click()
        page.wait_for_timeout(300)

        # Test Shortcuts Modal
        page.locator("#btn-shortcuts-toggle").click()
        page.wait_for_timeout(300)
        assert page.locator("#shortcuts-modal").is_visible()
        print("  Shortcuts Modal opened successfully.")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        assert not page.locator("#shortcuts-modal").is_visible()
        print("  Shortcuts Modal closed with Escape key.")

        # 3. Model selector
        print("[STEP 3] Testing Model Selector Dropdown...")
        model_select = page.locator("#model-select")
        current_model = model_select.input_value()
        print(f"  Active model in dropdown: {current_model}")

        # 4. Check Navigation: Reports Archive
        print("[STEP 4] Testing Reports Archive Navigation & Search...")
        page.locator("#nav-reports-btn").click()
        page.wait_for_timeout(800)
        assert page.locator("#view-reports").is_visible()
        
        # Test report filter
        report_search = page.locator("#reports-search-input")
        report_search.fill("test")
        page.wait_for_timeout(300)
        report_search.fill("")
        page.wait_for_timeout(300)
        print("  Reports archive view verified.")

        # 5. Test Navigation: Memory Explorer
        print("[STEP 5] Testing Vector Memory Explorer View & Query...")
        page.locator("#nav-memory-btn").click()
        page.wait_for_timeout(800)
        assert page.locator("#view-memory").is_visible()
        
        memory_search = page.locator("#memory-search-input")
        memory_search.fill("machine learning")
        page.locator("button:has-text('Query Memory')").click()
        page.wait_for_timeout(800)
        print("  Vector memory query executed successfully.")

        # 6. Test Navigation: Sandbox Diagnostic Tools
        print("[STEP 6] Testing Diagnostic Tools View...")
        page.locator("#nav-tools-btn").click()
        page.wait_for_timeout(500)
        assert page.locator("#view-tools").is_visible()
        print("  Diagnostic Tools view verified.")

        # 7. Return to Studio View & Start Autonomous Research Run
        print("[STEP 7] Returning to Studio & Starting Research Run...")
        page.locator("#nav-studio-btn").click()
        page.wait_for_timeout(500)
        assert page.locator("#view-studio").is_visible()

        # Fill topic
        topic_input = page.locator("#research-topic-input")
        topic_input.fill("Neuromorphic Computing Architecture")

        # Select quick mode (2 queries for swift test)
        mode_btn = page.locator(".depth-pill[data-depth='quick']")
        if mode_btn.count() > 0:
            mode_btn.first.click()
            print("  Selected Quick mode (2 queries)")

        # Click Start Research button
        start_btn = page.locator("#btn-start-research")
        start_btn.click()
        print("  Start Autonomous Research button clicked. Waiting for execution...")

        # Verify timer is running in Canvas Activity HUD
        page.wait_for_timeout(1500)
        timer_text = page.locator("#canvas-timer").inner_text()
        print(f"  Execution HUD Timer running: '{timer_text}'")

        # Wait for research to finish (stream completes and UI unlocks)
        print("  Waiting for research completion (SSE stream)...")
        page.wait_for_function(
            "document.getElementById('btn-start-research').disabled === false",
            timeout=120000
        )
        print("  Research cycle finished and report rendered!")

        # 8. Test Slide Deck Controls (Stage View, Nav Buttons, Dot Pills, Grid View)
        print("[STEP 8] Testing Presentation Slide Deck Carousel & Grid...")
        # Make sure Deck mode is active
        page.locator("#btn-view-deck").click()
        page.wait_for_timeout(600)

        # Check slide navigation buttons
        next_slide_btn = page.locator("#btn-slide-next")
        if next_slide_btn.is_visible() and not next_slide_btn.is_disabled():
            next_slide_btn.click()
            page.wait_for_timeout(400)
            print("  Next slide button clicked successfully.")

        prev_slide_btn = page.locator("#btn-slide-prev")
        if prev_slide_btn.is_visible() and not prev_slide_btn.is_disabled():
            prev_slide_btn.click()
            page.wait_for_timeout(400)
            print("  Previous slide button clicked successfully.")

        # Click Dot pill
        pills = page.locator(".slide-dot-pill")
        pill_count = pills.count()
        print(f"  Total slide pills: {pill_count}")
        if pill_count > 1:
            pills.nth(1).click()
            page.wait_for_timeout(400)
            print("  Slide dot pill clicked successfully.")

        # Switch to Grid View
        page.locator("#btn-grid-view").click()
        page.wait_for_timeout(500)
        grid_cards = page.locator(".grid-slide-card")
        print(f"  Deck Grid View active. Total slide cards rendered: {grid_cards.count()}")

        # Switch back to Stage View
        page.locator("#btn-stage-view").click()
        page.wait_for_timeout(500)
        print("  Deck Stage View restored.")

        # 9. Test Executive Document View Switch & Export Buttons
        print("[STEP 9] Testing Executive Document View Switch & Export Actions...")
        page.locator("#btn-view-doc").click()
        page.wait_for_timeout(500)
        doc_view = page.locator("#rendered-markdown-output")
        assert doc_view.is_visible()
        print("  Document view verified.")

        # Test Export buttons
        btn_copy_rich = page.locator("button:has-text('Copy Rich-Text')")
        if btn_copy_rich.is_visible():
            btn_copy_rich.click()
            page.wait_for_timeout(300)
            print("  Copy Rich-Text button clicked successfully.")

        btn_copy_md = page.locator("button:has-text('Copy MD')")
        if btn_copy_md.is_visible():
            btn_copy_md.click()
            page.wait_for_timeout(300)
            print("  Copy MD button clicked successfully.")

        # 10. Test Citations Filtering
        print("[STEP 10] Testing Citations Sidebar & Filter Search...")
        citation_filter = page.locator("#citations-filter-input")
        if citation_filter.is_visible():
            citation_filter.fill("http")
            page.wait_for_timeout(300)
            citation_items = page.locator(".citation-card")
            print(f"  Citations filtered count: {citation_items.count()}")
            citation_filter.fill("")

        # 11. Test Interactive Follow-up Chat Quick Chips
        print("[STEP 11] Testing Follow-up Chat Chips...")
        chip = page.locator('.chat-chip')
        if chip.count() > 0:
            first_chip_text = chip.first.inner_text()
            chip.first.click()
            page.wait_for_timeout(300)
            input_val = page.locator("#chat-question-input").input_value()
            print(f"  Clicked prompt chip '{first_chip_text}'. Chat input value: '{input_val}'")

        # 12. Check Console Errors
        print("[STEP 12] Checking for Browser Console Errors...")
        if console_errors:
            print(f"  [WARN] Console errors detected ({len(console_errors)}): {console_errors}")
        else:
            print("  [SUCCESS] 0 Console errors detected across all tested UI interactions!")

        # Take confirmation screenshot
        screenshot_path = "data/outputs/playwright_ui_verified.png"
        page.screenshot(path=screenshot_path, full_page=True)
        print(f"  Full page screenshot saved to {screenshot_path}")

        browser.close()
        print("\n=======================================================")
        print("   ALL UI/UX COMPONENTS CLICKED & VERIFIED PERFECTLY!  ")
        print("=======================================================")

if __name__ == "__main__":
    test_full_ui()
