import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from my_agent.config import load_project_config, resolve_project_path

PROJECT_CONFIG = load_project_config()
output_file = resolve_project_path(PROJECT_CONFIG["paths"]["raw_results"])
url = PROJECT_CONFIG["urls"]["sportstats_leaderboard"]
apply_truncate_file = PROJECT_CONFIG["scraper"]["apply_truncate_file"]
num_skipped_pages = PROJECT_CONFIG["scraper"]["num_skipped_pages"]

# Functions

def truncate_file(output_file = output_file):
    Path(output_file).write_text("", encoding="utf-8")

def next_page(page, page_num, continue_loop, logging = True):
            
    # --- PAGINATION LOGIC ---
    # Strategy A: Target the generic button containing the right-chevron SVG path
    next_button = page.locator("button:has(svg path[d='M192 128l128 128-128 128z'])").first

    # Strategy B (Fallback): If Strategy A fails, try targeting any button wrapped directly around that SVG vector
    if not next_button.is_visible():
        next_button = page.locator("svg path[d='M192 128l128 128-128 128z']").first

    # Validate if the element was successfully detected
    if not next_button.is_visible():
        if logging:
            print("Pagination button could not be located. Reached the end of the leaderboard.")

    # Check if the next button is disabled via common JS attributes/classes
    is_disabled = next_button.evaluate("""el => {
        // Check closest button wrapper or the node itself
        const btn = el.tagName === 'BUTTON' ? el : el.closest('button');
        if (!btn) return false;
        return btn.disabled || 
            btn.getAttribute('aria-disabled') === 'true' || 
            btn.classList.contains('disabled');
    }""")

    if is_disabled:
        if logging:
            print("The 'Next' arrow is grayed out/disabled. Scraping complete!")
        continue_loop = False

    if logging:
        print("Clicking 'Next Page' arrow...")
    # Using force=True overrides situations where the SVG path blocks the click on the button container
    next_button.click(force=True)

    # Important: Allow the async API payload to load new table items safely
    page.wait_for_timeout(6000)
    page_num += 1

    return (page, page_num, continue_loop)

def skip_pages(page, page_num, continue_loop, num_skipped_pages):

    print(f"Commencing page skipping at page_num {page_num}. Once complete, processing will continue at page {page_num + num_skipped_pages}")

    for i in range(num_skipped_pages):
        page, page_num, continue_loop = next_page(page, page_num, continue_loop, logging = False)
        
        if not continue_loop:
            raise IndexError(f"no additional pages found at page {page_num}")
    
    print(f"skipped to page {page_num}")
        
    return page, page_num, continue_loop

def scrape_sportstats(starting_page = 1, url = url, output_file = output_file):
    
    with sync_playwright() as p:
        # Launch browser. Set headless=False if you want to visually watch it scrape.
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        print("Loading initial page...")
        page.goto(url, wait_until="networkidle")
        
        # Wait a moment for any delayed client-side hydration or table loaders
        page.wait_for_timeout(3000)
        
        page_num = 1
        continue_loop = True

        page, page_num, continue_loop = skip_pages(page, page_num, continue_loop, num_skipped_pages)

        while continue_loop:
            print(f"\n--- Scraping Page {page_num} ---")
            
            # Locate all table rows inside the leaderboard container
            # Adjust '.v-data-table' or 'tr' if the DOM layout varies
            rows = page.locator("table tbody tr").all()
            
            if not rows or len(rows) == 0:
                print("No table data rows detected. The page might still be loading or has ended.")
                break
                
            print(f"Found {len(rows)} runners on this page.")

            with open(output_file,"a", encoding="utf-8") as f:
            
                # Loop through rows to extract text data
                for index, row in enumerate(rows):
                    # Grabbing the inner text of all columns in the row
                    row_text = row.inner_text().replace("\n", " | ")
                    print(f"Row {index+1}: {row_text}")

                    f.write(row_text+"\n")

            f.close()

            page, page_num, continue_loop = next_page(page, page_num, continue_loop)
            
        browser.close()

if __name__ == "__main__":
    if apply_truncate_file:
        truncate_file()
        print("output file truncated")
    scrape_sportstats()
