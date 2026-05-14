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
TIME_THRESHOLD_SECONDS = 240
MAX_ROUNDS_PER_SCRAPE = 5  # Limit rounds to prevent timeout
MAX_ITERATIONS_PER_DRIVER = 3  # Force new driver every 3 iterations
# ==========================================

app = Flask(__name__)

def parse_timestamp(ts_str):
    try:
        return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    except:
        return datetime.min

def sort_by_timestamp_then_round(results):
    if not results:
        return results
    
    for r in results:
        r['_parsed_timestamp'] = parse_timestamp(r.get('timestamp', ''))
    
    results.sort(key=lambda x: x['_parsed_timestamp'])
    
    i = 0
    n = len(results)
    while i < n:
        j = i
        base_ts = results[i]['_parsed_timestamp']
        while j < n:
            diff = (results[j]['_parsed_timestamp'] - base_ts).total_seconds()
            if diff < TIME_THRESHOLD_SECONDS:
                j += 1
            else:
                break
        if j - i > 1:
            results[i:j] = sorted(results[i:j], key=lambda x: x.get('round_number', 0))
        i = j
    
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
    
    all_results = sort_by_timestamp_then_round(all_results)
    
    with open(JSON_FILENAME, 'w', encoding='utf-8') as f:
        json.dump({
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_rows": len(all_results),
            "results": all_results
        }, f, indent=2)
    
    return len(all_results)

def create_driver():
    """Create driver using Selenium Grid with timeout settings"""
    for attempt in range(3):
        try:
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--disable-gpu')
            options.add_argument('--disable-logging')
            options.add_argument('--log-level=3')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.set_capability('pageLoadStrategy', 'eager')  # Don't wait for all resources
            options.set_capability('timeouts', {'implicit': 5000, 'pageLoad': 30000, 'script': 30000})
            options.add_experimental_option('excludeSwitches', ['enable-logging', 'enable-automation'])
            
            driver = webdriver.Remote(
                command_executor=f'{SELENIUM_GRID_URL}/wd/hub',
                options=options,
                keep_alive=False  # Don't keep connection alive
            )
            
            # Set timeouts
            driver.set_page_load_timeout(30)
            driver.set_script_timeout(20)
            
            # Test connection with a simple command
            driver.get('https://www.google.com')
            print("   ✅ Connected to Selenium Grid and verified")
            return driver
            
        except Exception as e:
            print(f"   ⚠️ Connection attempt {attempt + 1} failed: {str(e)[:100]}")
            if attempt < 2:
                time.sleep(5)
            else:
                print(f"   ❌ Failed to connect to grid after 3 attempts")
                return None
    
    return None

def test_driver_health(driver):
    """Test if driver is still responsive"""
    try:
        driver.current_url  # Simple command to test health
        return True
    except:
        return False

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
        # Set script timeout for this operation
        driver.set_script_timeout(20)
        
        print("   Loading website...")
        driver.get('https://www.simacombet.com/luckysix')
        
        # Use shorter wait times
        try:
            iframe = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.ID, "PluginLuckySix"))
            )
            driver.switch_to.frame(iframe)
            print("   ✅ Iframe loaded")
        except TimeoutException:
            print("   ❌ Iframe timeout")
            return None
        
        try:
            button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Results')]"))
            )
            button.click()
            time.sleep(1)  # Reduced sleep
            print("   ✅ Results button clicked")
        except TimeoutException:
            print("   ❌ Results button timeout")
            return None
        
        # Get rounds with shorter timeout
        round_rows = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.round-row"))
        )
        print(f"   Found {len(round_rows)} rounds")
        
        existing = load_existing_data()
        existing_nums = {r.get('round_number') for r in existing}
        
        new_rounds = []
        rounds_processed = 0
        
        for row in round_rows:
            if rounds_processed >= MAX_ROUNDS_PER_SCRAPE:
                print(f"   Reached limit of {MAX_ROUNDS_PER_SCRAPE} rounds per scrape")
                break
                
            try:
                title = row.find_element(By.CSS_SELECTOR, "div.accordion-title")
                title_text = title.text.strip()
                match = re.search(r'Round\s*(\d+)', title_text)
                if not match:
                    continue
                round_num = int(match.group(1))
                
                if round_num in existing_nums:
                    continue
                
                # Scroll and click with JavaScript (more reliable)
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", row)
                time.sleep(0.3)
                driver.execute_script("arguments[0].click();", row)
                time.sleep(1)  # Reduced wait
                
                # Quick check for draw sequences
                try:
                    draw_seqs = WebDriverWait(driver, 5).until(
                        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.draw-sequence"))
                    )
                except:
                    draw_seqs = []
                
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
                
                if first_numbers:
                    result = {
                        'round_number': round_num,
                        'round_title': title_text,
                        'first_draw_numbers': [int(n) for n in first_numbers],
                        'second_draw_numbers': [],
                        'timestamp': datetime.now().isoformat()
                    }
                    new_rounds.append(result)
                    print(f"   ✅ Round {round_num} collected: {len(first_numbers)} numbers")
                    rounds_processed += 1
                else:
                    print(f"   ⚠️ Round {round_num}: no numbers found")
                
                # Close accordion
                driver.execute_script("arguments[0].click();", row)
                time.sleep(0.3)
                
            except Exception as e:
                print(f"   ⚠️ Error on round: {str(e)[:80]}")
                continue
        
        return new_rounds
        
    except TimeoutException as e:
        print(f"   ❌ Timeout during scrape: {e}")
        return None
    except Exception as e:
        print(f"   ❌ Scrape error: {e}")
        return None

