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

# --- פונקציות סריקה מקוונת (סריקה דרך עמוד קטגוריה) ---

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
    st.info("🛠️ יומן סריקה: סורק את עמוד הקטגוריה הראשי למציאת הגיליון העדכני...")
    
    # קריאת הנתונים השמורים (אופציונלי, כדי לדעת מה היה הגיליון הקודם)
    data = get_config()
    current_id = data.get("last_id", DEFAULT_START_ID)

    try:
        scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
        
        # שלב 1: כניסה לעמוד הקטגוריה הייעודי למשכן שילה
        category_url = "https://kav.meorot.net/category/%d7%a2%d7%9c%d7%95%d7%a0%d7%99-%d7%a9%d7%91%d7%aa/%d7%9e%d7%a9%d7%9b%d7%9f-%d7%a9%d7%99%d7%9c%d7%94/"
        st.write("🔍 מושך נתונים מעמוד הקטגוריה 'משכן שילה'...")
        
        cat_response = scraper.get(category_url)
        if cat_response.status_code != 200:
            st.error(f"❌ לא הצלחנו לגשת לעמוד הקטגוריה (קוד {cat_response.status_code}).")
            return None
            
        # חיפוש כל המספרים בלינקים שמובילים לפוסטים בעמוד זה
        post_ids = re.findall(r'kav\.meorot\.net/(\d+)/?', cat_response.text)
        
        if not post_ids:
            st.error("❌ לא מצאנו שום גיליון בעמוד הקטגוריה.")
            return None
            
        # הפיכה למספרים ובחירת המספר הגבוה ביותר (המעודכן ביותר)
        valid_ids = [int(pid) for pid in post_ids]
        highest_id = max(valid_ids)
        
        st.write(f"✅ המספר הגבוה ביותר שנמצא בקטגוריה הוא: {highest_id}")
        
        if highest_id > current_id:
            st.write(f"🆕 נמצא גיליון חדש! (הקודם ששמור במערכת היה {current_id})")
        else:
            st.write(f"🔄 מושך את הגיליון האחרון המוכר ({highest_id}).")

        # שלב 2: כניסה לפוסט הספציפי שנבחר ושליפת הדרייב
        target_url = f"https://kav.meorot.net/{highest_id}/"
        st.write(f"🔍 נכנס לדף הגיליון...")
        
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
                st.success(f"✅ נמצא מזהה קובץ (ID) במספר {highest_id}: {found_id}")
                
                # שמירת ה-ID החדש במסד הנתונים
                save_config({
                    "last_id": highest_id,
                    "found_date": datetime.datetime.now().isoformat()
                })
                
                return found_id
            else:
                st.error(f"⚠️ לא נמצא קישור לדרייב בדף {highest_id}.")
                return None
        else:
            st.error(f"❌ דף {highest_id} לא זמין (סטטוס {response.status_code}).")
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
        if not os.path.exists(START_IMG) or not os.path.exists(END_IMG):
            st.error("שגיאה: קבצי התמונות (start.png / end.png) חסרים.")
            return

        with st.spinner("מבצע תהליך שליפה וחיתוך..."):
            try:
                with open(START_IMG, "rb") as f: start_b64 = base64.b64encode(f.read())
                with open(END_IMG, "rb") as f: end_b64 = base64.b64encode(f.read())

                input_path = ""
                
                if upload_option == "העלאת קובץ מהמחשב":
                    if not uploaded_file:
                        st.warning("נא להעלות קובץ.")
                        return
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(uploaded_file.getvalue())
                        input_path = tmp.name
                
                elif upload_option == "קישור מ-Google Drive":
                    if not manual_link:
                        st.warning("נא להזין לינק.")
                        return
                    
                    file_id = None
                    id_match = re.search(r'/d/([a-zA-Z0-9_-]+)', manual_link)
                    if id_match:
                        file_id = id_match.group(1)
                    else:
                        st.warning("הקישור לא תקין או לא מכיל מזהה (ID).")
                        return
                        
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        input_path = tmp.name
                    gdown.download(id=file_id, output=input_path, quiet=False)

                elif upload_option == "שליפה אוטומטית (משכן שילה)":
                    file_id = get_latest_mishkan_shilo_drive_link()
                    if not file_id: 
                        return
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        input_path = tmp.name
                    
                    gdown.download(id=file_id, output=input_path, quiet=False)

                    file_size = os.path.getsize(input_path)
                    st.write(f"🔍 דיבוג: גודל הקובץ שהורד מגוגל הוא {file_size / 1024:.2f} KB")
                    
                    if file_size < 100000:
                        st.error("⚠️ הקובץ שהורד קטן מדי! נראה שגוגל דרייב חסם את ההורדה.")
                        return

                if input_path:
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
