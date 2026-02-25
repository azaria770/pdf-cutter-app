import fitz  # PyMuPDF
import cv2
import numpy as np
import os
import base64
import tempfile
import streamlit as st
import gdown
import re
import cloudscraper
import json
import urllib.parse
import time

# --- פונקציות סריקה מקוונת (עקיפת חסימת 403) ---

CONFIG_FILE = "config.json"
DEFAULT_START_ID = 72680

def get_latest_mishkan_shilo_drive_link():
    """
    סורק דפים ומנסה לעקוף חסימת 403 באמצעות Headers מורחבים.
    """
    st.info("🛠️ מנסה להתחבר לאתר (עקיפת חסימה)...")
    
    current_id = DEFAULT_START_ID
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                current_id = data.get("last_id", DEFAULT_START_ID)
        except: pass

    try:
        # יצירת סורק עם הגדרות דפדפן ספציפיות
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )
        
        max_attempts = 50 
        
        for i in range(0, max_attempts):
            test_id = current_id + i
            test_url = f"https://kav.meorot.net/{test_id}/"
            
            # הוספת Headers ידניים כדי להיראות כמו דפדפן אמיתי
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7',
                'Referer': 'https://kav.meorot.net/',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }

            st.write(f"🔍 בודק את {test_id}...")
            
            # ניסיון גישה עם השהיה קלה למניעת זיהוי
            time.sleep(1) 
            response = scraper.get(test_url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                html = response.text
                
                # חיפוש לינק דרייב (regex משופר)
                pattern = r'https?://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)'
                match = re.search(pattern, html)
                
                if not match and "%3A" in html: # בדיקה אם הלינק מקודד בתוך ה-HTML
                    encoded_pattern = r'https%3A%2F%2Fdrive\.google\.com%2Ffile%2Fd%2F([a-zA-Z0-9_-]+)'
                    match = re.search(encoded_pattern, html)
                
                if match:
                    file_id = match.group(1)
                    found_url = f"https://drive.google.com/file/d/{file_id}"
                    st.success(f"✅ הצלחנו! נמצא קישור: {found_url}")
                    
                    with open(CONFIG_FILE, "w") as f:
                        json.dump({"last_id": test_id}, f)
                    
                    return found_url
                else:
                    st.write(f"   ⚠️ דף {test_id} נפתח, אך הקישור לדרייב לא נמצא בקוד.")
            
            elif response.status_code == 403:
                st.error(f"❌ חסימה (403) בכתובת {test_id}. האתר מזהה אותנו כבוט.")
                return None
            else:
                st.write(f"   ❌ דף {test_id} החזיר שגיאה {response.status_code}.")
                
        return None
    except Exception as e:
        st.error(f"❌ שגיאה טכנית: {e}")
        return None

# --- יתר הפונקציות נשארות ללא שינוי בהתאם לבקשתך ---
# (find_image_in_page, extract_pdf_by_images, main)
# ... [המשך הקוד מהגרסה הקודמת]
