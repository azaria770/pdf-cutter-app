import fitz  # PyMuPDF
import cv2
import numpy as np
import os
import base64
import tempfile
import streamlit as st
from concurrent.futures import ProcessPoolExecutor # לעיבוד מקבילי

# --- פונקציות לוגיקה משופרות ---

def check_single_page(page_data):
    """
    פונקציית עזר לעיבוד מקבילי - בודקת עמוד בודד עבור תמונה מסוימת.
    """
    page_index, pdf_path, template_b64, threshold = page_data
    
    # פתיחת המסמך בתוך התהליך (נחוץ לעיבוד מקבילי)
    doc = fitz.open(pdf_path)
    page = doc.load_page(page_index)
    pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
    
    # המרה לשחור לבן
    img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n >= 3:
        img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    
    # טעינת התבנית
    img_data = base64.b64decode(template_b64)
    np_arr_template = np.frombuffer(img_data, np.uint8)
    template = cv2.imdecode(np_arr_template, cv2.IMREAD_GRAYSCALE)
    
    if template is None:
        doc.close()
        return page_index, False

    # אופטימיזציה 1: צמצום ל-10 קפיצות גודל (Scale) בטווח רלוונטי
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
    """
    מנהלת את החיפוש המקבילי על פני כל העמודים.
    """
    # יצירת רשימת משימות לעמודים
    tasks = [(i, pdf_path, template_b64, threshold) for i in range(total_pages)]
    
    # אופטימיזציה 2: עיבוד מקבילי (Parallel Processing)
    with ProcessPoolExecutor() as executor:
        results = list(executor.map(check_single_page, tasks))
    
    # מיון תוצאות לפי אינדקס עמוד והחזרת העמוד הראשון שמתאים
    found_pages = [idx for idx, found in results if found]
    return min(found_pages) if found_pages else -1

def extract_pdf_by_images(input_pdf_path, output_pdf_path, start_image_b64, end_image_b64):
    doc = fitz.open(input_pdf_path)
    total_pages = len(doc)
    doc.close() # נסגור כדי שהתהליכים המקביליים יוכלו לפתוח אותו בנפרד

    # חיפוש עמוד התחלה
    start_page = find_page_parallel(input_pdf_path, start_image_b64, total_pages)
    
    if start_page == -1:
        return False

    # חיפוש עמוד סיום (רק מהעמוד שנמצא והלאה לחיסכון בזמן)
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

# --- ממשק המשתמש (Streamlit) ---

def main():
    st.set_page_config(page_title="PDF Auto Cutter Pro", page_icon="⚡")
    
    st.markdown("""<style> .block-container { direction: rtl; text-align: right; } </style>""", unsafe_allow_html=True)

    st.title("⚡ חיתוך PDF מהיר (Parallel)")
    st.write("גרסה מותאמת לעיבוד מקבילי ומהיר.")

    input_pdf_file = st.file_uploader("העלה קובץ PDF לעיבוד", type=["pdf"], key="pdf_uploader_pro")
    
    START_IMG_PATH = "start.png"
    END_IMG_PATH = "end.png"

    if st.button("בצע חיתוך מהיר", type="primary"):
        if not os.path.exists(START_IMG_PATH) or not os.path.exists(END_IMG_PATH):
            st.error("קבצי start.png או end.png חסרים.")
            return

        if input_pdf_file:
            with st.spinner("מפעיל עיבוד מקבילי..."):
                try:
                    with open(START_IMG_PATH, "rb") as f:
                        start_b64 = base64.b64encode(f.read())
                    with open(END_IMG_PATH, "rb") as f:
                        end_b64 = base64.b64encode(f.read())

                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_in:
                        tmp_in.write(input_pdf_file.getvalue())
                        temp_input_path = tmp_in.name
                    
                    temp_output_path = temp_input_path.replace(".pdf", "_final.pdf")

                    if extract_pdf_by_images(temp_input_path, temp_output_path, start_b64, end_b64):
                        st.success("הסתיים בהצלחה!")
                        with open(temp_output_path, "rb") as f:
                            st.download_button("📥 הורד קובץ מוכן", f, "cut_document.pdf", "application/pdf")
                    else:
                        st.error("לא נמצאו התאמות בטווח העמודים.")
                except Exception as e:
                    st.error(f"שגיאה: {e}")
                finally:
                    if 'temp_input_path' in locals(): os.remove(temp_input_path)
        else:
            st.warning("נא להעלות קובץ.")

if __name__ == "__main__":
    main()
