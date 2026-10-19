import fitz  # PyMuPDF
import cv2
import numpy as np
import os
import base64
import tempfile
import streamlit as st
import gdown
import re
import json
import urllib.parse
import datetime
import requests 
from bs4 import BeautifulSoup
import subprocess
import logging

logger = logging.getLogger(__name__)

# מונע מ-OpenCV לפתוח תהליכים מקבילים שגורמים ל-Segmentation fault בשרתים מוגבלים
cv2.setNumThreads(1)

# --- הגדרות מערכת ---
SOURCE_URL = (
    "https://sites.google.com/view/mishkan-shilo/"
    "%D7%A2%D7%9E%D7%95%D7%AA%D7%AA-%D7%9E%D7%A9%D7%9B%D7%9F-%D7%A9%D7%99%D7%9C%D7%94"
)
AUTO_REGULAR_PDF = "auto_regular_document.pdf"
AUTO_REGULAR_BW_PDF = "auto_regular_document_bw.pdf" 
REQUEST_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 120
# start_v2.png מתאים לעיצוב הכותרת שהתחיל בתשפ"ז; start.png נשאר עבור גיליונות ישנים
START_IMAGES = ("start.png", "start_v2.png")
END_IMAGE = "end.png"
FULL_RENDER_SCALE = 1.2
COARSE_RENDER_SCALE = FULL_RENDER_SCALE / 2
# סף מקל לסריקה המהירה כדי לא לפספס עמודי סמן; ההכרעה נעשית ברזולוציה מלאה
COARSE_THRESHOLD = 0.65

# --- פונקציות מסד נתונים וזמן ---

@st.cache_data(ttl=600) 
def get_config():
    """שולף את הנתונים ממסד הנתונים בענן (JSONBin)"""
    try:
        if 'JSONBIN_BIN_ID' in st.secrets and 'JSONBIN_API_KEY' in st.secrets:
            url = f"https://api.jsonbin.io/v3/b/{st.secrets['JSONBIN_BIN_ID']}"
            headers = {'X-Master-Key': st.secrets['JSONBIN_API_KEY']}
            req = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
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
            requests.put(url, json=data, headers=headers, timeout=REQUEST_TIMEOUT)
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

