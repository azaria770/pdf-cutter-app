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
import subprocess

# --- הגדרות מערכת ---
DEFAULT_START_ID = 72680
AUTO_REGULAR_PDF = "auto_regular_document.pdf"
AUTO_REGULAR_BW_PDF = "auto_regular_document_bw.pdf" 
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

    if not found_new and os.path.exists(AUTO_REGULAR_PDF):
        if not os.path.exists(AUTO_REGULAR_BW_PDF): convert_pdf_to_bw(AUTO_REGULAR_PDF, AUTO_REGULAR_BW_PDF)
        if not os.path.exists(AUTO_CUT_PDF): split_pdf_to_columns(AUTO_REGULAR_PDF, AUTO_CUT_PDF)
        if not os.path.exists(AUTO_CUT_BW_PDF): convert_pdf_to_bw(AUTO_CUT_PDF, AUTO_CUT_BW_PDF)
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
        if os.path.exists(downloaded_path): os.remove(downloaded_path)
        return False, "הקובץ שהורד קטן מדי! נראה שגוגל דרייב חסם את ההורדה.", None

    START_IMG, END_IMG = "start.png", "end.png"
    if not os.path.exists(START_IMG) or not os.path.exists(END_IMG):
        if os.path.exists(downloaded_path): os.remove(downloaded_path)
        return False, "שגיאה: קבצי תמונות החיתוך חסרים בשרת.", None

    with open(START_IMG, "rb") as f: start_b64 = base64.b64encode(f.read())
    with open(END_IMG, "rb") as f: end_b64 = base64.b64encode(f.read())

    success = extract_pdf_by_images(downloaded_path, AUTO_REGULAR_PDF, start_b64, end_b64)
    if os.path.exists(downloaded_path): os.remove(downloaded_path)

    if success:
        convert_pdf_to_bw(AUTO_REGULAR_PDF, AUTO_REGULAR_BW_PDF)
        split_pdf_to_columns(AUTO_REGULAR_PDF, AUTO_CUT_PDF)
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

# --- פונקציות עיבוד תצוגה וממשק מתקדם ---

def display_pdf(file_path):
    with open(file_path, "rb") as f:
        base64_pdf = base64.b64encode(f.read()).decode('utf-8')
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800px" type="application/pdf" style="border: 1px solid #ccc; border-radius: 8px;"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)

def render_download_view_ui(base_filename, regular_color, regular_bw, cut_color, cut_bw, key_prefix):
    if f"{key_prefix}_format" not in st.session_state:
        st.session_state[f"{key_prefix}_format"] = None
    if f"{key_prefix}_layout" not in st.session_state:
        st.session_state[f"{key_prefix}_layout"] = None

    st.write("### 1. בחר פורמט צבע:")
    col1, col2 = st.columns(2)
    
    if col1.button("🎨 צבעוני", use_container_width=True, key=f"{key_prefix}_btn_color"):
        st.session_state[f"{key_prefix}_format"] = "color"
        st.session_state[f"{key_prefix}_layout"] = None
    
    if col2.button("🖨️ שחור לבן", use_container_width=True, key=f"{key_prefix}_btn_bw"):
        st.session_state[f"{key_prefix}_format"] = "bw"
        st.session_state[f"{key_prefix}_layout"] = None

    fmt = st.session_state[f"{key_prefix}_format"]
    
    if fmt:
        st.write("### 2. בחר פריסה:")
        layout_col1, layout_col2 = st.columns(2)
        
        if layout_col1.button("📄 מסמך רגיל", use_container_width=True, key=f"{key_prefix}_btn_reg"):
            st.session_state[f"{key_prefix}_layout"] = "regular"
        
        if layout_col2.button("✂️ חתוך לטורים (לקריאה דיגיטלית)", use_container_width=True, key=f"{key_prefix}_btn_cut"):
            st.session_state[f"{key_prefix}_layout"] = "cut"

        lyt = st.session_state[f"{key_prefix}_layout"]
        if lyt:
            if fmt == "color" and lyt == "regular":
                target_file = regular_color
                dl_name = base_filename
            elif fmt == "bw" and lyt == "regular":
                target_file = regular_bw
                dl_name = base_filename.replace(".pdf", " - שחור לבן.pdf")
            elif fmt == "color" and lyt == "cut":
                target_file = cut_color
                dl_name = base_filename.replace(".pdf", " - חתוך לטורים.pdf")
            elif fmt == "bw" and lyt == "cut":
                target_file = cut_bw
                dl_name = base_filename.replace(".pdf", " - שחור לבן - חתוך לטורים.pdf")

            if os.path.exists(target_file):
                st.write("### 3. בחר פעולה:")
                act_col1, act_col2 = st.columns(2)
                with open(target_file, "rb") as f:
                    act_col1.download_button("📥 הורד קובץ", f, dl_name, "application/pdf", use_container_width=True, key=f"{key_prefix}_btn_dl")
                if act_col2.button("👁️ תצוגה באתר", use_container_width=True, key=f"{key_prefix}_btn_view"):
                    display_pdf(target_file)
            else:
                st.error("הקובץ המבוקש נוצר עם שגיאה או אינו קיים.")


