import fitz  # PyMuPDF
import cv2
import numpy as np
import os
import base64
import tempfile
import streamlit as st
import requests  # חדש: לצורך הורדת הקובץ מהלינק
import re        # חדש: לעיבוד הלינק של גוגל דרייב
from concurrent.futures import ProcessPoolExecutor

# --- פונקציות לוגיקה ועיבוד מקבילי (ללא שינוי) ---

def check_single_page(page_data):
    page_index, pdf_path, template_b64, threshold = page_data
    doc = fitz.open(pdf_path)
    page = doc.load_page(page_index)
    pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
    img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n >= 3:
        img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    img_data = base64.b64decode(template_b64)
    np_arr_template = np.frombuffer(img_data, np.uint8)
    template = cv2.imdecode(np_arr_template, cv2.IMREAD_GRAYSCALE)
    if template is None:
        doc.close()
        return page_index, False
    for scale in np.linspace(0.5, 1.5, 10):
        width = int(template.shape[1] * scale)
        height = int(template.shape[0] * scale)
        if height == 0 or width == 0 or height > img_array.shape[0] or width > img_array.shape[1]:
            continue
        resized_template = cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(img_array, resized_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        if max_val >= threshold:
            doc.close()
            return page_index, True
    doc.close()
    return page_index, False

def find_page_parallel(pdf_path, template_b64, total_pages, threshold=0.7):
    tasks = [(i, pdf_path, template_b64, threshold) for i in range(total_pages)]
    
    # שימוש ב-max_workers כדי לא להחניק את השרת החינמי
    with ProcessPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(check_single_page, tasks))
    
    found_pages = [idx for idx, found in results if found]
    return min(found_pages) if found_pages else -1

if __name__ == "__main__":
    # זהו הקו המפריד הקריטי שמונע מהאפליקציה לקרוס בענן
    main()
    
def extract_pdf_by_images(input_pdf_path, output_pdf_path, start_image_b64, end_image_b64):
    doc = fitz.open(input_pdf_path)
    total_pages = len(doc)
    doc.close()
    start_page = find_page_parallel(input_pdf_path, start_image_b64, total_pages)
    if start_page == -1: return False
    end_page = find_page_parallel(input_pdf_path, end_image_b64, total_pages)
    if start_page != -1 and end_page != -1 and end_page >= start_page:
        doc = fitz.open(input_pdf_path)
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=start_page, to_page=end_page)
        new_doc.save(output_pdf_path)
        new_doc.close()
        doc.close()
        return True
    return False

# --- פונקציית הורדה מגוגל דרייב ---

def download_from_gdrive(url):
    """
    ממירה לינק שיתוף של גוגל דרייב ללינק הורדה ישירה ומורידה את הקובץ.
    """
    try:
        # חילוץ ה-File ID מתוך הלינק
        file_id_match = re.search(r'd/([^/]+)', url)
        if not file_id_match:
            return None
        file_id = file_id_match.group(1)
        direct_link = f'https://drive.google.com/uc?export=download&id={file_id}'
        
        response = requests.get(direct_link, stream=True)
        if response.status_code == 200:
            return response.content
        return None
    except Exception:
        return None

# --- ממשק המשתמש (Streamlit) ---

def main():
    st.set_page_config(page_title="PDF Auto Cutter Pro", page_icon="⚡")
    st.markdown("""<style> .block-container { direction: rtl; text-align: right; } </style>""", unsafe_allow_html=True)

    st.title("⚡ חיתוך PDF מהיר וחכם")
    st.write("בחר דרך להזנת הקובץ (העלאה או לינק מגוגל דרייב):")

    # יצירת טאבים לבחירת שיטת ההזנה
    tab1, tab2 = st.tabs(["📤 העלאת קובץ", "🔗 לינק מגוגל דרייב"])
    
    pdf_content = None

    with tab1:
        uploaded_file = st.file_uploader("בחר קובץ PDF", type=["pdf"], key="file_up")
        if uploaded_file:
            pdf_content = uploaded_file.getvalue()

    with tab2:
        gdrive_url = st.text_input("הדבק כאן לינק לשיתוף מגוגל דרייב:", placeholder="https://drive.google.com/file/d/...")
        if gdrive_url:
            if st.button("טען קובץ מהלינק"):
                with st.spinner("מוריד קובץ מגוגל דרייב..."):
                    pdf_content = download_from_gdrive(gdrive_url)
                    if pdf_content:
                        st.success("הקובץ נטען בהצלחה!")
                        st.session_state['pdf_content'] = pdf_content
                    else:
                        st.error("לא ניתן להוריד את הקובץ. וודא שהלינק פתוח לצפייה לכולם (Anyone with the link).")

    # שמירת התוכן ב-session_state כדי שלא ייעלם ברענון
    if pdf_content:
        st.session_state['pdf_content'] = pdf_content

    START_IMG_PATH = "start.png"
    END_IMG_PATH = "end.png"

    if st.button("🚀 בצע חיתוך", type="primary"):
        if 'pdf_content' not in st.session_state:
            st.warning("נא לספק קובץ PDF תחילה.")
            return

        if not os.path.exists(START_IMG_PATH) or not os.path.exists(END_IMG_PATH):
            st.error("קבצי start.png או end.png חסרים בשרת.")
            return

        with st.spinner("מעבד ומבצע חיתוך מקבילי..."):
            try:
                # טעינת תמונות
                with open(START_IMG_PATH, "rb") as f:
                    start_b64 = base64.b64encode(f.read())
                with open(END_IMG_PATH, "rb") as f:
                    end_b64 = base64.b64encode(f.read())

                # שמירה לקבצים זמניים
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_in:
                    tmp_in.write(st.session_state['pdf_content'])
                    temp_input_path = tmp_in.name
                
                temp_output_path = temp_input_path.replace(".pdf", "_final.pdf")

                if extract_pdf_by_images(temp_input_path, temp_output_path, start_b64, end_b64):
                    st.success("החיתוך הושלם!")
                    with open(temp_output_path, "rb") as f:
                        st.download_button("📥 הורד קובץ חתוך", f, "output.pdf", "application/pdf")
                else:
                    st.error("התמונות לא נמצאו ב-PDF.")
            except Exception as e:
                st.error(f"שגיאה: {e}")
            finally:
                if 'temp_input_path' in locals(): os.remove(temp_input_path)

if __name__ == "__main__":
    main()

