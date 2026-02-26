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
from bs4 import BeautifulSoup

# --- הגדרות מערכת ---
DEFAULT_START_ID = 72680
AUTO_CUT_PDF = "auto_cut_document.pdf"
AUTO_CUT_BW_PDF = "auto_cut_document_bw.pdf" 

# --- פונקציות מסד נתונים וזמן ---

@st.cache_data(ttl=600) 
def get_config():
    """שולף את הנתונים ממסד הנתונים בענן (JSONBin)"""
    try:
        if 'JSONBIN_BIN_ID' in st.secrets and 'JSONBIN_API_KEY' in st.secrets:
            url = f"https://api.jsonbin.io/v3/b/{st.secrets['JSONBIN_BIN_ID']}"
            headers = {'X-Master-Key': st.secrets['JSONBIN_API_KEY']}
            req = requests.get(url, headers=headers)
            if req.status_code == 200:
                return req.json().get('record', {})
    except Exception as e:
        st.warning(f"שגיאה בקריאה ממסד הנתונים: {e}")
    return {}

def save_config(data):
    """שומר את הנתונים למסד הנתונים בענן ומנקה את זיכרון המטמון"""
    try:
        if 'JSONBIN_BIN_ID' in st.secrets and 'JSONBIN_API_KEY' in st.secrets:
            url = f"https://api.jsonbin.io/v3/b/{st.secrets['JSONBIN_BIN_ID']}"
            headers = {
                'Content-Type': 'application/json',
                'X-Master-Key': st.secrets['JSONBIN_API_KEY']
            }
            requests.put(url, json=data, headers=headers)
            get_config.clear() 
    except Exception as e:
        st.error(f"שגיאה בשמירה למסד הנתונים: {e}")

def get_next_saturday_1600(from_date):
    """מחשב מתי תחול השבת הקרובה בשעה 16:00"""
    days_ahead = 5 - from_date.weekday()
    if days_ahead < 0 or (days_ahead == 0 and from_date.hour >= 16):
        days_ahead += 7
    next_sat = from_date + datetime.timedelta(days=days_ahead)
    return next_sat.replace(hour=16, minute=0, second=0, microsecond=0)

# --- פונקציית האוטומציה המרכזית ---

def prepare_auto_pdf():
    """
    מנהל את הלוגיקה האוטומטית.
    מחזיר: (הצלחה?, הודעת_שגיאה, שם_הקובץ)
    """
    config = get_config()
    last_post_id = config.get("last_post_id", DEFAULT_START_ID)
    last_drive_id = config.get("last_drive_id", None)
    last_check_str = config.get("last_check_time")
    last_title = config.get("last_title", "גיליון משכן שילה") 

    now = datetime.datetime.now()
    should_scrape = False

    if not last_check_str:
        should_scrape = True
    else:
        last_check = datetime.datetime.fromisoformat(last_check_str)
        next_check = get_next_saturday_1600(last_check)
        if now >= next_check:
            should_scrape = True

    target_post_id = last_post_id
    target_drive_id = last_drive_id
    found_new = False

    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
    
    if should_scrape:
        cat_url = "https://kav.meorot.net/category/%d7%a2%d7%9c%d7%95%d7%a0%d7%99-%d7%a9%d7%91%d7%aa/%d7%9e%d7%a9%d7%9b%d7%9f-%d7%a9%d7%99%d7%9c%d7%94/"
        cat_res = scraper.get(cat_url)
        
        if cat_res.status_code == 200:
            soup = BeautifulSoup(cat_res.text, "html.parser")
            post_link = soup.select_one("h3 a, h2 a")
            
            if post_link:
                url = post_link["href"]
                id_match = re.search(r'kav\.meorot\.net/(\d+)', url)
                if id_match:
                    scraped_post_id = int(id_match.group(1))
                    
                    if scraped_post_id > last_post_id:
                        post_res = scraper.get(url)
                        if post_res.status_code == 200:
                            drive_patterns = [
                                r'https://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)', 
                                r'https%3A%2F%2Fdrive\.google\.com%2Ffile%2Fd%2F([a-zA-Z0-9_-]+)'
                            ]
                            for pattern in drive_patterns:
                                match = re.search(pattern, post_res.text)
                                if match:
                                    target_drive_id = match.group(1)
                                    target_post_id = scraped_post_id
                                    found_new = True
                                    break

    # החזרת הקובץ המוכן אם כבר נחתך ואין חדש באופק
    if not found_new and os.path.exists(AUTO_CUT_PDF):
        if not os.path.exists(AUTO_CUT_BW_PDF):
            convert_pdf_to_bw(AUTO_CUT_PDF, AUTO_CUT_BW_PDF)
        return True, None, last_title

    if not target_drive_id:
        post_res = scraper.get(f"https://kav.meorot.net/{target_post_id}/")
        if post_res.status_code == 200:
            drive_patterns = [r'https://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)', r'https%3A%2F%2Fdrive\.google\.com%2Ffile%2Fd%2F([a-zA-Z0-9_-]+)']
            for pattern in drive_patterns:
                match = re.search(pattern, post_res.text)
                if match:
                    target_drive_id = match.group(1)
                    break
                    
    if not target_drive_id:
        return False, "לא הצלחנו לאתר קישור תקין לגוגל דרייב בפוסט.", None

    downloaded_path = gdown.download(id=target_drive_id, quiet=False)
    
    if not downloaded_path:
        return False, "שגיאה בהורדת הקובץ מגוגל דרייב.", None

    original_filename = urllib.parse.unquote(os.path.basename(downloaded_path))

    if os.path.getsize(downloaded_path) < 100000:
        os.remove(downloaded_path)
        return False, "הקובץ שהורד קטן מדי! נראה שגוגל דרייב חסם את ההורדה.", None

    START_IMG, END_IMG = "start.png", "end.png"
    if not os.path.exists(START_IMG) or not os.path.exists(END_IMG):
        os.remove(downloaded_path)
        return False, "שגיאה: קבצי תמונות החיתוך חסרים בשרת.", None

    with open(START_IMG, "rb") as f: start_b64 = base64.b64encode(f.read())
    with open(END_IMG, "rb") as f: end_b64 = base64.b64encode(f.read())

    success = extract_pdf_by_images(downloaded_path, AUTO_CUT_PDF, start_b64, end_b64)
    os.remove(downloaded_path)

    if success:
        convert_pdf_to_bw(AUTO_CUT_PDF, AUTO_CUT_BW_PDF)
        
        if found_new or last_title != original_filename:
            save_config({
                "last_post_id": target_post_id,
                "last_drive_id": target_drive_id,
                "last_check_time": last_check_str if not found_new else now.isoformat(),
                "last_title": original_filename
            })
        return True, None, original_filename
    else:
        return False, "לא הצלחנו למצוא את סימני ההתחלה והסיום בתוך ה-PDF החדש.", None