def split_pdf_to_columns(input_pdf_path, output_pdf_path):
    """
    מפצל PDF ל-3 טורים. משייך בלוקים (טקסט/תמונה) לטור הרלוונטי, מוחק בלוקים שזלגו מטורים שכנים בלבן (טיפקס),
    ולבסוף חותך פיזית (Cropbox) את העמוד כך שיוצג אך ורק הטור עצמו ללא השוליים הלבנים של שאר העמוד.
    """
    doc = fitz.open(input_pdf_path)
    out_doc = fitz.open()

    for page_num in range(len(doc)):
        page = doc[page_num]
        width = page.rect.width
        height = page.rect.height

        # חילוץ כל הבלוקים (טקסט ותמונות) בעמוד
        page_dict = page.get_text("dict")
        blocks = page_dict.get("blocks", [])

        if not blocks:
            continue

        # 1. סיווג כל בלוק לטור שלו לפי מרכז הכובד האופקי
        block_assignments = []
        for b in blocks:
            b_bbox = b["bbox"]
            b_width = b_bbox[2] - b_bbox[0]
            b_cx = (b_bbox[0] + b_bbox[2]) / 2

            # כותרות או קווים שחוצים את רוב העמוד - נשייך לכל הטורים
            if b_width > width * 0.75:
                target_cols = [0, 1, 2]
            else:
                if b_cx >= width * 0.63:
                    target_cols = [0] # ימין
                elif b_cx >= width * 0.33:
                    target_cols = [1] # אמצע
                else:
                    target_cols = [2] # שמאל
            
            block_assignments.append({"block": b, "cols": target_cols})

        # 2. יצירת 3 עמודים חדשים (אחד לכל טור)
        for col_idx in [0, 1, 2]:
            # המערכים הללו יאספו את הקואורדינטות המדויקות לחישוב גודל הטור
            valid_bboxes = [] # כל מה שיוצג (כולל כותרות משותפות)
            core_bboxes = []  # טקסט ששייך *רק* לטור הזה (כדי לאמוד נכון את רוחב הטור ללא כותרות ענק)

            for item in block_assignments:
                b = item["block"]
                cols = item["cols"]
                
                if col_idx in cols:
                    if b["type"] == 0: # טקסט
                        for line in b.get("lines", []):
                            valid_bboxes.append(line["bbox"])
                            if len(cols) == 1:
                                core_bboxes.append(line["bbox"])
                    elif b["type"] == 1: # תמונה
                        valid_bboxes.append(b["bbox"])
                        if len(cols) == 1:
                            core_bboxes.append(b["bbox"])

            if not valid_bboxes:
                continue # אין תוכן בטור הזה, מדלגים עליו
            
            # מעתיקים את העמוד בשלמותו
            new_page = out_doc.new_page(width=width, height=height)
            new_page.show_pdf_page(new_page.rect, doc, page_num)
            
            # 3. "טיפקס וירטואלי": מחיקת הטורים הלא רלוונטיים באמצעות ציור מלבנים לבנים
            for item in block_assignments:
                b = item["block"]
                cols = item["cols"]
                
                if col_idx not in cols:
                    # הבלוק הזה שייך לטור אחר - נמחק אותו
                    if b["type"] == 0: # טקסט
                        for line in b.get("lines", []):
                            l_bbox = line["bbox"]
                            # שוליים של 3 פיקסלים להבטיח מחיקת ניקוד שזלג
                            erase_rect = fitz.Rect(l_bbox[0]-3, l_bbox[1]-3, l_bbox[2]+3, l_bbox[3]+3)
                            new_page.draw_rect(erase_rect, color=(1,1,1), fill=(1,1,1))
                    elif b["type"] == 1: # תמונה
                        i_bbox = b["bbox"]
                        erase_rect = fitz.Rect(i_bbox[0]-3, i_bbox[1]-3, i_bbox[2]+3, i_bbox[3]+3)
                        new_page.draw_rect(erase_rect, color=(1,1,1), fill=(1,1,1))
            
            # 4. חיתוך פיזי של העמוד (כדי שלא יוצג הלבן של הטורים האחרים)
            # את הגובה נחשב לפי כל התוכן (כולל כותרות משותפות כדי לא לגזום אותן)
            min_y = min([box[1] for box in valid_bboxes])
            max_y = max([box[3] for box in valid_bboxes])
            
            # את הרוחב נחשב *רק* לפי הבלוקים הייחודיים לטור (core_bboxes) כדי שהכותרת לא תרחיב את הטור על פני כל העמוד
            if core_bboxes:
                min_x = min([box[0] for box in core_bboxes])
                max_x = max([box[2] for box in core_bboxes])
            else:
                min_x = min([box[0] for box in valid_bboxes])
                max_x = max([box[2] for box in valid_bboxes])
                
            pad_x = 10
            pad_y = 15
            
            crop_rect = fitz.Rect(
                max(0, min_x - pad_x),
                max(0, min_y - pad_y),
                min(width, max_x + pad_x),
                min(height, max_y + pad_y)
            )
            
            # ביצוע החיתוך הפיזי על המידות המדויקות של הטור
            if crop_rect.width > 20 and crop_rect.height > 20:
                new_page.set_cropbox(crop_rect)
                new_page.set_mediabox(crop_rect)
            else:
                out_doc.delete_page(-1)

    out_doc.save(output_pdf_path)
    out_doc.close()
    doc.close()


