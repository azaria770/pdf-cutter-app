import fitz  # PyMuPDF
import cv2
import numpy as np
import os
import base64
import tempfile
import streamlit as st
import gdown
import urllib.request
import re

# --- פונקציות סריקה מקוונת (משופר ואגרסיבי יותר) ---

def get_latest_mishkan_shilo_drive_link():
    """
    סורק את אתר המאורות באופן אגרסיבי, מוצא את המספר הגבוה ביותר, 
    נכנס לפוסט ושולף את קישור הגוגל דרייב גם אם הוא חבוי בקוד.
    """
    try:
        category_url = "https://kav.meorot.net/category/%d7%a2%d7%9c%d7%95%d7%a0%d7%99-%d7%a9%d7%91%d7%aa/%d7%9e%d7%a9%d7%9b%d7%9f-%d7%a9%d7%99%d7%9c%d7%94/"
        # הוספת User-Agent מלא של כרום כדי למנוע חסימות אבטחה של האתר
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'}
        
        # 1. שליפת עמוד הקטגוריה
        req = urllib.request.Request(category_url, headers=headers)
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
        
        # 2. מציאת מספרי פוסטים - חיפוש גמיש יותר
        post_ids = re.findall(r'kav\.meorot\.net/(\d+)', html)
        if not post_ids:
            return None
        
        # 3. מציאת המספר הגבוה ביותר ובניית הקישור אליו
        latest_id = max(int(pid) for pid in post_ids)
        latest_post_url = f"https://kav.meorot.net/{latest_id}/"
        
        # 4. כניסה לפוסט הרלוונטי
        req2 = urllib.request.Request(latest_post_url, headers=headers)
        with urllib.request.urlopen(req2) as response2:
            html2 = response2.read().decode('utf-8')
            
        # 5. חילוץ קישור גוגל דרייב - חיפוש אגרסיבי למזהה (ID) של הקובץ
        drive_match = re.search(r'(https://drive\.google\.com/file/d/[a-zA-Z0-9_-]+)', html2)
        if drive_match:
            return drive_match.group(1)
            
        return None
    except Exception as e:
        print(f"Error fetching auto link: {e}")
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
        # נשאר: קיצור זמן הסריקה על ידי הקטנת מטריצת הרינדור מ-2.0 ל-1.2
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

# --- ממשק המשתמש (Streamlit) ---

def main():
    st.set_page_config(page_title="חותך PDF אוטומטי", page_icon="✂️")
    
    st.markdown("""
        <style>
        .block-container { direction: rtl; text-align: right; }
        .stButton>button { width: 100%; }
        </style>
    """, unsafe_allow_html=True)

    st.title("✂️ חיתוך PDF לפי סימנים")
    st.info("המערכת סורקת את ה-PDF ומחפשת את תמונות ההתחלה והסיום המוגדרות מראש.")

    # בחירת שיטת ההזנה כולל האופציה החדשה
    upload_option = st.radio("איך תרצה לטעון את ה-PDF?", 
                             ("העלאת קובץ מהמחשב", 
                              "קישור מ-Google Drive", 
                              "שליפה אוטומטית (משכן שילה)"))
    
    uploaded_file = None
    drive_link = ""
    
    if upload_option == "העלאת קובץ מהמחשב":
        uploaded_file = st.file_uploader("בחר קובץ PDF מהמחשב", type=["pdf"], key="main_uploader")
    elif upload_option == "קישור מ-Google Drive":
        drive_link = st.text_input("הדבק כאן קישור שיתוף ל-PDF מ-Google Drive:")
        st.caption("שים לב: הקישור חייב להיות פתוח להרשאת 'כל מי שברשותו הקישור' (Anyone with the link).")
    else:
        st.write("המערכת תיגש לאתר 'המאורות', תחפש את הגיליון העדכני ביותר של 'משכן שילה' ותוריד אותו אוטומטית.")

    START_IMG = "start.png"
    END_IMG = "end.png"

    if st.button("הפעל חיתוך אוטומטי"):
        if upload_option == "העלאת קובץ מהמחשב" and not uploaded_file:
            st.warning("נא להעלות קובץ PDF קודם.")
            return
        if upload_option == "קישור מ-Google Drive" and not drive_link:
            st.warning("נא להדביק קישור חוקי מגוגל דרייב קודם.")
            return
            
        if not os.path.exists(START_IMG) or not os.path.exists(END_IMG):
            st.error("שגיאה: קבצי התמונות (start.png / end.png) לא נמצאו בשרת. וודא שהם הועלו ל-GitHub.")
            return

        with st.spinner("מושך את הקובץ וסורק את המסמך... זה עשוי לקחת מספר שניות"):
            try:
                with open(START_IMG, "rb") as f:
                    start_b64 = base64.b64encode(f.read())
                with open(END_IMG, "rb") as f:
                    end_b64 = base64.b64encode(f.read())

                input_path = ""
                
                if upload_option == "העלאת קובץ מהמחשב":
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_in:
                        tmp_in.write(uploaded_file.getvalue())
                        input_path = tmp_in.name
                else:
                    # שימוש בגוגל דרייב - רגיל או אוטומטי
                    if upload_option == "שליפה אוטומטית (משכן שילה)":
                        drive_link = get_latest_mishkan_shilo_drive_link()
                        if not drive_link:
                            st.error("שגיאה: לא הצלחנו לאתר את קובץ ה-PDF (קישור דרייב) בעמוד העדכני ביותר.")
                            return
                            
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_in:
                        input_path = tmp_in.name
                    gdown.download(url=drive_link, output=input_path, quiet=False, fuzzy=True)
                    
                    if not os.path.exists(input_path) or os.path.getsize(input_path) < 1000:
                        st.error("שגיאה בהורדת הקובץ מדרייב. ייתכן שהקישור אינו פומבי או שאינו קובץ PDF תקין.")
                        return

                output_path = input_path.replace(".pdf", "_fixed.pdf")

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
                if 'input_path' in locals() and os.path.exists(input_path):
                    os.remove(input_path)
                if 'output_path' in locals() and os.path.exists(output_path):
                    if os.path.exists(output_path): os.remove(output_path)

if __name__ == "__main__":
    main()
