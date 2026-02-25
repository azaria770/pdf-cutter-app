def get_latest_mishkan_shilo_drive_link():
    """
    סורק את דף הקטגוריה, מוצא את הקישור לפוסט האחרון (לפי המספר ב-URL)
    ואז נכנס לפוסט כדי למצוא את הדרייב.
    """
    st.info("🌐 מתחבר לדף הקטגוריה...")
    
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'}

    try:
        response = scraper.get(CATEGORY_URL, headers=headers, timeout=20)
        if response.status_code != 200:
            st.error(f"❌ חסימה בדף הקטגוריה (קוד {response.status_code})")
            return None
        
        # חיפוש קישורים שמכילים מספרים (למשל mishkan-shilo-72418)
        # אנחנו מחפשים את כל הכתובות בתוך תגיות href שנגמרות במספר ולוכסן
        all_links = re.findall(r'href="https://kav\.meorot\.net/([^"]+?(\d+)/?)"', response.text)
        
        if not all_links:
            st.error("❌ לא נמצאו קישורי פוסטים. וודא שכתובת הקטגוריה תקינה.")
            return None
        
        # חילוץ המספרים בלבד ומציאת המקסימלי (הכי חדש)
        post_ids = []
        url_map = {}
        for full_path, p_id in all_links:
            post_ids.append(int(p_id))
            url_map[int(p_id)] = f"https://kav.meorot.net/{full_path}"

        latest_id = max(post_ids)
        latest_url = url_map[latest_id]
        
        st.write(f"📄 נמצא פוסט עדכני (ID: {latest_id}). נכנס לשלוף את הקובץ...")

        # כניסה לפוסט הספציפי
        time.sleep(1)
        post_response = scraper.get(latest_url, headers=headers, timeout=20)
        html = post_response.text
        
        # חיפוש לינק דרייב
        drive_links = re.findall(r'drive\.google\.com(?:%2F|/)file(?:%2F|/)d(?:%2F|/)([a-zA-Z0-9_-]{20,})', html)
        
        if drive_links:
            file_id = drive_links[0]
            found_url = f"https://drive.google.com/file/d/{file_id}"
            st.success(f"✅ נמצא קישור לקובץ!")
            return found_url
        else:
            st.error(f"❌ לא נמצא קישור גוגל דרייב בתוך הפוסט {latest_id}.")
            return None

    except Exception as e:
        st.error(f"❌ שגיאה: {e}")
        return None
