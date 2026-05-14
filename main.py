from playwright.sync_api import sync_playwright
import time
import json
import os
import re
from datetime import datetime
from flask import Flask, jsonify
import threading

app = Flask(__name__)
JSON_FILENAME = "results.json"

def scrape_rounds():
    """Scrape using Playwright - no Selenium Grid needed"""
    try:
        with sync_playwright() as p:
            # Launch browser directly (no grid required)
            browser = p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            page = browser.new_page()
            
            print("   Loading website...")
            page.goto('https://www.simacombet.com/luckysix', timeout=30000)
            time.sleep(2)
            
            # Find and click results button
            page.click('button:has-text("Results")')
            time.sleep(2)
            
            # Get all round rows
            round_rows = page.query_selector_all('div.round-row')
            print(f"   Found {len(round_rows)} rounds")
            
            # Load existing data
            existing = load_existing_data()
            existing_nums = {r.get('round_number') for r in existing}
            new_rounds = []
            
            for row in round_rows[:10]:  # Limit to 10 per run
                try:
                    title = row.query_selector('div.accordion-title')
                    title_text = title.inner_text()
                    match = re.search(r'Round\s*(\d+)', title_text)
                    if not match:
                        continue
                    
                    round_num = int(match.group(1))
                    if round_num in existing_nums:
                        continue
                    
                    # Click to expand
                    row.click()
                    time.sleep(1.5)
                    
                    # Extract numbers
                    draw_sequences = page.query_selector_all('div.draw-sequence')
                    first_numbers = []
                    
                    for seq in draw_sequences:
                        seq_title = seq.query_selector('div.title')
                        if seq_title and 'drawn' in seq_title.inner_text().lower():
                            balls = seq.query_selector_all('div.balls button')
                            for ball in balls:
                                text = ball.inner_text()
                                if text and text.isdigit():
                                    first_numbers.append(text)
                    
                    new_rounds.append({
                        'round_number': round_num,
                        'round_title': title_text,
                        'first_draw_numbers': [int(n) for n in first_numbers],
                        'second_draw_numbers': [],
                        'timestamp': datetime.now().isoformat()
                    })
                    print(f"   ✅ Round {round_num} collected")
                    
                    # Close
                    row.click()
                    time.sleep(0.5)
                    
                except Exception as e:
                    print(f"   ⚠️ Error: {e}")
                    continue
            
            browser.close()
            return new_rounds
            
    except Exception as e:
        print(f"   ❌ Scrape error: {e}")
        return None

def load_existing_data():
    if not os.path.exists(JSON_FILENAME):
        return []
    try:
        with open(JSON_FILENAME, 'r') as f:
            data = json.load(f)
            return data.get('results', [])
    except:
        return []

def save_results(new_results):
    existing = load_existing_data()
    seen = {r.get('round_number') for r in existing}
    all_results = existing.copy()
    
    for r in new_results:
        if r.get('round_number') not in seen:
            seen.add(r.get('round_number'))
            all_results.append(r)
    
    with open(JSON_FILENAME, 'w') as f:
        json.dump({"results": all_results, "total": len(all_results)}, f, indent=2)
    
    return len(all_results)

def run_scraper_loop():
    print("🤖 LOTTERY SCRAPER - PLAYWRIGHT VERSION")
    print("=" * 50)
    
    while True:
        print(f"\n🔄 Scraping at {datetime.now()}")
        new_rounds = scrape_rounds()
        
        if new_rounds:
            total = save_results(new_rounds)
            print(f"💾 Saved {len(new_rounds)} rounds. Total: {total}")
        else:
            print("No new rounds found")
        
        print(f"💤 Sleeping for 27 minutes...")
        time.sleep(27 * 60)

@app.route('/')
def home():
    return "<h1>Lottery Scraper</h1><a href='/data'>View Data</a>"

@app.route('/data')
def get_data():
    if os.path.exists(JSON_FILENAME):
        with open(JSON_FILENAME, 'r') as f:
            return jsonify(json.load(f))
    return {"error": "No data"}

if __name__ == "__main__":
    # Install playwright browsers on startup
    import subprocess
    subprocess.run(["playwright", "install", "chromium"], capture_output=True)
    
    thread = threading.Thread(target=run_scraper_loop)
    thread.daemon = True
    thread.start()
    
    app.run(host='0.0.0.0', port=10000)
