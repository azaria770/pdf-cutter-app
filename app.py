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

# --- פונקציות סריקה מקוונת (זיהוי קישורים משופר) ---

CONFIG_FILE = "config.json"
DEFAULT_START_ID = 72680

def get_latest_mishkan_shilo_drive_link():
    """
    סורק דפים ומחפש כל רמז לקישור גוגל דרייב בקוד ה-HTML.
    """
    st.info("🛠️ מתחיל סריקה מעמיקה לזיהוי הקישור...")
    
    current_id = DEFAULT_START_ID
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                current_id = data.get("last_id", DEFAULT_START_ID)
        except: pass

    try:
        scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
        max_attempts = 50 
        
        for i in range(0, max_attempts):
            test_id = current_id + i
            test_url = f"https://kav.meorot.net/{test_id}/"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Referer': 'https://kav.meorot.net/'
            }

            st.write(f"🔍 בודק דף {test_id}...")
            time.sleep(1) 
            response = scraper.get(test_url, headers=headers, timeout=20)
            
            if response.status_code == 200:
                html = response.text
                
                # מנגנון חיפוש רחב - מחפש כל מופע של ID של גוגל דרייב (6-40 תווים של אותיות ומספרים אחרי ה-/d/)
                # מחפש גם קישורים רגילים וגם מקודדים (עבור תמונות/iframe)
                links_found = re.findall(r'drive\.google\.com(?:%2F|/)file(?:%2F|/)d(?:%2F|/)([a-zA-Z0-9_-]{20,})', html)
                
                if links_found:
                    # לוקחים את הראשון שנמצא
                    file_id = links_found[0]
                    found_url = f"https://drive.google.com/file/d/{file_id}"
                    st.success(f"✅ נמצא קישור: {found_url}")
                    
                    with open(CONFIG_FILE, "w") as f:
                        json.dump({"last_id": test_id}, f)
                    
                    return found_url
                else:
                    # הודעת דיבוג למקרה שלא נמצא - עוזרת להבין מה השתנה באתר
                    st.write(f"   ⚠️ בדף {test_id} לא נמצאה תבנית מוכרת של גוגל דרייב.")
                    if "drive" in html.lower():
                        st.caption("נמצאה המילה 'drive' בדף, אך לא בפורמט של קישור תקין.")
            
            elif response.status_code == 403:
                st.error(f"❌ חסימה (403) ב- {test_id}. נסה שוב מאוחר יותר.")
                return None
            else:
                st.write(f"   ❌ דף {test_id} לא זמין (קוד {response.status_code}).")
                
        return None
    except Exception as e:
        st.error(f"❌ שגיאה טכנית: {e}")
        return None

# --- פונקציות לוגיקה (ללא שינוי - נשמרות בדיוק כפי שהיו) ---

def find_image_in_page(page_pixmap, template_b64, threshold=0.7):
    img_array = np.frombuffer(page_pixmap.samples, dtype=np.uint8).reshape(page_pixmap.h, page_pixmap.w, page_pixmap.n)
    if page_pixmap.n >= 3:
        img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    img_data = base64.b64decode(template_b64)
    np_arr_template = np.frombuffer(img_data, np.uint8)
    template = cv2.imdecode(np_arr_template, cv2.IMREAD_GRAYSCALE)
    if template is None: return False
    for scale in np.linspace(0.4, 1.6, 12):
        width, height = int(template.shape[1] * scale), int(template.shape[0] * scale)
        if height == 0 or width == 0 or height > img_array.shape[0] or width > img_array.shape[1]: continue
        resized_template = cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(img_array, resized_template, cv2.TM_CCOEFF_NORMED)
        if cv2.minMaxLoc(result)[1] >= threshold: return True
    return False

def extract_pdf_by_images(input_pdf_path, output_pdf_path, start_image_b64, end_image_b64):
    doc = fitz.open(input_pdf_path)
    start_page, end_page = -1, -1
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2))
        if start_page == -1 and find_image_in_page(pix, start_image_b64): start_page = page_num
        if start_page != -1 and end_page == -1 and find_image_in_page(pix, end_image_b64):
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

def main():
    st.set_page_config(page_title="חותך PDF אוטומטי", page_icon="✂️")
    st.markdown("<style>.block-container { direction: rtl; text-align: right; }</style>", unsafe_allow_html=True)
    st.title("✂️ חיתוך PDF לפי סימנים")
    
    upload_option = st.radio("איך תרצה לטעון את ה-PDF?", ("העלאת קובץ מהמחשב", "קישור מ-Google Drive", "שליפה אוטומטית (משכן שילה)"))
    START_IMG, END_IMG = "start.png", "end.png"

    if st.button("הפעל תהליך"):
        try:
            with open(START_IMG, "rb") as f: start_b64 = base64.b64encode(f.read())
            with open(END_IMG, "rb") as f: end_b64 = base64.b64encode(f.read())
            input_path = ""
            
            if upload_option == "העלאת קובץ מהמחשב":
                file = st.file_uploader("בחר קובץ", type=["pdf"])
                if not file: return
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(file.getvalue()); input_path = tmp.name
            elif upload_option == "שליפה אוטומטית (משכן שילה)":
                link = get_latest_mishkan_shilo_drive_link()
                if not link: return
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp: input_path = tmp.name
                gdown.download(url=link, output=input_path, quiet=False, fuzzy=True)
            else:
                link = st.text_input("הכנס קישור:")
                if not link: return
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp: input_path = tmp.name
                gdown.download(url=link, output=input_path, quiet=False, fuzzy=True)

            if input_path and os.path.exists(input_path):
                output_path = input_path.replace(".pdf", "_fixed.pdf")
                if extract_pdf_by_images(input_path, output_path, start_b64, end_b64):
                    st.success("הושלם!")
                    with open(output_path, "rb") as f: st.download_button("📥 הורד קובץ", f, "cut.pdf", "application/pdf")
                else: st.error("לא נמצאו סימני חיתוך.")
        except Exception as e: st.error(f"שגיאה: {e}")

if __name__ == "__main__":
    main()
