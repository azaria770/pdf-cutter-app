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

# --- פונקציות סריקה (לוגיקת דו-שלבית: קטגוריה -> פוסט) ---

CATEGORY_URL = "https://kav.meorot.net/category/%d7%a2%d7%9c%d7%95%d7%a0%d7%99-%d7%a9%d7%91%d7%aa/%d7%9e%d7%a9%d7%9b%d7%9f-%d7%a9%d7%91%d7%aa/"

def get_latest_mishkan_shilo_drive_link():
    """
    1. נכנס לדף הקטגוריה ושולף את הקישור לפוסט הכי חדש.
    2. נכנס לדף הפוסט ושולף את קישור הגוגל דרייב.
    """
    st.info("🌐 מתחבר לדף הקטגוריה של 'משכן שילה'...")
    
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'}

    try:
        # שלב א': מציאת הפוסט האחרון
        response = scraper.get(CATEGORY_URL, headers=headers, timeout=20)
        if response.status_code != 200:
            st.error(f"❌ לא ניתן לגשת לדף הקטגוריה (קוד {response.status_code})")
            return None
        
        # חיפוש כל הקישורים מהצורה https://kav.meorot.net/XXXXX/
        post_links = re.findall(r'https://kav\.meorot\.net/(\[0-9\]+)/', response.text)
        if not post_links:
            st.error("❌ לא נמצאו קישורי פוסטים בדף הקטגוריה.")
            return None
        
        # בחירת המספר הגבוה ביותר (הכי חדש)
        latest_post_id = max(set(map(int, post_links)))
        latest_post_url = f"https://kav.meorot.net/{latest_post_id}/"
        st.write(f"📄 נמצא פוסט עדכני: {latest_post_id}. נכנס פנימה...")

        # שלב ב': מציאת הדרייב בתוך הפוסט
        time.sleep(1)
        post_response = scraper.get(latest_post_url, headers=headers, timeout=20)
        if post_response.status_code != 200:
            st.error(f"❌ שגיאה בכניסה לפוסט {latest_post_id}")
            return None

        html = post_response.text
        # חיפוש גמיש לדרייב (כולל מקודד)
        drive_links = re.findall(r'drive\.google\.com(?:%2F|/)file(?:%2F|/)d(?:%2F|/)([a-zA-Z0-9_-]{20,})', html)
        
        if drive_links:
            file_id = drive_links[0]
            found_url = f"https://drive.google.com/file/d/{file_id}"
            st.success(f"✅ נמצא קישור לקובץ ה-PDF!")
            return found_url
        else:
            st.error(f"❌ הפוסט {latest_post_id} נמצא, אך אין בתוכו קישור לגוגל דרייב.")
            return None

    except Exception as e:
        st.error(f"❌ שגיאה בתהליך השליפה: {e}")
        return None

# --- שאר הפונקציות (find_image_in_page, extract_pdf_by_images, main) נשארות ללא שינוי ---
# (מעתיק רק את ה-main כדי לוודא שקריאת הפונקציה תואמת)

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

def main():
    st.set_page_config(page_title="חותך PDF אוטומטי", page_icon="✂️")
    st.markdown("<style>.block-container { direction: rtl; text-align: right; }</style>", unsafe_allow_html=True)
    st.title("✂️ חותך משכן שילה אוטומטי")
    
    upload_option = st.radio("בחר מקור:", ("שליפה אוטומטית (מהאתר)", "העלאת קובץ ידנית", "קישור דרייב ידני"))
    START_IMG, END_IMG = "start.png", "end.png"

    if st.button("הפעל"):
        try:
            with open(START_IMG, "rb") as f: start_b64 = base64.b64encode(f.read())
            with open(END_IMG, "rb") as f: end_b64 = base64.b64encode(f.read())
            input_path = ""
            
            if upload_option == "שליפה אוטומטית (מהאתר)":
                link = get_latest_mishkan_shilo_drive_link()
                if not link: return
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp: input_path = tmp.name
                gdown.download(url=link, output=input_path, quiet=False, fuzzy=True)
            elif upload_option == "העלאת קובץ ידנית":
                file = st.file_uploader("בחר PDF", type=["pdf"])
                if not file: return
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(file.getvalue()); input_path = tmp.name
            else:
                link = st.text_input("קישור דרייב:")
                if not link: return
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp: input_path = tmp.name
                gdown.download(url=link, output=input_path, quiet=False, fuzzy=True)

            if input_path and os.path.exists(input_path):
                output_path = input_path.replace(".pdf", "_fixed.pdf")
                if extract_pdf_by_images(input_path, output_path, start_b64, end_b64):
                    st.success("החיתוך הצליח!")
                    with open(output_path, "rb") as f: st.download_button("📥 הורד קובץ", f, "mishkan_shilo.pdf", "application/pdf")
                else: st.error("לא נמצאו סימני ההתחלה/סיום בחוברת.")
        except Exception as e: st.error(f"שגיאה: {e}")

if __name__ == "__main__":
    main()
