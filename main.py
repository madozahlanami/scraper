from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, WebDriverException
import time
import json
import os
import re
from datetime import datetime
from flask import Flask, jsonify
import threading

# ============= CONFIGURATION =============
SCRAPE_INTERVAL_MINUTES = 27
JSON_FILENAME = "results.json"
SELENIUM_GRID_URL = os.getenv('SELENIUM_GRID_URL', 'http://selenium-hub.railway.internal:4444')
TIME_THRESHOLD_SECONDS = 240  # 4 minutes
# New timeout configurations
GRID_CONNECTION_TIMEOUT = 60  # 60 seconds for grid connection
PAGE_LOAD_TIMEOUT = 30  # 30 seconds for page load
SCRIPT_TIMEOUT = 20  # 20 seconds for scripts
# ==========================================

app = Flask(__name__)

def parse_timestamp(ts_str):
    """Convert timestamp string to datetime object for sorting"""
    try:
        return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    except:
        return datetime.min

def sort_by_timestamp_then_round(results):
    """
    CRITICAL SORTING RULE:
    1. First sort by timestamp (oldest first)
    2. If timestamps are within 4 minutes, then sort by round number
    """
    if not results:
        return results
    
    # Add parsed timestamp to each result
    for r in results:
        r['_parsed_timestamp'] = parse_timestamp(r.get('timestamp', ''))
    
    # Sort by timestamp first
    results.sort(key=lambda x: x['_parsed_timestamp'])
    
    # Now handle clusters within 4 minutes
    i = 0
    n = len(results)
    while i < n:
        j = i
        base_ts = results[i]['_parsed_timestamp']
        # Find cluster where timestamps are within THRESHOLD
        while j < n:
            diff = (results[j]['_parsed_timestamp'] - base_ts).total_seconds()
            if diff < TIME_THRESHOLD_SECONDS:
                j += 1
            else:
                break
        # Sort this cluster by round number (ascending)
        if j - i > 1:
            results[i:j] = sorted(results[i:j], key=lambda x: x.get('round_number', 0))
        i = j
    
    # Remove temporary field
    for r in results:
        del r['_parsed_timestamp']
    
    return results

def load_existing_data():
    if not os.path.exists(JSON_FILENAME):
        return []
    try:
        with open(JSON_FILENAME, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('results', [])
    except:
        return []

def save_results(new_results):
    existing = load_existing_data()
    
    # Merge existing and new
    seen = set()
    all_results = []
    for r in existing:
        num = r.get('round_number')
        if num not in seen:
            seen.add(num)
            all_results.append(r)
    for r in new_results:
        num = r.get('round_number')
        if num not in seen:
            seen.add(num)
            all_results.append(r)
            print(f"      Added new round {num}")
    
    # CRITICAL: Sort by timestamp first, then round number within 4 minutes
    all_results = sort_by_timestamp_then_round(all_results)
    
    # Save to file
    with open(JSON_FILENAME, 'w', encoding='utf-8') as f:
        json.dump({
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_rows": len(all_results),
            "results": all_results
        }, f, indent=2)
    
    return len(all_results)

def create_driver():
    """Create driver using Selenium Grid with better timeout handling"""
    for attempt in range(3):  # Retry up to 3 times
        try:
            print(f"   Attempting to connect to grid (attempt {attempt + 1}/3)...")
            
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--disable-gpu')
            options.add_argument('--disable-logging')
            options.add_argument('--log-level=3')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_experimental_option('excludeSwitches', ['enable-logging', 'enable-automation'])
            options.add_experimental_option('useAutomationExtension', False)
            
            # Set page load strategy to 'eager' to reduce wait time
            options.page_load_strategy = 'eager'
            
            driver = webdriver.Remote(
                command_executor=f'{SELENIUM_GRID_URL}/wd/hub',
                options=options
            )
            
            # Set timeouts
            driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
            driver.set_script_timeout(SCRIPT_TIMEOUT)
            
            # Test the connection
            driver.get('https://www.google.com')
            print("   ✅ Successfully connected to Selenium Grid")
            return driver
            
        except Exception as e:
            print(f"   ⚠️ Connection attempt {attempt + 1} failed: {str(e)[:100]}")
            if attempt < 2:
                time.sleep(5)
            else:
                print(f"   ❌ Failed to connect to grid after 3 attempts")
                return None
    
    return None

def extract_numbers_from_balls(balls_div):
    numbers = []
    try:
        buttons = balls_div.find_elements(By.TAG_NAME, "button")
        for button in buttons:
            text = button.text.strip()
            if text and text.isdigit():
                numbers.append(text)
    except:
        pass
    return numbers

def scrape_rounds(driver):
    """Scrape rounds from website with better error handling"""
    try:
        print("   Loading website...")
        driver.get('https://www.simacombet.com/luckysix')
        time.sleep(2)  # Reduced sleep
        
        try:
            iframe = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "PluginLuckySix"))
            )
            driver.switch_to.frame(iframe)
        except TimeoutException:
            print("   ⚠️ Iframe not found, trying alternative selector...")
            iframe = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[src*='LuckySix']"))
            )
            driver.switch_to.frame(iframe)
        
        try:
            button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Results')]"))
            )
            button.click()
            time.sleep(1.5)
        except:
            print("   ⚠️ Results button not found, trying alternative...")
            button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.results-btn"))
            )
            button.click()
            time.sleep(1.5)
        
        round_rows = driver.find_elements(By.CSS_SELECTOR, "div.round-row")
        print(f"   Found {len(round_rows)} rounds")
        
        existing = load_existing_data()
        existing_nums = {r.get('round_number') for r in existing}
        
        new_rounds = []
        
        for idx, row in enumerate(round_rows[:10]):  # Limit to 10 rounds per scrape to avoid timeout
            try:
                title = row.find_element(By.CSS_SELECTOR, "div.accordion-title")
                title_text = title.text.strip()
                match = re.search(r'Round\s*(\d+)', title_text)
                if not match:
                    continue
                round_num = int(match.group(1))
                
                if round_num in existing_nums:
                    continue
                
                # Scroll and click
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", row)
                time.sleep(0.3)
                driver.execute_script("arguments[0].click();", row)
                time.sleep(1.5)
                
                # Wait for content to load
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.draw-sequence"))
                )
                
                draw_seqs = driver.find_elements(By.CSS_SELECTOR, "div.draw-sequence")
                first_numbers = []
                
                for seq in draw_seqs:
                    try:
                        seq_title = seq.find_element(By.CSS_SELECTOR, "div.title").text.lower()
                        if "drawn" in seq_title:
                            balls = seq.find_elements(By.CSS_SELECTOR, "div.balls")
                            for b in balls:
                                first_numbers.extend(extract_numbers_from_balls(b))
                    except:
                        continue
                
                result = {
                    'round_number': round_num,
                    'round_title': title_text,
                    'first_draw_numbers': [int(n) for n in first_numbers if n],
                    'second_draw_numbers': [],
                    'timestamp': datetime.now().isoformat()
                }
                new_rounds.append(result)
                print(f"   ✅ Round {round_num} collected")
                
                # Close accordion
                driver.execute_script("arguments[0].click();", row)
                time.sleep(0.5)
                
            except Exception as e:
                print(f"   ⚠️ Error on round {idx}: {str(e)[:80]}")
                continue
        
        return new_rounds if new_rounds else []
        
    except Exception as e:
        print(f"   ❌ Scrape error: {str(e)[:200]}")
        return None