# --- פונקציות לוגיקת החיתוך והמרה לשחור-לבן ---

def convert_pdf_to_bw(input_path, output_path):
    doc = fitz.open(input_path)
    bw_doc = fitz.open()
    for page in doc:
        pix = page.get_pixmap(colorspace=fitz.csGRAY, matrix=fitz.Matrix(2, 2))
        bw_page = bw_doc.new_page(width=page.rect.width, height=page.rect.height)
        bw_page.insert_image(page.rect, pixmap=pix)
    bw_doc.save(output_path)
    bw_doc.close()
    doc.close()

def find_image_in_page(page_pixmap, template_b64, threshold=0.7):
    img_array = np.frombuffer(page_pixmap.samples, dtype=np.uint8).reshape(page_pixmap.h, page_pixmap.w, page_pixmap.n)
    if page_pixmap.n >= 3:
        img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    img_data = base64.b64decode(template_b64)
    np_arr_template = np.frombuffer(img_data, np.uint8)
    template = cv2.imdecode(np_arr_template, cv2.IMREAD_GRAYSCALE)
    if template is None: return False
    for scale in np.linspace(0.4, 1.6, 12):
        width = int(template.shape[1] * scale)
        height = int(template.shape[0] * scale)
        if height == 0 or width == 0 or height > img_array.shape[0] or width > img_array.shape[1]: continue
        resized_template = cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(img_array, resized_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        if max_val >= threshold: return True
    return False

def extract_pdf_by_images(input_pdf_path, output_pdf_path, start_image_b64, end_image_b64):
    doc = fitz.open(input_pdf_path)
    start_page = -1
    end_page = -1
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

# --- ממשק משתמש ---

def main():
    st.set_page_config(page_title="הורדת סיכום פרשה - משכן שילה", page_icon="📄")
    st.markdown("<style>.block-container { direction: rtl; text-align: right; }</style>", unsafe_allow_html=True)
    
    st.markdown('<h1 style="text-align: center;">סיכום פרשת שבוע מגיליון "משכן שילה"</h1>', unsafe_allow_html=True)
    
    upload_option = st.radio("איך תרצה לטעון את ה-PDF?", 
                             ("שליפה אוטומטית (משכן שילה)", 
                              "העלאת קובץ מהמחשב", 
                              "קישור מ-Google Drive"))
    
    START_IMG, END_IMG = "start.png", "end.png"

    if upload_option == "שליפה אוטומטית (משכן שילה)":
        with st.spinner("מוודא ומכין את הגיליון העדכני ביותר..."):
            success, error_msg, target_title = prepare_auto_pdf()
        
        if success and os.path.exists(AUTO_CUT_PDF):
            st.success("✅ הקובץ מוכן עבורך!")
            
            safe_filename = re.sub(r'[\\/*?:"<>|]', "", target_title).strip()
            if not safe_filename.lower().endswith('.pdf'):
                safe_filename += ".pdf"
            
            safe_filename_bw = safe_filename.replace(".pdf", " - שחור לבן.pdf")
            display_title = safe_filename.replace(".pdf", "")
            
            # --- התיקון: הסרת המילה 'מגיליון' ---
            st.markdown(f'<h3 style="text-align: right; direction: rtl;">להורדת סיכום פרשת השבוע מ-"{display_title}"</h3>', unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
            
            with open(AUTO_CUT_PDF, "rb") as f_color:
                col1.download_button(
                    label="📥 פורמט צבעוני", 
                    data=f_color, 
                    file_name=safe_filename, 
                    mime="application/pdf",
                    use_container_width=True
                )
                
            if os.path.exists(AUTO_CUT_BW_PDF):
                with open(AUTO_CUT_BW_PDF, "rb") as f_bw:
                    col2.download_button(
                        label="🖨️ פורמט שחור לבן", 
                        data=f_bw, 
                        file_name=safe_filename_bw, 
                        mime="application/pdf",
                        use_container_width=True
                    )
        else:
            st.error(error_msg)

    else:
        uploaded_file = None
        manual_link = ""
        
        if upload_option == "העלאת קובץ מהמחשב":
            uploaded_file = st.file_uploader("בחר קובץ PDF מהמחשב", type=["pdf"], key="manual_upload")
        elif upload_option == "קישור מ-Google Drive":
            manual_link = st.text_input("הדבק כאן קישור שיתוף ל-PDF מ-Google Drive:")
            
        if st.button("הפעל חיתוך ידני"):
            if not os.path.exists(START_IMG) or not os.path.exists(END_IMG):
                st.error("שגיאה: קבצי התמונות (start.png / end.png) חסרים.")
                return

            with st.spinner("מבצע משיכה וחיתוך..."):
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
                        
                        output_path = input_path.replace(".pdf", "_fixed.pdf")
                        output_bw_path = input_path.replace(".pdf", "_fixed_bw.pdf")
                        
                        if extract_pdf_by_images(input_path, output_path, start_b64, end_b64):
                            convert_pdf_to_bw(output_path, output_bw_path) 
                            st.success("החיתוך בוצע בהצלחה!")
                            
                            safe_manual_name = uploaded_file.name
                            if not safe_manual_name.lower().endswith('.pdf'):
                                safe_manual_name += ".pdf"
                            safe_manual_name = safe_manual_name.replace(".pdf", "_fixed.pdf")
                            safe_manual_name_bw = safe_manual_name.replace(".pdf", " - שחור לבן.pdf")
                            display_manual_title = safe_manual_name.replace(".pdf", "")
                            
                            # --- התיקון למצב הידני ---
                            st.markdown(f'<h3 style="text-align: right; direction: rtl;">להורדת סיכום פרשת השבוע מ-"{display_manual_title}"</h3>', unsafe_allow_html=True)
                            col1, col2 = st.columns(2)
                                
                            with open(output_path, "rb") as f_color:
                                col1.download_button("📥 פורמט צבעוני", f_color, safe_manual_name, "application/pdf", use_container_width=True)
                            with open(output_bw_path, "rb") as f_bw:
                                col2.download_button("🖨️ פורמט שחור לבן", f_bw, safe_manual_name_bw, "application/pdf", use_container_width=True)
                        else:
                            st.error("לא הצלחנו למצוא את סימני ההתחלה והסיום בתוך הקובץ.")
                    
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
                            
                        downloaded_path = gdown.download(id=file_id, quiet=False)
                        if downloaded_path:
                            original_filename = urllib.parse.unquote(os.path.basename(downloaded_path))
                            
                            safe_manual_name = re.sub(r'[\\/*?:"<>|]', "", original_filename).strip()
                            if safe_manual_name.lower().endswith('.pdf'):
                                safe_manual_name = safe_manual_name.replace(".pdf", "_fixed.pdf")
                            else:
                                safe_manual_name += "_fixed.pdf"
                                
                            safe_manual_name_bw = safe_manual_name.replace(".pdf", " - שחור לבן.pdf")
                            display_manual_title = safe_manual_name.replace(".pdf", "")
                            
                            output_path = "temp_fixed.pdf"
                            output_bw_path = "temp_fixed_bw.pdf"
                            
                            if extract_pdf_by_images(downloaded_path, output_path, start_b64, end_b64):
                                convert_pdf_to_bw(output_path, output_bw_path) 
                                st.success("החיתוך בוצע בהצלחה!")
                                
                                # --- התיקון למצב הלינק מהדרייב ---
                                st.markdown(f'<h3 style="text-align: right; direction: rtl;">להורדת סיכום פרשת השבוע מ-"{display_manual_title}"</h3>', unsafe_allow_html=True)
                                col1, col2 = st.columns(2)
                                
                                with open(output_path, "rb") as f_color:
                                    col1.download_button("📥 פורמט צבעוני", f_color, safe_manual_name, "application/pdf", use_container_width=True)
                                with open(output_bw_path, "rb") as f_bw:
                                    col2.download_button("🖨️ פורמט שחור לבן", f_bw, safe_manual_name_bw, "application/pdf", use_container_width=True)
                            else:
                                st.error("לא הצלחנו למצוא את סימני ההתחלה והסיום בתוך הקובץ.")
                            os.remove(downloaded_path)
                        else:
                            st.error("לא הצלחנו להוריד את הקובץ מהלינק שסופק.")
                
                except Exception as e:
                    st.error(f"אירעה שגיאה: {e}")

if __name__ == "__main__":
    main()
