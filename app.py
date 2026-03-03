def split_pdf_to_columns(input_pdf_path, output_pdf_path):
    doc = fitz.open(input_pdf_path)
    out_doc = fitz.open()

    for page_num in range(len(doc)):
        page = doc[page_num]
        rect = page.rect
        width = rect.width
        height = rect.height

        top_margin = 50
        bottom_margin = 50
        crop_height = height - bottom_margin

        blocks = page.get_text("blocks")
        
        # סינון מחמיר: רק טקסט, מתחת ל-40% רוחב, ו*רק* טקסט שנמצא בתוך שולי החיתוך האנכיים
        col_blocks = [b for b in blocks if b[6] == 0 and (b[2] - b[0]) < width * 0.4 and b[1] >= top_margin and b[3] <= crop_height]
        
        left_x0, left_x1 = width, 0
        mid_x0, mid_x1 = width, 0
        right_x0, right_x1 = width, 0
        
        found_left, found_mid, found_right = False, False, False
        
        for b in col_blocks:
            cx = (b[0] + b[2]) / 2
            if cx < width / 3: 
                left_x0, left_x1 = min(left_x0, b[0]), max(left_x1, b[2])
                found_left = True
            elif cx < 2 * width / 3: 
                mid_x0, mid_x1 = min(mid_x0, b[0]), max(mid_x1, b[2])
                found_mid = True
            else: 
                right_x0, right_x1 = min(right_x0, b[0]), max(right_x1, b[2])
                found_right = True
        
        # מרווח ביטחון מינימלי להצמדות מקסימלית לטקסט
        pad = 1
        
        # בניית התיבות רק לטורים שיש בהם טקסט באמת
        right_col = fitz.Rect(right_x0 - pad, top_margin, right_x1 + pad, crop_height) if found_right else None
        middle_col = fitz.Rect(mid_x0 - pad, top_margin, mid_x1 + pad, crop_height) if found_mid else None
        left_col = fitz.Rect(left_x0 - pad, top_margin, left_x1 + pad, crop_height) if found_left else None

        # נאסוף רק את הטורים התקינים
        columns = [c for c in [right_col, middle_col, left_col] if c is not None and c.width > 0]

        page_dict = page.get_text("dict")
        images = [b for b in page_dict.get("blocks", []) if b["type"] == 1]

        for col_idx, col_rect in enumerate(columns):
            new_page = out_doc.new_page(width=col_rect.width, height=col_rect.height)
            new_page.show_pdf_page(new_page.rect, doc, page_num, clip=col_rect)

            for img in images:
                img_bbox = fitz.Rect(img["bbox"])
                intersections = [img_bbox.intersect(c).get_area() for c in columns]
                
                if not intersections:
                    continue
                    
                max_area = max(intersections)
                
                if max_area == 0:
                    continue 
                
                assigned_col_idx = intersections.index(max_area)
                shifted_bbox = fitz.Rect(
                    img_bbox.x0 - col_rect.x0, 
                    img_bbox.y0 - col_rect.y0, 
                    img_bbox.x1 - col_rect.x0, 
                    img_bbox.y1 - col_rect.y0
                )
                
                if col_idx != assigned_col_idx:
                    new_page.draw_rect(shifted_bbox, color=(1, 1, 1), fill=(1, 1, 1))
                else:
                    new_page.draw_rect(shifted_bbox, color=(1, 1, 1), fill=(1, 1, 1))
                    img_bytes = img.get("image")
                    if img_bytes and img_bbox.width > 0:
                        scale = col_rect.width / img_bbox.width
                        new_height = img_bbox.height * scale
                        target_rect = fitz.Rect(0, shifted_bbox.y0, col_rect.width, shifted_bbox.y0 + new_height)
                        new_page.insert_image(target_rect, stream=img_bytes)

    out_doc.save(output_pdf_path)
    out_doc.close()
    doc.close()