def fetch_latest_drive_id():
    """שולף את קישור הגיליון בעל המספר הגבוה ביותר, ומדלג על קישורי התפריט."""
    response = requests.get(SOURCE_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    latest_issue, latest_drive_id = -1, None
    for link in soup.select("a[href]"):
        url = urllib.parse.urlparse(link["href"])
        if url.hostname != "drive.google.com":
            continue
        drive_match = re.fullmatch(r"/file/d/([a-zA-Z0-9_-]+)(?:/view|/preview)?/?", url.path)
        issue_match = re.search(r"גיליון משכן שילה\s+(\d+)", link.get_text(" ", strip=True))
        if drive_match and issue_match and int(issue_match.group(1)) > latest_issue:
            latest_issue, latest_drive_id = int(issue_match.group(1)), drive_match.group(1)
    if latest_drive_id:
        return latest_drive_id
    raise ValueError("לא נמצא קישור תקין לגיליון בעמוד משכן שילה.")


def _download_drive_file_direct(file_id):
    """הורדה ישירה מ-drive.usercontent, כולל מעבר על דף אישור סריקת הווירוסים."""
    with requests.Session() as sess:
        res = sess.get(
            "https://drive.usercontent.google.com/download",
            params={"id": file_id, "export": "download", "confirm": "t"},
            stream=True, timeout=DOWNLOAD_TIMEOUT,
        )
        res.raise_for_status()
        if "text/html" in res.headers.get("Content-Type", ""):
            form = BeautifulSoup(res.text, "html.parser").find("form", id="download-form")
            if not form or not form.get("action"):
                raise ValueError("גוגל דרייב חסם את ההורדה (ייתכן שהקובץ אינו משותף לציבור או שחרג ממכסת ההורדות).")
            params = {i["name"]: i.get("value", "") for i in form.find_all("input") if i.get("name")}
            res = sess.get(form["action"], params=params, stream=True, timeout=DOWNLOAD_TIMEOUT)
            res.raise_for_status()
            if "text/html" in res.headers.get("Content-Type", ""):
                raise ValueError("גוגל דרייב חסם את ההורדה (ייתכן שחרג ממכסת ההורדות).")

        disposition = res.headers.get("Content-Disposition", "")
        name_match = (re.search(r"filename\*=UTF-8''([^;]+)", disposition)
                      or re.search(r'filename="([^"]+)"', disposition))
        filename = os.path.basename(urllib.parse.unquote(name_match.group(1))) if name_match else ""
        path = os.path.join(tempfile.mkdtemp(), filename or f"{file_id}.pdf")
        with open(path, "wb") as f:
            for chunk in res.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    return path


def download_drive_file(file_id):
    """מוריד קובץ מגוגל דרייב בעזרת gdown, עם מעבר להורדה ישירה אם gdown נכשל."""
    try:
        path = gdown.download(id=file_id, quiet=False, timeout=DOWNLOAD_TIMEOUT)
        if path:
            return path
    except gdown.exceptions.FileURLRetrievalError:
        logger.warning("gdown failed for %s, falling back to direct download", file_id, exc_info=True)
    return _download_drive_file_direct(file_id)


def prepare_auto_pdf():
    config = get_config()
    last_drive_id = config.get("last_drive_id", None)
    last_check_str = config.get("last_check_time")
    last_title = config.get("last_title", "גיליון משכן שילה") 
    source_changed = config.get("source_url") != SOURCE_URL

    now = datetime.datetime.now()
    should_scrape = False

    if source_changed or not last_drive_id or not os.path.exists(AUTO_REGULAR_PDF) or not last_check_str:
        should_scrape = True
    else:
        last_check = datetime.datetime.fromisoformat(last_check_str)
        next_check = get_next_saturday_1600(last_check)
        if now >= next_check:
            should_scrape = True

    target_drive_id = last_drive_id
    found_new = False

    if should_scrape:
        try:
            target_drive_id = fetch_latest_drive_id()
        except (requests.RequestException, ValueError) as e:
            return False, f"שגיאה בשליפת הגיליון מאתר משכן שילה: {e}", None
        found_new = source_changed or target_drive_id != last_drive_id
        last_check_str = now.isoformat()

    if not found_new and os.path.exists(AUTO_REGULAR_PDF):
        if not os.path.exists(AUTO_REGULAR_BW_PDF): convert_pdf_to_bw(AUTO_REGULAR_PDF, AUTO_REGULAR_BW_PDF)
        if should_scrape:
            save_config({
                **config,
                "source_url": SOURCE_URL,
                "last_check_time": last_check_str
            })
        return True, None, last_title

    if not target_drive_id:
        return False, "לא הצלחנו לאתר קישור תקין לגוגל דרייב בעמוד משכן שילה.", None

    downloaded_path = None
    try:
        try:
            downloaded_path = download_drive_file(target_drive_id)
        except (requests.RequestException, ValueError) as e:
            return False, f"שגיאה בהורדת הקובץ מגוגל דרייב: {e}", None

        if not downloaded_path:
            return False, "שגיאה בהורדת הקובץ מגוגל דרייב.", None

        original_filename = urllib.parse.unquote(os.path.basename(downloaded_path))

        if os.path.getsize(downloaded_path) < 100000:
            return False, "הקובץ שהורד קטן מדי! נראה שגוגל דרייב חסם את ההורדה.", None

        if not marker_images_exist():
            return False, "שגיאה: קבצי תמונות החיתוך חסרים בשרת.", None

        start_b64s, end_b64 = load_marker_images()

        success = extract_pdf_by_images(downloaded_path, AUTO_REGULAR_PDF, start_b64s, end_b64)
    finally:
        if isinstance(downloaded_path, str) and os.path.exists(downloaded_path):
            os.remove(downloaded_path)

    if success:
        convert_pdf_to_bw(AUTO_REGULAR_PDF, AUTO_REGULAR_BW_PDF)
        
        if should_scrape or last_title != original_filename:
            save_config({
                **config,
                "source_url": SOURCE_URL,
                "last_drive_id": target_drive_id,
                "last_check_time": last_check_str,
                "last_title": original_filename
            })
        return True, None, original_filename
    else:
        return False, "לא הצלחנו למצוא את סימני ההתחלה והסיום בתוך ה-PDF החדש.", None

# --- פונקציות עיבוד תצוגה וממשק מתקדם ---

def render_download_view_ui(base_filename, regular_color, regular_bw, key_prefix):
    st.write("### בחר פורמט להורדה:")
    col1, col2 = st.columns(2)
    options = (
        (col1, "🎨 צבעוני", regular_color, base_filename, "color"),
        (col2, "🖨️ שחור לבן", regular_bw, base_filename.replace(".pdf", " - שחור לבן.pdf"), "bw"),
    )
    for col, label, target_file, dl_name, key in options:
        if os.path.exists(target_file):
            with open(target_file, "rb") as f:
                col.download_button(label, f, dl_name, "application/pdf", width="stretch", key=f"{key_prefix}_dl_{key}")
        else:
            col.error("הקובץ המבוקש נוצר עם שגיאה או אינו קיים.")


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

def decode_template(template_b64):
    return cv2.imdecode(np.frombuffer(base64.b64decode(template_b64), np.uint8), cv2.IMREAD_GRAYSCALE)

def template_scales(template):
    """מכין מראש את כל גדלי התבנית כדי לא לחזור על הפענוח והשינוי בכל עמוד."""
    if template is None:
        return []
    resized = []
    # 1.0 נוסף לסולם המקורי כדי לזהות סמנים שנחתכו ברזולוציית הסריקה
    for scale in np.append(1.0, np.linspace(0.4, 1.6, 12)):
        width = int(template.shape[1] * scale)
        height = int(template.shape[0] * scale)
        if height and width:
            resized.append(cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA))
    return resized