def convert_pdf_to_bw(input_path, output_path):
    gs_cmd = [
        "gs",
        "-sOutputFile=" + output_path,
        "-sDEVICE=pdfwrite",
        "-sColorConversionStrategy=Gray",
        "-dProcessColorModel=/DeviceGray",
        "-dCompatibilityLevel=1.4",
        "-dNOPAUSE",
        "-dBATCH",
        "-dQUIET",
        input_path
    ]
    try:
        subprocess.run(gs_cmd, check=True)
    except Exception as e:
        import shutil
        shutil.copy(input_path, output_path)
        print(f"Ghostscript error: {e}")

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
    
    if "prev_upload_option" not in st.session_state:
        st.session_state.prev_upload_option = None

    upload_option = st.radio("איך תרצה לטעון את ה-PDF?", 
                             ("שליפה אוטומטית (משכן שילה)", 
                              "העלאת קובץ מהמחשב", 
                              "קישור מ-Google Drive"))
    
    if st.session_state.prev_upload_option != upload_option:
        st.session_state.prev_upload_option = upload_option
        if "manual_files" in st.session_state:
            del st.session_state["manual_files"]
    
    START_IMG, END_IMG = "start.png", "end.png"

    if upload_option == "שליפה אוטומטית (משכן שילה)":
        with st.spinner("מוודא ומכין את הגיליון העדכני ביותר..."):
            success, error_msg, target_title = prepare_auto_pdf()
        
        if success and os.path.exists(AUTO_REGULAR_PDF):
            st.success("✅ הקובץ מוכן עבורך!")
            
            safe_filename = re.sub(r'[\\/*?:"<>|]', "", target_title).strip()
            if not safe_filename.lower().endswith('.pdf'):
                safe_filename += ".pdf"
            
            display_title = safe_filename.replace(".pdf", "")
            st.markdown(f'<h3 style="text-align: right; direction: rtl;">ניהול מסמך מ-"{display_title}"</h3>', unsafe_allow_html=True)
            
            render_download_view_ui(
                base_filename=safe_filename,
                regular_color=AUTO_REGULAR_PDF,
                regular_bw=AUTO_REGULAR_BW_PDF,
                cut_color=AUTO_CUT_PDF,
                cut_bw=AUTO_CUT_BW_PDF,
                key_prefix="auto"
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
            
        if st.button("הפעל חיתוך ועיבוד ידני"):
            if not os.path.exists(START_IMG) or not os.path.exists(END_IMG):
                st.error("שגיאה: קבצי התמונות (start.png / end.png) חסרים.")
                return

            with st.spinner("מבצע משיכה, חיתוך והכנת הטורים..."):
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
                        
                        output_regular = input_path.replace(".pdf", "_regular.pdf")
                        output_regular_bw = input_path.replace(".pdf", "_regular_bw.pdf")
                        output_cut = input_path.replace(".pdf", "_cut.pdf")
                        output_cut_bw = input_path.replace(".pdf", "_cut_bw.pdf")
                        
                        if extract_pdf_by_images(input_path, output_regular, start_b64, end_b64):
                            convert_pdf_to_bw(output_regular, output_regular_bw)
                            split_pdf_to_columns(output_regular, output_cut)
                            convert_pdf_to_bw(output_cut, output_cut_bw)
                            
                            safe_manual_name = uploaded_file.name
                            if not safe_manual_name.lower().endswith('.pdf'):
                                safe_manual_name += ".pdf"
                            safe_manual_name = safe_manual_name.replace(".pdf", "_fixed.pdf")
                            
                            st.session_state["manual_files"] = {
                                "reg_col": output_regular,
                                "reg_bw": output_regular_bw,
                                "cut_col": output_cut,
                                "cut_bw": output_cut_bw,
                                "base_name": safe_manual_name
                            }
                            st.success("העיבוד בוצע בהצלחה!")
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
                            
                            output_regular = "temp_regular_drive.pdf"
                            output_regular_bw = "temp_regular_bw_drive.pdf"
                            output_cut = "temp_cut_drive.pdf"
                            output_cut_bw = "temp_cut_bw_drive.pdf"
                            
                            if extract_pdf_by_images(downloaded_path, output_regular, start_b64, end_b64):
                                convert_pdf_to_bw(output_regular, output_regular_bw)
                                split_pdf_to_columns(output_regular, output_cut)
                                convert_pdf_to_bw(output_cut, output_cut_bw)
                                
                                st.session_state["manual_files"] = {
                                    "reg_col": output_regular,
                                    "reg_bw": output_regular_bw,
                                    "cut_col": output_cut,
                                    "cut_bw": output_cut_bw,
                                    "base_name": safe_manual_name
                                }
                                st.success("העיבוד בוצע בהצלחה!")
                            else:
                                st.error("לא הצלחנו למצוא את סימני ההתחלה והסיום בתוך הקובץ.")
                            if os.path.exists(downloaded_path): os.remove(downloaded_path)
                        else:
                            st.error("לא הצלחנו להוריד את הקובץ מהלינק שסופק.")
                
                except Exception as e:
                    st.error(f"אירעה שגיאה: {e}")

        if "manual_files" in st.session_state:
            f = st.session_state["manual_files"]
            display_manual_title = f["base_name"].replace(".pdf", "")
            st.markdown(f'<h3 style="text-align: right; direction: rtl;">ניהול מסמך מ-"{display_manual_title}"</h3>', unsafe_allow_html=True)
            
            render_download_view_ui(
                base_filename=f["base_name"],
                regular_color=f["reg_col"],
                regular_bw=f["reg_bw"],
                cut_color=f["cut_col"],
                cut_bw=f["cut_bw"],
                key_prefix="manual"
            )

if __name__ == "__main__":
    main()
