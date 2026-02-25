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
import datetime
import requests 
from bs4 import BeautifulSoup # הספרייה החדשה שהוספנו לחילוץ האלמנטים

# --- פונקציות סריקה מקוונת (מבוסס BeautifulSoup) ---

DEFAULT_START_ID = 72680

def get_config():
    """שולף את הנתונים ממסד הנתונים בענן (JSONBin)"""
    try:
        if 'JSONBIN_BIN_ID' in st.secrets and 'JSONBIN_API_KEY' in st.secrets:
            url = f"https://api.jsonbin.io/v3/b/{st.secrets['JSONBIN_BIN_ID']}"
            headers = {'X-Master-Key': st.secrets['JSONBIN_API_KEY']}
            req = requests.get(url, headers=headers)
            if req.status_code == 200:
                return req.json().get('record', {})
        else:
            st.write("ℹ️ דיבוג: לא הוגדרו מפתחות מסד נתונים (Secrets), מתחיל מברירת מחדל.")
    except Exception as e:
        st.warning(f"שגיאה בקריאה ממסד הנתונים: {e}")
    return {}

def save_config(data):
    """שומר את הנתונים למסד הנתונים בענן (JSONBin)"""
    try:
        if 'JSONBIN_BIN_ID' in st.secrets and 'JSONBIN_API_KEY' in st.secrets:
            url = f"https://api.jsonbin.io/v3/b/{st.secrets['JSONBIN_BIN_ID']}"
            headers = {
                'Content-Type': 'application/json',
                'X-Master-Key': st.secrets['JSONBIN_API_KEY']
            }
            requests.put(url, json=data, headers=headers)
        else:
            st.warning("⚠️ לא הוגדרו מפתחות למסד הנתונים ב-Secrets. המיקום החדש לא נשמר בענן.")
    except Exception as e:
        st.error(f"שגיאה בשמירה למסד הנתונים: {e}")

def get_latest_mishkan_shilo_drive_link():
    st.info("🛠️ יומן סריקה: סורק את עמוד הקטגוריה בעזרת BeautifulSoup...")
    
    data = get_config()
    current_id = data.get("last_id", DEFAULT_START_ID)

    try:
        # אנו משתמשים ב-cloudscraper כדי לא להיחסם (שגיאת 403)
        scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
        
        category_url = "https://kav.meorot.net/category/%d7%a2%d7%9c%d7%95%d7%a0%d7%99-%d7%a9%d7%91%d7%aa/%d7%9e%d7%a9%d7%9b%d7%9f-%d7%a9%d7%99%d7%9c%d7%94/"
        st.write("🔍 נכנס לעמוד הקטגוריה 'משכן שילה'...")
        
        cat_response = scraper.get(category_url)
        if cat_response.status_code != 200:
            st.error(f"❌ לא הצלחנו לגשת לעמוד הקטגוריה (קוד {cat_response.status_code}).")
            return None
            
        # שימוש ב-BeautifulSoup לחילוץ הפוסט הראשון כפי שהצעת
        soup = BeautifulSoup(cat_response.text, "html.parser")
        post_link = soup.select_one("h3 a, h2 a")
        
        if not post_link:
            st.error("❌ לא נמצא לינק ראשון לגליון בעמוד הקטגוריה.")
            return None
            
        target_url = post_link["href"]
        post_title = post_link.get_text(strip=True)
        
        st.write(f"✅ הפוסט האחרון שנמצא: **{post_title}**")
        
        # נחלץ את ה-ID מתוך הלינק רק כדי שנוכל לעדכן את מסד הנתונים למעקב
        highest_id = current_id
        id_match = re.search(r'kav\.meorot\.net/(\d+)', target_url)
        if id_match:
            highest_id = int(id_match.group(1))
            if highest_id > current_id:
                st.write(f"🆕 מדובר בגיליון חדש! (הקודם ששמור במערכת היה {current_id})")
            else:
                st.write(f"🔄 מושך את הגיליון האחרון המוכר...")

        # שלב 2: כניסה לפוסט הספציפי ושליפת הדרייב
        st.write(f"🔍 נכנס לתוך הגיליון כדי לשלוף את הקובץ...")
        response = scraper.get(target_url)
        
        if response.status_code == 200:
            html = response.text
            
            drive_patterns = [
                r'https://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)', 
                r'https%3A%2F%2Fdrive\.google\.com%2Ffile%2Fd%2F([a-zA-Z0-9_-]+)' 
            ]
            
            found_id = None
            for pattern in drive_patterns:
                match = re.search(pattern, html)
                if match:
                    found_id = match.group(1)
                    break
            
            if found_id:
                st.success(f"✅ נמצא מזהה קובץ (ID): {found_id}")
                
                # שמירת ה-ID במסד הנתונים
                save_config({
                    "last_id": highest_id,
                    "found_date": datetime.datetime.now().isoformat()
                })
                
                return found_id
            else:
                st.error(f"⚠️ לא נמצא קישור לדרייב בפוסט: {post_title}")
                return None
        else:
            st.error(f"❌ הפוסט לא זמין (סטטוס {response.status_code}).")
            return None
            
    except Exception as e:
        st.error(f"❌ שגיאה בסריקה: {e}")
        return None

