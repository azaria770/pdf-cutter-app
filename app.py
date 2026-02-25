import fitz  # PyMuPDF
import cv2
import numpy as np
import os
import base64
import tempfile
import streamlit as st


def find_image_in_page(page_pixmap, template_b64, threshold=0.7):
    """
    ממירה את עמוד ה-PDF לתמונה ומחפשת בתוכו את תמונת המטרה.
    שודרג לחיפוש רב-ממדי (Multi-Scale) + המרה לשחור-לבן (Grayscale) להתגברות על הבדלי צבעים.
    """
    # המרת הפיקסמאפ של PyMuPDF למערך NumPy ש-OpenCV יודע לקרוא
    img_array = np.frombuffer(page_pixmap.samples, dtype=np.uint8).reshape(page_pixmap.h, page_pixmap.w, page_pixmap.n)

    # המרת צבעים מפורמט PDF לפורמט גווני אפור (Grayscale)
    if page_pixmap.n == 4:
        img_array = cv2.cvtColor(img_array, cv2.COLOR_RGBA2GRAY)
    elif page_pixmap.n == 3:
        img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    elif page_pixmap.n == 1:
        pass  # כבר בשחור לבן
    else:
        return False

    # פעינוח תמונת החיפוש מ-Base64 ישירות לגווני אפור
    img_data = base64.b64decode(template_b64)
    np_arr_template = np.frombuffer(img_data, np.uint8)
    template = cv2.imdecode(np_arr_template, cv2.IMREAD_GRAYSCALE)

    if template is None:
        raise ValueError("לא ניתן לפענח את תמונת המטרה מהמחרוזת שסופקה.")

    # === שדרוג: סריקה מרובת-גדלים (Multi-Scale) ===
    # נסרוק החל מ-30% ועד 300% מגודל תמונת המטרה כדי למצוא התאמה
    for scale in np.linspace(0.3, 3.0, 28):
        width = int(template.shape[1] * scale)
        height = int(template.shape[0] * scale)

        # מניעת קריסה: אם התמונה הוקטנה ל-0 או שהיא גדולה פיזית מעמוד ה-PDF, מדלגים
        if height == 0 or width == 0 or height > img_array.shape[0] or width > img_array.shape[1]:
            continue

        # שינוי גודל תמונת המטרה בהתאם לקנה המידה הנוכחי
        resized_template = cv2.resize(template, (width, height),
                                      interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC)

        # ביצוע התאמת תבנית (Template Matching)
        result = cv2.matchTemplate(img_array, resized_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)

        # אם נמצאה התאמה שגבוהה מהסף שהוגדר
        if max_val >= threshold:
            return True

    return False


def fast_find_image_in_page(doc, page_num, template_b64, threshold=0.7):
    """
    שולפת אובייקטי תמונה מוטמעים מהעמוד ומחפשת בהם (חיפוש מהיר - הומר לשחור לבן).
    """
    page = doc.load_page(page_num)

    # פעינוח תמונת החיפוש מ-Base64 ישירות לגווני אפור
    img_data = base64.b64decode(template_b64)
    np_arr_template = np.frombuffer(img_data, np.uint8)
    template = cv2.imdecode(np_arr_template, cv2.IMREAD_GRAYSCALE)

    if template is None:
        raise ValueError("לא ניתן לפענח את תמונת המטרה מהמחרוזת שסופקה.")

    # מעבר על כל התמונות המוטמעות בעמוד הספציפי
    for img_info in page.get_images(full=True):
        xref = img_info[0]
        base_image = doc.extract_image(xref)
        image_bytes = base_image["image"]

        # המרת התמונה שנשלפה לפורמט של OpenCV בגווני אפור
        np_arr = np.frombuffer(image_bytes, np.uint8)
        img_array = cv2.imdecode(np_arr, cv2.IMREAD_GRAYSCALE)

        if img_array is None:
            continue

        # בדיקה שהתבנית לא גדולה מהתמונה שנשלפה מה-PDF (אחרת OpenCV יזרוק שגיאה)
        if template.shape[0] <= img_array.shape[0] and template.shape[1] <= img_array.shape[1]:
            result = cv2.matchTemplate(img_array, template, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= threshold)
            if len(locations[0]) > 0:
                return True
    return False


