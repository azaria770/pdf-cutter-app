import fitz  # PyMuPDF
import cv2
import numpy as np
import os
import base64
import tempfile
import streamlit as st

# --- פונקציות עיבוד וזיהוי ---

def find_image_in_page(page_pixmap, template_b64, threshold=0.7):
    """
    סורק עמוד PDF ומחפש תמונת מטרה תוך שימוש באופטימיזציית Scale למהירות מקסימלית.
    """
    # המרת עמוד ה-PDF למערך NumPy (גווני אפור)
    img_array = np.frombuffer(page_pixmap.samples, dtype=np.uint8).reshape(page_pixmap.h, page_pixmap.w, page_pixmap.n)
    if page_pixmap.n >= 3:
        img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    
    # טעינת תמונת המטרה מ-Base64
    img_data = base64.b64decode(template_b64)
    np_arr_template = np.frombuffer(img_data, np.uint8)
    template = cv2.imdecode(np_arr_template, cv2.IMREAD_GRAYSCALE)

    if template is None:
        return False

    # אופטימיזציה: 12 קפיצות גודל בלבד למהירות (במקום 28)
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
    """
    סורק את המסמך וגוזר את טווח העמודים.
    """
    doc = fitz.open(input_pdf_path)
    start_page = -1
    end_page = -1

    # מעבר על עמודי המסמך
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        # רנדור העמוד לתמונה ברזולוציה טובה לזיהוי
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))

        if start_page == -1:
            if find_image_in_page(pix, start_image_b64):
                start_page = page_num
        
        # אם מצאנו התחלה, נחפש סוף (מאותו עמוד והלאה)
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
    st.set_page_config(page_title="חותך PDF אוטומטי", page_icon="✂️")
    
    # עיצוב RTL לעברית
    st.markdown("""
        <style>
        .block-container { direction: rtl; text-align: right; }
        .stButton>button { width: 100%; }
        </style>
    """, unsafe_allow_html=True)

    st.title("✂️ חיתוך PDF לפי סימנים")
    st.info("המערכת סורקת את ה-PDF ומחפשת את תמונות ההתחלה והסיום המוגדרות מראש.")

    # רכיב העלאת קבצים
    uploaded_file = st.file_uploader("בחר קובץ PDF מהמחשב", type=["pdf"], key="main_uploader")
    
    # נתיבים לתמונות הקבועות ב-GitHub
    START_IMG = "start.png"
    END_IMG = "end.png"

    if st.button("הפעל חיתוך אוטומטי"):
        if not uploaded_file:
            st.warning("נא להעלות קובץ PDF קודם.")
            return
            
        if not os.path.exists(START_IMG) or not os.path.exists(END_IMG):
            st.error("שגיאה: קבצי התמונות (start.png / end.png) לא נמצאו בשרת. וודא שהם הועלו ל-GitHub.")
            return

        with st.spinner("סורק את המסמך... זה עשוי לקחת מספר שניות"):
            try:
                # טעינת התמונות
                with open(START_IMG, "rb") as f:
                    start_b64 = base64.b64encode(f.read())
                with open(END_IMG, "rb") as f:
                    end_b64 = base64.b64encode(f.read())

                # שמירה זמנית של הקובץ שהועלה
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_in:
                    tmp_in.write(uploaded_file.getvalue())
                    input_path = tmp_in.name
                
                output_path = input_path.replace(".pdf", "_fixed.pdf")

                # ביצוע החיתוך
                if extract_pdf_by_images(input_path, output_path, start_b64, end_b64):
                    st.success("החיתוך הושלם בהצלחה!")
                    with open(output_path, "rb") as f:
                        st.download_button(
                            label="📥 לחץ כאן להורדת הקובץ החתוך",
                            data=f,
                            file_name="cut_document.pdf",
                            mime="application/pdf"
                        )
                else:
                    st.error("לא הצלחנו למצוא את תמונת ההתחלה או הסיום בתוך המסמך.")
            
            except Exception as e:
                st.error(f"אירעה שגיאה בעיבוד: {e}")
            finally:
                # ניקוי קבצים זמניים
                if 'input_path' in locals() and os.path.exists(input_path):
                    os.remove(input_path)
                if 'output_path' in locals() and os.path.exists(output_path):
                    if os.path.exists(output_path): os.remove(output_path)

if __name__ == "__main__":
    main()