def run_scraper_loop():
    print("=" * 70)
    print("🤖 LOTTERY SCRAPER - OPTIMIZED VERSION")
    print("=" * 70)
    print(f"📅 Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏱️  Scrape interval: {SCRAPE_INTERVAL_MINUTES} minutes")
    print(f"🔗 Grid URL: {SELENIUM_GRID_URL}")
    print(f"📊 Max rounds per scrape: {MAX_ROUNDS_PER_SCRAPE}")
    print(f"🔄 Driver refresh every {MAX_ITERATIONS_PER_DRIVER} iterations")
    print("=" * 70)
    
    existing = load_existing_data()
    print(f"\n📊 Starting with {len(existing)} rounds")
    
    iteration = 0
    consecutive_failures = 0
    driver = None
    iterations_on_current_driver = 0
    
    while True:
        iteration += 1
        print(f"\n🔄 ITERATION #{iteration} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Force driver refresh after N iterations
        if driver and iterations_on_current_driver >= MAX_ITERATIONS_PER_DRIVER:
            print(f"   Refreshing driver after {iterations_on_current_driver} iterations...")
            try:
                driver.quit()
            except:
                pass
            driver = None
            iterations_on_current_driver = 0
            time.sleep(5)
        
        # Create driver if needed
        if driver is None:
            print("   Connecting to Selenium Grid...")
            driver = create_driver()
            if driver is None:
                consecutive_failures += 1
                wait_time = min(60 * consecutive_failures, 300)
                print(f"   ❌ Failed, waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            iterations_on_current_driver = 0
        
        # Test if driver is still healthy
        if not test_driver_health(driver):
            print("   ⚠️ Driver unhealthy, recreating...")
            try:
                driver.quit()
            except:
                pass
            driver = None
            time.sleep(5)
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
                
                print(f"   ✅ Scrape successful!")
                iterations_on_current_driver += 1
                
            else:
                consecutive_failures += 1
                print(f"   ⚠️ Scrape failed ({consecutive_failures})")
                
                # Driver is likely dead, force recreation
                if driver:
                    try:
                        driver.quit()
                    except:
                        pass
                    driver = None
                    iterations_on_current_driver = 0
                
                if consecutive_failures >= 3:
                    print("   Waiting 2 minutes before retry...")
                    time.sleep(120)
                    consecutive_failures = 0
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
            if driver:
                try:
                    driver.quit()
                except:
                    pass
                driver = None
                iterations_on_current_driver = 0
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
    return {"status": "healthy", "iterations": "running"}

if __name__ == "__main__":
    thread = threading.Thread(target=run_scraper_loop)
    thread.daemon = True
    thread.start()
    
    print("\n🌐 Starting web server on port 10000...")
    app.run(host='0.0.0.0', port=10000, threaded=True)