def find_image_in_page(img_array, scaled_templates, threshold=0.7):
    return best_match(img_array, scaled_templates, threshold) >= threshold

def best_match(img_array, scaled_templates, stop_at=1.0):
    best = 0.0
    for resized_template in scaled_templates:
        if resized_template.shape[0] > img_array.shape[0] or resized_template.shape[1] > img_array.shape[1]: continue
        result = cv2.matchTemplate(img_array, resized_template, cv2.TM_CCOEFF_NORMED)
        best = max(best, cv2.minMaxLoc(result)[1])
        if best >= stop_at:
            break
    return best

def shrink_templates(scaled_templates):
    return [cv2.resize(t, (max(1, t.shape[1] // 2), max(1, t.shape[0] // 2)), interpolation=cv2.INTER_AREA)
            for t in scaled_templates]

def page_matches(page, coarse_templates, full_templates, threshold=0.7):
    """סריקה מהירה בחצי רזולוציה, ואימות ברזולוציה מלאה רק לעמודים מועמדים."""
    if best_match(render_gray(page, COARSE_RENDER_SCALE), coarse_templates, COARSE_THRESHOLD) < COARSE_THRESHOLD:
        return False
    return find_image_in_page(render_gray(page, FULL_RENDER_SCALE), full_templates, threshold)

def render_gray(page, scale):
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
    img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    # רינדור ישיר באפור נותן ציוני התאמה מעט נמוכים יותר, שמפילים את start.png מתחת לסף
    return cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)

def marker_images_exist():
    return all(os.path.exists(path) for path in (*START_IMAGES, END_IMAGE))

def load_marker_images():
    start_b64s = []
    for path in START_IMAGES:
        with open(path, "rb") as f: start_b64s.append(base64.b64encode(f.read()))
    with open(END_IMAGE, "rb") as f: end_b64 = base64.b64encode(f.read())
    return start_b64s, end_b64

def extract_pdf_by_images(input_pdf_path, output_pdf_path, start_images_b64, end_image_b64):
    start_templates = [template_scales(decode_template(b64)) for b64 in start_images_b64]
    end_templates = template_scales(decode_template(end_image_b64))
    coarse_start = [shrink_templates(t) for t in start_templates]
    coarse_end = shrink_templates(end_templates)

    doc = fitz.open(input_pdf_path)
    start_page = -1
    end_page = -1
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)

        if start_page == -1:
            if any(page_matches(page, coarse, full) for coarse, full in zip(coarse_start, start_templates)):
                start_page = page_num

        if start_page != -1 and end_page == -1:
            if page_matches(page, coarse_end, end_templates):
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
        if "auto_pdf_processed" in st.session_state:
            del st.session_state["auto_pdf_processed"]
    
    if upload_option == "שליפה אוטומטית (משכן שילה)":
        # מניעת הורדה ועיבוד מחדש בכל לחיצה על כפתורי הממשק
        if "auto_pdf_processed" not in st.session_state:
            with st.spinner("מוודא ומכין את הגיליון העדכני ביותר..."):
                try:
                    result = prepare_auto_pdf()
                except Exception as e:
                    logger.exception("Automatic PDF preparation failed")
                    result = (False, f"אירעה שגיאה בהכנת הגיליון: {e}", None)
                st.session_state["auto_pdf_processed"] = result
        success, error_msg, target_title = st.session_state["auto_pdf_processed"]
        
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
                key_prefix="auto"
            )

        else:
            st.error(error_msg or "הקובץ המעובד לא נמצא בשרת.")
            if st.button("נסה שוב", icon=":material/refresh:", key="auto_retry"):
                del st.session_state["auto_pdf_processed"]
                st.rerun()

    else:
        uploaded_file = None
        manual_link = ""
        
        if upload_option == "העלאת קובץ מהמחשב":
            uploaded_file = st.file_uploader("בחר קובץ PDF מהמחשב", type=["pdf"], key="manual_upload")
        elif upload_option == "קישור מ-Google Drive":
            manual_link = st.text_input("הדבק כאן קישור שיתוף ל-PDF מ-Google Drive:")
            
        if st.button("הפעל חיתוך ועיבוד ידני"):
            if not marker_images_exist():
                st.error(f"שגיאה: קבצי התמונות ({' / '.join((*START_IMAGES, END_IMAGE))}) חסרים.")
                return

            with st.spinner("מבצע משיכה ועיבוד של המסמך..."):
                try:
                    start_b64s, end_b64 = load_marker_images()

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
                        
                        if extract_pdf_by_images(input_path, output_regular, start_b64s, end_b64):
                            convert_pdf_to_bw(output_regular, output_regular_bw)
                            
                            safe_manual_name = uploaded_file.name
                            if not safe_manual_name.lower().endswith('.pdf'):
                                safe_manual_name += ".pdf"
                            safe_manual_name = safe_manual_name.replace(".pdf", "_fixed.pdf")
                            
                            st.session_state["manual_files"] = {
                                "reg_col": output_regular,
                                "reg_bw": output_regular_bw,
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
                            
                        downloaded_path = download_drive_file(file_id)
                        if downloaded_path:
                            original_filename = urllib.parse.unquote(os.path.basename(downloaded_path))
                            
                            safe_manual_name = re.sub(r'[\\/*?:"<>|]', "", original_filename).strip()
                            if safe_manual_name.lower().endswith('.pdf'):
                                safe_manual_name = safe_manual_name.replace(".pdf", "_fixed.pdf")
                            else:
                                safe_manual_name += "_fixed.pdf"
                            
                            output_regular = "temp_regular_drive.pdf"
                            output_regular_bw = "temp_regular_bw_drive.pdf"
                            
                            if extract_pdf_by_images(downloaded_path, output_regular, start_b64s, end_b64):
                                convert_pdf_to_bw(output_regular, output_regular_bw)
                                
                                st.session_state["manual_files"] = {
                                    "reg_col": output_regular,
                                    "reg_bw": output_regular_bw,
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
                key_prefix="manual"
            )

if __name__ == "__main__":
    main()