def run_scraper_loop():
    print("=" * 70)
    print("🤖 LOTTERY SCRAPER - SELENIUM GRID VERSION")
    print("=" * 70)
    print("   ✓ Using Railway Selenium Grid")
    print("   ✓ Sorting: TIMESTAMP first, then ROUND NUMBER within 4 minutes")
    print("=" * 70)
    print(f"📅 Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏱️  Scrape interval: {SCRAPE_INTERVAL_MINUTES} minutes")
    print(f"🔗 Grid URL: {SELENIUM_GRID_URL}")
    print("=" * 70)
    
    existing = load_existing_data()
    print(f"\n📊 Starting with {len(existing)} rounds")
    
    iteration = 0
    consecutive_failures = 0
    driver = None
    
    while True:
        iteration += 1
        print(f"\n🔄 ITERATION #{iteration} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Refresh driver if needed (every 5 iterations to prevent memory issues)
        if driver is None or iteration % 5 == 0:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
                driver = None
                time.sleep(2)
        
        if driver is None:
            driver = create_driver()
            if driver is None:
                consecutive_failures += 1
                wait_time = min(60 * consecutive_failures, 300)  # Max 5 minutes
                print(f"   Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
                continue
        
        try:
            new_rounds = scrape_rounds(driver)
            
            if new_rounds is not None:
                if new_rounds:
                    total = save_results(new_rounds)
                    print(f"   💾 Saved {len(new_rounds)} new rounds. Total: {total}")
                    consecutive_failures = 0
                else:
                    print("   No new rounds found")
                    consecutive_failures = 0
                
                print(f"✅ Scrape successful!")
                
            else:
                consecutive_failures += 1
                print(f"⚠️ Scrape failed ({consecutive_failures})")
                
                if driver:
                    try:
                        driver.quit()
                    except:
                        pass
                    driver = None
                
                if consecutive_failures >= 3:
                    print("   Waiting 3 minutes before retry...")
                    time.sleep(180)
                    consecutive_failures = 0
                
        except WebDriverException as e:
            print(f"❌ WebDriver error: {str(e)[:100]}")
            if driver:
                try:
                    driver.quit()
                except:
                    pass
                driver = None
            time.sleep(30)
        except Exception as e:
            print(f"❌ Unexpected error: {str(e)[:100]}")
            time.sleep(30)
        
        print(f"\n💤 Sleeping for {SCRAPE_INTERVAL_MINUTES} minutes...")
        time.sleep(SCRAPE_INTERVAL_MINUTES * 60)

@app.route('/')
def home():
    return "<h1>Lottery Scraper</h1><p><a href='/data'>View data</a></p>"

@app.route('/data')
def get_data():
    if os.path.exists(JSON_FILENAME):
        with open(JSON_FILENAME, 'r', encoding='utf-8') as f:
            data = json.load(f)
            results = data.get('results', [])
            results = sort_by_timestamp_then_round(results)
            data['results'] = results
            return jsonify(data)
    return {"error": "No data"}

@app.route('/health')
def health():
    """Health check endpoint for Railway"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    thread = threading.Thread(target=run_scraper_loop)
    thread.daemon = True
    thread.start()
    
    print("\nStarting web server on port 10000...")
    app.run(host='0.0.0.0', port=10000)
