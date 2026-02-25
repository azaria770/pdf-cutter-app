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

# --- פונקציות סריקה (לוגיקה מעודכנת לזיהוי קישורי טקסט+מספר) ---

CATEGORY_URL = "https://kav.meorot.net/category/%d7%a2%d7%9c%d7%95%d7%a0%d7%99-%d7%a9%d7%91%d7%aa/%d7%9e%d7%a9%d7%9b%d7%9f-%d7%a9%d7%99%d7%9c%d7%94/"

def get_latest_mishkan_shilo_drive_link():
    """
    סורק את דף הקטגוריה, מוצא את הקישור לפוסט האחרון (לפי המספר ב-URL)
    ואז נכנס לפוסט כדי למצוא את הדרייב.
    """
    st.info("🌐 מתחבר לדף הקטגוריה של 'משכן שילה'...")
    
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'}

    try:
        response = scraper.get(CATEGORY_URL, headers=headers, timeout=20)
        if response.status_code != 200:
            st.error(f"❌ חסימה בדף הקטגוריה (קוד {response.status_code})")
            return None
        
        # חיפוש קישורים שמכילים מספרים (למשל mishkan-shilo-72418)
        # Regex משופר שתופס את הנתיב המלא ואת המספר המזהה בסופו
        all_links = re.findall(r'href="https://kav\.meorot\.net/([^"]+?(\d+)/?)"', response.text)
        
        if not all_links:
            st.error("❌ לא נמצאו קישורי פוסטים בדף הקטגוריה.")
            return None
        
        # בניית מפה של מזהה פוסט לכתובת מלאה
        post_ids = []
        url_map = {}
        for full_path, p_id in all_links:
            p_id_int = int(p_id)
            post_ids.append(p_id_int)
            url_map[p_id_int] = f"https://kav.meorot.net/{full_path}"

        # בחירת הפוסט עם המספר הגבוה ביותר
        latest_id = max(post_ids)
        latest_url = url_map[latest_id]
        
        st.write(f"📄 נמצא פוסט עדכני (מזהה: {latest_id}). שולף נתונים...")

        # שלב ב': כניסה לפוסט ומציאת הדרייב
        time.sleep(1)
        post_response = scraper.get(latest_url, headers=headers, timeout=20)
        html = post_response.text
        
        # חיפוש לינק דרייב (כולל בתוך iframe או תמונה מקודדת)
        drive_links = re.findall(r'drive\.google\.com(?:%2F|/)file(?:%2F|/)d(?:%2F|/)([a-zA-Z0-9_-]{20,})', html)
        
        if drive_links:
            file_id = drive_links[0]
            found_url = f"https://drive.google.com/file/d/{file_id}"
            st.success(f"✅ נמצא קישור לקובץ הדרייב!")
            return found_url
        else:
            st.error(f"❌ לא נמצא קישור גוגל דרייב בתוך הפוסט {latest_id}.")
            return None

    except Exception as e:
        st.error(f"❌ שגיאה בתהליך השליפה: {e}")
        return None

# --- פונקציות לוגיקה (ללא שינוי) ---

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
        if cv2.minMaxLoc(result)[1] >= threshold:
            return True
    return False

def extract_pdf_by_images(input_pdf_path, output_pdf_path, start_image_b64, end_image_b64):
    doc = fitz.open(input_pdf_path)
    start_page, end_page = -1, -1

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2))
        if start_page == -1:
            if find_image_in_page(pix, start_image_b64): start_page = page_num
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

# --- ממשק משתמש (Streamlit) ---

def main():
    st.set_page_config(page_title="חותך PDF אוטומטי", page_icon="✂️")
    st.markdown("<style>.block-container { direction: rtl; text-align: right; }</style>", unsafe_allow_html=True)
    st.title("✂️ חותך משכן שילה אוטומטי")
    
    upload_option = st.radio("בחר מקור:", 
                             ("שליפה אוטומטית (מהאתר)", 
                              "העלאת קובץ ידנית", 
                              "קישור דרייב ידני"))
    
    START_IMG, END_IMG = "start.png", "end.png"

    if st.button("הפעל"):
        if not os.path.exists(START_IMG) or not os.path.exists(END_IMG):
            st.error("קבצי התמונות (start.png / end.png) חסרים בשרת.")
            return

        with st.spinner("מעבד נתונים..."):
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
                    file = st.file_uploader("בחר קובץ PDF", type=["pdf"])
                    if not file: return
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(file.getvalue())
                        input_path = tmp.name
                
                else:
                    manual_link = st.text_input("הדבק קישור גוגל דרייב:")
                    if not manual_link: return
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp: input_path = tmp.name
                    gdown.download(url=manual_link, output=input_path, quiet=False, fuzzy=True)

                if input_path and os.path.exists(input_path):
                    output_path = input_path.replace(".pdf", "_fixed.pdf")
                    if extract_pdf_by_images(input_path, output_path, start_b64, end_b64):
                        st.success("החיתוך בוצע בהצלחה!")
                        with open(output_path, "rb") as f:
                            st.download_button("📥 הורד קובץ חתוך", f, "mishkan_shilo_cut.pdf", "application/pdf")
                    else:
                        st.error("לא נמצאו סימני החיתוך בתוך החוברת.")
            except Exception as e:
                st.error(f"אירעה שגיאה: {e}")

if __name__ == "__main__":
    main()
