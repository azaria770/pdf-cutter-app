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

# --- פונקציות סריקה וחילוץ (סריקה ישירה לפי מספרים) ---

CONFIG_FILE = "config.json"
DEFAULT_START_ID = 72680

def get_latest_mishkan_shilo_drive_link():
    """
    סורק דפים בצורה ישירה (72680, 72681...) ומחפש קישורי דרייב.
    אם נמצא קישור, הוא מוחזר להמשך טיפול (חיתוך).
    """
    st.info("🛠️ מתחיל סריקה ישירה של דפי פוסטים...")
    
    current_id = DEFAULT_START_ID
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                current_id = data.get("last_id", DEFAULT_START_ID)
        except: pass

    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'}

    max_attempts = 20 # מספר הדפים קדימה שנבדוק בכל הרצה
    
    for i in range(0, max_attempts):
        test_id = current_id + i
        test_url = f"https://kav.meorot.net/{test_id}/"
        st.write(f"🔍 בודק דף: {test_url}")
        
        try:
            time.sleep(1) # מניעת חסימות
            response = scraper.get(test_url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                html = response.text
                # חיפוש מזהה קובץ של גוגל דרייב (מזהה כל סוג של קישור דרייב בדף)
                drive_matches = re.findall(r'drive\.google\.com(?:%2F|/)file(?:%2F|/)d(?:%2F|/)([a-zA-Z0-9_-]{20,})', html)
                
                if drive_matches:
                    file_id = drive_matches[0]
                    found_url = f"https://drive.google.com/file/d/{file_id}/view"
                    st.success(f"✅ נמצא קישור בפוסט {test_id}: {found_url}")
                    
                    # שמירת המספר הנוכחי להרצה הבאה
                    with open(CONFIG_FILE, "w") as f:
                        json.dump({"last_id": test_id}, f)
                    
                    return found_url
                else:
                    st.write(f"   ⚠️ לא נמצא קישור לדרייב בפוסט {test_id}, ממשיך למספר הבא...")
            else:
                st.write(f"   ❌ דף {test_id} לא זמין (סטטוס {response.status_code})")
                
        except Exception as e:
            st.error(f"⚠️ שגיאה בגישה לדף {test_id}: {e}")
            
    st.error("❌ סיימנו לסרוק את טווח הדפים ולא נמצא קישור חדש.")
    return None

# --- פונקציות לוגיקה וחיתוך (ללא שינוי) ---

def find_image_in_page(page_pixmap, template_b64, threshold=0.7):
    img_array = np.frombuffer(page_pixmap.samples, dtype=np.uint8).reshape(page_pixmap.h, page_pixmap.w, page_pixmap.n)
    if page_pixmap.n >= 3: img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
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

# --- ממשק משתמש ---

def main():
    st.set_page_config(page_title="חותך PDF אוטומטי", page_icon="✂️")
    st.markdown("<style>.block-container { direction: rtl; text-align: right; }</style>", unsafe_allow_html=True)
    st.title("✂️ שליפה וחיתוך אוטומטי")
    
    START_IMG, END_IMG = "start.png", "end.png"

    if st.button("הפעל סריקה וחיתוך"):
        if not os.path.exists(START_IMG) or not os.path.exists(END_IMG):
            st.error("חסרים קבצי תמונות לזיהוי (start.png / end.png).")
            return

        with st.spinner("סורק את האתר ומעבד את הקובץ..."):
            try:
                # טעינת תמונות החיתוך
                with open(START_IMG, "rb") as f: start_b64 = base64.b64encode(f.read())
                with open(END_IMG, "rb") as f: end_b64 = base64.b64encode(f.read())

                # 1. מציאת הקישור
                link = get_latest_mishkan_shilo_drive_link()
                if not link: return

                # 2. הורדה
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    input_path = tmp.name
                gdown.download(url=link, output=input_path, quiet=False, fuzzy=True)

                # 3. חיתוך
                output_path = input_path.replace(".pdf", "_fixed.pdf")
                if extract_pdf_by_images(input_path, output_path, start_b64, end_b64):
                    st.success("הקובץ נמצא ונחתך בהצלחה!")
                    with open(output_path, "rb") as f:
                        st.download_button("📥 הורד את העלון החתוך", f, "mishkan_shilo.pdf", "application/pdf")
                else:
                    st.error("הקובץ הורד, אך לא נמצאו בתוכו סימני החיתוך.")
                    
            except Exception as e:
                st.error(f"שגיאה בתהליך: {e}")

if __name__ == "__main__":
    main()
