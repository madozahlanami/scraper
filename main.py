from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import json
import os
import re
from datetime import datetime
from flask import Flask, jsonify
import threading

app = Flask(__name__)
JSON_FILENAME = "results.json"
SCRAPE_INTERVAL_MINUTES = 27

def load_existing_data():
    if not os.path.exists(JSON_FILENAME):
        return []
    try:
        with open(JSON_FILENAME, 'r') as f:
            data = json.load(f)
            return data.get('results', [])
    except:
        return []

def save_results(new_rounds):
    existing = load_existing_data()
    seen = {r.get('round_number') for r in existing}
    all_results = existing.copy()
    
    for r in new_rounds:
        if r.get('round_number') not in seen:
            seen.add(r.get('round_number'))
            all_results.append(r)
            print(f"   ✅ Added round {r.get('round_number')}")
    
    with open(JSON_FILENAME, 'w') as f:
        json.dump({"results": all_results, "total": len(all_results)}, f, indent=2)
    
    return len(all_results)

def scrape_rounds():
    """Direct Chrome connection - NO GRID NEEDED"""
    driver = None
    try:
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        
        # Connect directly to Chrome (not grid)
        driver = webdriver.Chrome(options=options)
        print("   ✅ Chrome started")
        
        driver.get('https://www.simacombet.com/luckysix')
        time.sleep(3)
        
        # Switch to iframe
        iframe = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "PluginLuckySix"))
        )
        driver.switch_to.frame(iframe)
        
        # Click results button
        button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Results')]"))
        )
        button.click()
        time.sleep(2)
        
        # Get rounds
        round_rows = driver.find_elements(By.CSS_SELECTOR, "div.round-row")
        print(f"   Found {len(round_rows)} rounds")
        
        existing = load_existing_data()
        existing_nums = {r.get('round_number') for r in existing}
        new_rounds = []
        
        for row in round_rows[:5]:
            try:
                title = row.find_element(By.CSS_SELECTOR, "div.accordion-title")
                title_text = title.text.strip()
                match = re.search(r'Round\s*(\d+)', title_text)
                if not match:
                    continue
                round_num = int(match.group(1))
                
                if round_num in existing_nums:
                    continue
                
                row.click()
                time.sleep(2)
                
                draw_seqs = driver.find_elements(By.CSS_SELECTOR, "div.draw-sequence")
                numbers = []
                
                for seq in draw_seqs:
                    seq_title = seq.find_element(By.CSS_SELECTOR, "div.title").text.lower()
                    if "drawn" in seq_title:
                        balls = seq.find_elements(By.CSS_SELECTOR, "div.balls button")
                        for ball in balls:
                            text = ball.text.strip()
                            if text and text.isdigit():
                                numbers.append(text)
                
                if numbers:
                    new_rounds.append({
                        'round_number': round_num,
                        'round_title': title_text,
                        'first_draw_numbers': [int(n) for n in numbers],
                        'second_draw_numbers': [],
                        'timestamp': datetime.now().isoformat()
                    })
                    print(f"   ✅ Round {round_num}: {numbers}")
                
                row.click()
                time.sleep(1)
                
            except Exception as e:
                print(f"   ⚠️ Error: {e}")
                continue
        
        return new_rounds
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return None
    finally:
        if driver:
            driver.quit()

def run_scraper():
    print("=" * 60)
    print("🤖 LOTTERY SCRAPER - DIRECT CHROME")
    print("=" * 60)
    
    while True:
        print(f"\n🔄 Scraping at {datetime.now()}")
        new_rounds = scrape_rounds()
        
        if new_rounds:
            total = save_results(new_rounds)
            print(f"💾 Saved {len(new_rounds)} rounds. Total: {total}")
        else:
            print("No new rounds found")
        
        print(f"💤 Sleeping 27 minutes...")
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
    thread = threading.Thread(target=run_scraper, daemon=True)
    thread.start()
    app.run(host='0.0.0.0', port=10000)