# --- פונקציות לוגיקה ---

def find_image_in_page(page_pixmap, template_b64, threshold=0.7):
    img_array = np.frombuffer(page_pixmap.samples, dtype=np.uint8).reshape(page_pixmap.h, page_pixmap.w, page_pixmap.n)
    if page_pixmap.n >= 3:
        img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    
    img_data = base64.b64decode(template_b64)
    np_arr_template = np.frombuffer(img_data, np.uint8)
    template = cv2.imdecode(np_arr_template, cv2.IMREAD_GRAYSCALE)

    if template is None:
        return False

    for scale in np.linspace(0.4, 1.6, 12):
        width = int(template.shape[1] * scale)
        height = int(template.shape[0] * scale)
        
        if height == 0 or width == 0 or height > img_array.shape[0] or width > img_array.shape[1]:
            continue
            
        resized_template = cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(img_array, resized_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        
        if max_val >= threshold:
            return True
    return False

def extract_pdf_by_images(input_pdf_path, output_pdf_path, start_image_b64, end_image_b64):
    doc = fitz.open(input_pdf_path)
    start_page = -1
    end_page = -1

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2))

        if start_page == -1:
            if find_image_in_page(pix, start_image_b64):
                start_page = page_num
        
        if start_page != -1 and end_page == -1:
            if find_image_in_page(pix, end_image_b64):
                end_page = page_num
                break

    if start_page != -1 and end_page != -1:
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=start_page, to_page=end_page)
        new_doc.save(output_pdf_path)
        new_doc.close()
        doc.close()
        return True
    
    doc.close()
    return False

# --- ממשק משתמש ---

def main():
    st.set_page_config(page_title="חותך PDF אוטומטי", page_icon="✂️")
    st.markdown("<style>.block-container { direction: rtl; text-align: right; }</style>", unsafe_allow_html=True)
    st.title("✂️ חיתוך PDF לפי סימנים")
    
    upload_option = st.radio("איך תרצה לטעון את ה-PDF?", 
                             ("העלאת קובץ מהמחשב", 
                              "קישור מ-Google Drive", 
                              "שליפה אוטומטית (משכן שילה)"))
    
    uploaded_file = None
    manual_link = ""
    
    if upload_option == "העלאת קובץ מהמחשב":
        uploaded_file = st.file_uploader("בחר קובץ PDF מהמחשב", type=["pdf"], key="manual_upload")
    elif upload_option == "קישור מ-Google Drive":
        manual_link = st.text_input("הדבק כאן קישור שיתוף ל-PDF מ-Google Drive:")
    else:
        st.write("המערכת תיגש לאתר 'המאורות', תחפש את הגיליון העדכני ביותר של 'משכן שילה' ותוריד אותו אוטומטית.")
    
    START_IMG, END_IMG = "start.png", "end.png"

    if st.button("הפעל חיתוך אוטומטי"):
        if not os
