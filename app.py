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

# --- פונקציות סריקה מקוונת ---

CONFIG_FILE = "config.json"
DEFAULT_START_ID = 72680

def get_latest_mishkan_shilo_drive_link():
    """
    סורק דפים ומחפש לינק לדרייב. במקום להחזיר לינק מלא, נחזיר רק את ה-ID.
    """
    st.info("🛠️ יומן סריקה: מחפש קישור גוגל דרייב בקוד הדף...")
    
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
            st.write(f"🔍 סורק את {test_url}...")
            
            response = scraper.get(test_url)
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
                        found_id = match.group(1) # לוקחים רק את ה-ID, לא את כל הלינק
                        break
                
                if found_id:
                    st.success(f"✅ נמצא מזהה קובץ (ID): {found_id}")
                    
                    with open(CONFIG_FILE, "w") as f:
                        json.dump({"last_id": test_id}, f)
                    
                    return found_id
                else:
                    st.write(f"   ⚠️ לא נמצא קישור לדרייב בדף {test_id}.")
            else:
                st.write(f"   ❌ דף {test_id} לא זמין (סטטוס {response.status_code}).")
                
        return None
    except Exception as e:
        st.error(f"❌ שגיאה בסריקה: {e}")
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
    
    START_IMG, END_IMG = "start.png", "end.png"

    if st.button("הפעל חיתוך אוטומטי"):
        if not os.path.exists(START_IMG) or not os.path.exists(END_IMG):
            st.error("שגיאה: קבצי התמונות (start.png / end.png) חסרים.")
            return

        with st.spinner("מבצע תהליך שליפה וחיתוך..."):
            try:
                with open(START_IMG, "rb") as f: start_b64 = base64.b64encode(f.read())
                with open(END_IMG, "rb") as f: end_b64 = base64.b64encode(f.read())

                input_path = ""
                
                if upload_option == "העלאת קובץ מהמחשב":
                    uploaded_file = st.file_uploader("בחר קובץ", type=["pdf"], key="manual_upload")
                    if not uploaded_file:
                        st.warning("נא להעלות קובץ.")
                        return
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(uploaded_file.getvalue())
                        input_path = tmp.name
                else:
                    file_id = None
                    if upload_option == "שליפה אוטומטית (משכן שילה)":
                        file_id = get_latest_mishkan_shilo_drive_link()
                    else: 
                        manual_link = st.text_input("הדבק כאן קישור שיתוף ל-PDF מ-Google Drive:")
                        if manual_link:
                            # חילוץ ה-ID מהלינק הידני
                            id_match = re.search(r'/d/([a-zA-Z0-9_-]+)', manual_link)
                            if id_match:
                                file_id = id_match.group(1)
                    
                    if not file_id: 
                        st.warning("לא נמצא מזהה קובץ תקין להורדה.")
                        return
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        input_path = tmp.name
                    
                    # הורדה ישירה לפי ID (עוקף דפי HTML של גוגל)
                    gdown.download(id=file_id, output=input_path, quiet=False)

                    # --- שורת הדיבוג החדשה ---
                    file_size = os.path.getsize(input_path)
                    st.write(f"🔍 דיבוג: גודל הקובץ שהורד מגוגל הוא {file_size / 1024:.2f} KB")
                    
                    if file_size < 100000: # קובץ ששוקל פחות מ-100KB הוא כנראה לא העלון
                        st.error("⚠️ הקובץ שהורד קטן מדי! נראה שגוגל דרייב חסם את ההורדה האוטומטית והחזיר דף שגיאה/אזהרה במקום את ה-PDF האמיתי.")
                        return

                output_path = input_path.replace(".pdf", "_fixed.pdf")
                if extract_pdf_by_images(input_path, output_path, start_b64, end_b64):
                    st.success("החיתוך בוצע בהצלחה!")
                    with open(output_path, "rb") as f:
                        st.download_button("📥 הורד קובץ חתוך", f, "cut_document.pdf", "application/pdf")
                else:
                    st.error("לא הצלחנו למצוא את סימני ההתחלה והסיום בתוך הקובץ.")
            
            except Exception as e:
                st.error(f"אירעה שגיאה: {e}")

if __name__ == "__main__":
    main()
