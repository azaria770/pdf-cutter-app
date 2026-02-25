import fitz  # PyMuPDF
import cv2
import numpy as np
import os
import base64
import tempfile
import streamlit as st

# --- פונקציות לוגיקה (נשארות כפי שהיו) ---

def find_image_in_page(page_pixmap, template_b64, threshold=0.7):
    img_array = np.frombuffer(page_pixmap.samples, dtype=np.uint8).reshape(page_pixmap.h, page_pixmap.w, page_pixmap.n)
    if page_pixmap.n == 4:
        img_array = cv2.cvtColor(img_array, cv2.COLOR_RGBA2GRAY)
    elif page_pixmap.n == 3:
        img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    
    img_data = base64.b64decode(template_b64)
    np_arr_template = np.frombuffer(img_data, np.uint8)
    template = cv2.imdecode(np_arr_template, cv2.IMREAD_GRAYSCALE)

    if template is None: return False

    for scale in np.linspace(0.3, 3.0, 28):
        width = int(template.shape[1] * scale)
        height = int(template.shape[0] * scale)
        if height == 0 or width == 0 or height > img_array.shape[0] or width > img_array.shape[1]:
            continue
        resized_template = cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC)
        result = cv2.matchTemplate(img_array, resized_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        if max_val >= threshold:
            return True
    return False

def fast_find_image_in_page(doc, page_num, template_b64, threshold=0.7):
    page = doc.load_page(page_num)
    img_data = base64.b64decode(template_b64)
    np_arr_template = np.frombuffer(img_data, np.uint8)
    template = cv2.imdecode(np_arr_template, cv2.IMREAD_GRAYSCALE)
    if template is None: return False
    for img_info in page.get_images(full=True):
        xref = img_info[0]
        base_image = doc.extract_image(xref)
        np_arr = np.frombuffer(base_image["image"], np.uint8)
        img_array = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)
        if img_array is not None and template.shape[0] <= img_array.shape[0] and template.shape[1] <= img_array.shape[1]:
            result = cv2.matchTemplate(img_array, template, cv2.TM_CCOEFF_NORMED)
            if np.any(result >= threshold): return True
    return False

def extract_pdf_by_images(input_pdf_path, output_pdf_path, start_image_b64, end_image_b64):
    doc = fitz.open(input_pdf_path)
    start_page = -1
    end_page = -1
    
    # חיפוש עמוד התחלה וסוף
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
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

# --- ממשק המשתמש (Streamlit) ---

def main():
    # הגדרת העמוד - חייב להופיע רק פעם אחת!
    st.set_page_config(page_title="PDF Auto Cutter", page_icon="✂️")
    
    # יישור לימין
    st.markdown("""<style> .block-container { direction: rtl; text-align: right; } </style>""", unsafe_allow_html=True)

    st.title("✂️ חיתוך PDF אוטומטי")
    st.write("המערכת משתמשת בתמונות המוגדרות מראש (start.png ו-end.png) כדי לחתוך את המסמך שלך.")

    input_pdf_file = st.file_uploader("העלה קובץ PDF לעיבוד", type=["pdf"], key="pdf_uploader")
    
    START_IMG_PATH = "start.png"
    END_IMG_PATH = "end.png"

    if st.button("בצע חיתוך אוטומטי", type="primary"):
        if not os.path.exists(START_IMG_PATH) or not os.path.exists(END_IMG_PATH):
            st.error("קבצי התמונות (start.png/end.png) חסרים בשרת. וודא שהעלית אותם ל-GitHub.")
            return

        if input_pdf_file:
            with st.spinner("סורק ומעבד..."):
                try:
                    with open(START_IMG_PATH, "rb") as f:
                        start_b64 = base64.b64encode(f.read())
                    with open(END_IMG_PATH, "rb") as f:
                        end_b64 = base64.b64encode(f.read())

                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_in:
                        tmp_in.write(input_pdf_file.getvalue())
                        temp_input_path = tmp_in.name
                    
                    temp_output_path = temp_input_path.replace(".pdf", "_out.pdf")

                    if extract_pdf_by_images(temp_input_path, temp_output_path, start_b64, end_b64):
                        st.success("הצלחה! המסמך נחתך.")
                        with open(temp_output_path, "rb") as f:
                            st.download_button("📥 הורד את ה-PDF המוכן", f, "cut_document.pdf", "application/pdf")
                    else:
                        st.error("התמונות לא נמצאו בתוך ה-PDF.")
                except Exception as e:
                    st.error(f"שגיאה: {e}")
        else:
            st.warning("נא להעלות קובץ PDF.")

if __name__ == "__main__":
    main()