def extract_pdf_by_images(input_pdf_path, output_pdf_path, start_image_b64, end_image_b64):
    """
    סורקת את ה-PDF וגוזרת אותו לפי תמונת התחלה ותמונת סיום, תוך שילוב חיפוש מהיר ואיטי.
    """
    if not os.path.exists(input_pdf_path):
        print(f"שגיאה: קובץ ה-PDF לא נמצא בנתיב {input_pdf_path}")
        return False

    doc = fitz.open(input_pdf_path)
    start_page = -1
    end_page = -1

    # --- שלב 1: בדיקה אם המסמך הוא קובץ טהור (דיגיטלי) ---
    is_digital = False
    for page_num in range(min(3, len(doc))):
        if doc.load_page(page_num).get_text("text").strip():
            is_digital = True
            break

    # --- שלב 2: ניסיון חיפוש מהיר (אם דיגיטלי) ---
    if is_digital:
        for page_num in range(len(doc)):
            if start_page == -1:
                if fast_find_image_in_page(doc, page_num, start_image_b64):
                    start_page = page_num

            if start_page != -1 and end_page == -1:
                if fast_find_image_in_page(doc, page_num, end_image_b64):
                    end_page = page_num
                    break

    # --- שלב 3: מעבר לחיפוש איטי במקרה הצורך ---
    if start_page == -1 or end_page == -1:
        # איפוס תוצאות קודמות במקרה שהחיפוש המהיר מצא רק תמונה אחת
        start_page = -1
        end_page = -1

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            zoom = 2.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)

            if start_page == -1:
                if find_image_in_page(pix, start_image_b64):
                    start_page = page_num

            if start_page != -1 and end_page == -1:
                if find_image_in_page(pix, end_image_b64):
                    end_page = page_num
                    break

    # --- שלב 4: יצירת הקובץ החדש ---
    if start_page != -1 and end_page != -1:
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=start_page, to_page=end_page)
        new_doc.save(output_pdf_path)
        new_doc.close()
        doc.close()
        return True
    else:
        doc.close()
        return False


# --- ממשק משתמש כאתר אינטרנט (Streamlit) ---
# --- ממשק משתמש כאתר אינטרנט (Streamlit) ---
def main():
    st.set_page_config(page_title="חותך ה-PDF האוטומטי", page_icon="✂️", layout="centered")
    
    # יישור טקסט לימין (RTL)
    st.markdown("""
        <style>
        .block-container { direction: rtl; text-align: right; }
        </style>
    """, unsafe_allow_html=True)

    st.title("✂️ חיתוך PDF אוטומטי")
    st.write("העלה את קובץ ה-PDF. המערכת תזהה אוטומטית את תמונות ההתחלה והסיום המוגדרות מראש ותגזור את המסמך.")
    
    input_pdf_file = st.file_uploader("העלה קובץ PDF לעיבוד", type=["pdf"])
    
    # הגדרת נתיבים לתמונות הקבועות (שנמצאות בתיקיית הפרויקט)
    START_IMG_PATH = "start.png"
    END_IMG_PATH = "end.png"

    if st.button("בצע חיתוך אוטומטי", type="primary"):
        # בדיקה שהתמונות הקבועות אכן קיימות בשרת
        if not os.path.exists(START_IMG_PATH) or not os.path.exists(END_IMG_PATH):
            st.error("שגיאה: קבצי התמונות הקבועים (start.png / end.png) חסרים בשרת.")
            return

        if input_pdf_file:
            with st.spinner("מעבד את המסמך..."):
                try:
                    # קריאת התמונות מהדיסק והמרה ל-Base64 עבור הפונקציות הקיימות
                    with open(START_IMG_PATH, "rb") as f:
                        start_b64 = base64.b64encode(f.read())
                    with open(END_IMG_PATH, "rb") as f:
                        end_b64 = base64.b64encode(f.read())

                    # יצירת קבצים זמניים לעיבוד ה-PDF
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_in:
                        tmp_in.write(input_pdf_file.getvalue())
                        temp_input_path = tmp_in.name
                        
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_out:
                        temp_output_path = tmp_out.name

                    # הפעלת לוגיקת החיתוך
                    success = extract_pdf_by_images(temp_input_path, temp_output_path, start_b64, end_b64)
                
                    if success:
                        st.success("המסמך זוהה ונחתך בהצלחה!")
                        with open(temp_output_path, "rb") as f:
                            st.download_button(
                                label="📥 הורד את ה-PDF החתוך",
                                data=f,
                                file_name="extracted_document.pdf",
                                mime="application/pdf"
                            )
                    else:
                        st.error("לא הצלחנו למצוא את סימני ההתחלה או הסיום המוגדרים בתוך ה-PDF שהעלית.")
                
                except Exception as e:
                    st.error(f"אירעה שגיאה טכנית: {e}")
                finally:
                    # ניקוי שאריות
                    if 'temp_input_path' in locals(): os.remove(temp_input_path)
                    if 'temp_output_path' in locals(): os.remove(temp_output_path)
        else:
            st.warning("נא להעלות קובץ PDF תחילה.")

if __name__ == "__main__":
    main()


if __name__ == "__main__":

    main()
