"""Tro ly AI cua man hinh "Tro ly AI".

Hai che do, tu chon theo cau hinh:

1. Co ANTHROPIC_API_KEY trong .env  ->  goi Claude API. Truoc khi goi, app
   dong goi san mot ban chup so lieu that (doanh thu, ton kho, ban chay...)
   vao system prompt, nen model tra loi dua tren du lieu cua CHINH cua hang
   chu khong bia so.
2. Khong co key  ->  bo tra loi theo tu khoa (rule-based) chay hoan toan
   offline, van doc so lieu that tu MongoDB. Cau hoi duoc bo dau truoc khi
   so khop nen go "doanh thu hom nay" hay "doanh thu hôm nay" deu hieu.

Moi truy van so lieu deu di qua report_service / cac model nen tu dong
loai don da huy, khop voi man hinh Thong ke.
"""
import os
import re
from datetime import date, datetime, timedelta

from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, DeadlineExceeded

from app.utils.rag_store import query_rag_context
from app.models import customer as customer_model
from app.models import order as order_model
from app.models import product as product_model
from app.services import report_service
from app.utils.formatters import money
from app.utils.text import search_key

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

APP_GUIDE = """Bạn là trợ lý của TechStore — phần mềm quản lý bán hàng công nghệ.
Trả lời NGẮN GỌN bằng tiếng Việt, nhiệt tình, thân thiện, đúng số liệu được cung cấp.
- Khi khách hỏi theo đối tượng sử dụng (ví dụ: sinh viên, dân văn phòng, game thủ...) mà trong dữ liệu không có tag phân loại chính xác, KHÔNG mở đầu bằng "Xin lỗi, tôi không có thông tin...". Hãy trả lời trực tiếp và nhiệt tình các sản phẩm phù hợp đang có trong kho.
- Khi gợi ý sản phẩm cụ thể, luôn kèm theo giá bán và số lượng tồn kho lấy từ dữ liệu snapshot.
- Chỉ khi câu hỏi hoàn toàn nằm ngoài dữ liệu cửa hàng và cách dùng phần mềm mới nói rõ là không có thông tin.

Cách dùng các màn hình:
- Bán hàng: tìm sản phẩm (gõ là lọc ngay), double-click hoặc "Thêm vào giỏ";
  gõ đúng mã SKU rồi Enter là thêm thẳng vào giỏ (dùng được với máy quét mã vạch);
  nhập giảm giá, tên + số điện thoại khách rồi bấm THANH TOÁN.
- Sản phẩm (chỉ Quản lý): thêm/sửa/xóa, chọn ảnh, đặt tồn tối thiểu.
- Danh mục (chỉ Quản lý): thêm/sửa/xóa; đổi tên tự cập nhật mọi sản phẩm.
- Tồn kho (chỉ Quản lý): xem sản phẩm sắp hết, nhập thêm hàng.
- Hóa đơn: lọc theo mã/khách/khoảng ngày, xem chi tiết, xuất PDF, xuất Excel,
  HỦY ĐƠN (tồn kho được cộng trả lại, thống kê bỏ qua đơn hủy).
- Khách hàng: tự ghi nhận từ đơn có số điện thoại; double-click xem lịch sử mua.
- Thống kê (chỉ Quản lý): 4 thẻ số liệu + 3 biểu đồ, xuất Excel.
- Đăng nhập: admin/admin123 (Quản lý), nhanvien/123456 (Nhân viên).
- Nút 🌙 dưới thanh bên để đổi giao diện sáng/tối."""


def has_api() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


# ---------- ban chup so lieu ----------

def _data_snapshot() -> str:
    """Tom tat so lieu hien tai thanh van ban, dung cho ca hai che do."""
    today = datetime.now()
    first_of_month = today.replace(day=1)
    lines = [f"Số liệu tính đến {today:%H:%M %d/%m/%Y}:"]

    day_stats = report_service.summary(today, today)
    day_profit = day_stats.get('profit', 0)
    lines.append(
        f"- Hôm nay: Doanh thu {money(day_stats['revenue'])}, Lợi nhuận {money(day_profit)}, "
        f"{day_stats['orders']} đơn, {day_stats['products_sold']} sản phẩm.")

    month_stats = report_service.summary(first_of_month, today)
    month_profit = month_stats.get('profit', 0)
    lines.append(
        f"- Tháng này: Doanh thu {money(month_stats['revenue'])}, Lợi nhuận {money(month_profit)}, "
        f"{month_stats['orders']} đơn, trung bình {money(month_stats['avg_order'])}/đơn.")
    lines.append(
        f"- Hôm nay: {money(day_stats['revenue'])}, {day_stats['orders']} đơn, "
        f"{day_stats['products_sold']} sản phẩm.")

    month_stats = report_service.summary(first_of_month, today)
    lines.append(
        f"- Tháng này: {money(month_stats['revenue'])}, {month_stats['orders']} đơn, "
        f"trung bình {money(month_stats['avg_order'])}/đơn.")

    top = report_service.top_products(5, today - timedelta(days=30), today)
    if top:
        lines.append("- Bán chạy 30 ngày qua: " + "; ".join(
            f"{row['_id']} ({row['quantity']} cái)" for row in top))

    low = product_model.low_stock()
    if low:
        lines.append("- Sắp hết hàng: " + "; ".join(
            f"{p['name']} (còn {p['stock']}, tối thiểu {p.get('min_stock', 0)})"
            for p in low[:10]))
    else:
        lines.append("- Tồn kho ổn định, không sản phẩm nào dưới mức tối thiểu.")

    spenders = customer_model.top_spenders(3)
    if spenders:
        lines.append("- Khách chi tiêu nhiều nhất: " + "; ".join(
            f"{c['name']} ({money(c['total_spent'])}, {c['visits']} lần)"
            for c in spenders))
    return "\n".join(lines)


# ---------- che do offline: so khop tu khoa ----------

def _period_from(q: str):
    """Doan khoang thoi gian trong cau hoi (da bo dau)."""
    today = date.today()
    to_dt = lambda d: datetime(d.year, d.month, d.day)  # noqa: E731
    if "hom nay" in q:
        return to_dt(today), to_dt(today), "hôm nay"
    if "hom qua" in q:
        d = today - timedelta(days=1)
        return to_dt(d), to_dt(d), "hôm qua"
    if "tuan" in q:
        return to_dt(today - timedelta(days=6)), to_dt(today), "7 ngày qua"
    if "thang truoc" in q:
        last = today.replace(day=1) - timedelta(days=1)
        return to_dt(last.replace(day=1)), to_dt(last), "tháng trước"
    if "thang" in q:
        return to_dt(today.replace(day=1)), to_dt(today), "tháng này"
    if "nam" in q:
        return to_dt(today.replace(month=1, day=1)), to_dt(today), "năm nay"
    return None, None, "toàn bộ thời gian"


def _answer_revenue(q: str) -> str:
    date_from, date_to, label = _period_from(q)
    stats = report_service.summary(date_from, date_to)
    if stats["orders"] == 0:
        return f"Chưa có đơn hàng nào trong {label}."
    return (f"Doanh thu {label}: {money(stats['revenue'])} từ "
            f"{stats['orders']} hóa đơn ({stats['products_sold']} sản phẩm, "
            f"trung bình {money(stats['avg_order'])}/đơn). "
            f"Số liệu không tính các đơn đã hủy.")


def _answer_low_stock() -> str:
    low = product_model.low_stock()
    if not low:
        return "Tồn kho đang ổn định — không sản phẩm nào dưới mức tối thiểu."
    lines = [f"Có {len(low)} sản phẩm sắp hết hàng:"]
    lines += [f"• {p['name']}: còn {p['stock']} (tối thiểu {p.get('min_stock', 0)})"
              for p in low[:10]]
    if len(low) > 10:
        lines.append(f"... và {len(low) - 10} sản phẩm khác (xem màn Tồn kho).")
    return "\n".join(lines)


def _answer_top_products(q: str) -> str:
    date_from, date_to, label = _period_from(q)
    top = report_service.top_products(5, date_from, date_to)
    if not top:
        return f"Chưa có dữ liệu bán hàng trong {label}."
    lines = [f"Top sản phẩm bán chạy {label}:"]
    lines += [f"{i}. {row['_id']} — {row['quantity']} cái, {money(row['revenue'])}"
              for i, row in enumerate(top, start=1)]
    return "\n".join(lines)


def _answer_customers() -> str:
    spenders = customer_model.top_spenders(5)
    if not spenders:
        return ("Chưa có hồ sơ khách hàng nào. Khách được ghi nhận tự động "
                "khi thanh toán có nhập số điện thoại.")
    lines = ["Khách hàng chi tiêu nhiều nhất:"]
    lines += [f"{i}. {c['name']} ({c['phone']}) — {money(c['total_spent'])}, "
              f"{c['visits']} lần mua"
              for i, c in enumerate(spenders, start=1)]
    return "\n".join(lines)


def _answer_recent_orders() -> str:
    orders = order_model.recent(5)
    if not orders:
        return "Chưa có hóa đơn nào."
    lines = ["5 hóa đơn gần nhất:"]
    for o in orders:
        status = " (đã hủy)" if o.get("status") == "cancelled" else ""
        lines.append(f"• {o['order_code']} — {o['customer']['name']}, "
                     f"{money(o['total'])}, {o['created_at']:%d/%m %H:%M}{status}")
    return "\n".join(lines)

def _answer_profit(q: str) -> str:
    date_from, date_to, label = _period_from(q)
    stats = report_service.summary(date_from, date_to)
    if stats["orders"] == 0:
        return f"Chưa có đơn hàng nào trong {label} để tính lợi nhuận."
    
    profit = stats.get('profit', 0)
    return (f"Lợi nhuận {label}: {money(profit)} "
            f"(từ tổng doanh thu {money(stats['revenue'])} của {stats['orders']} hóa đơn). "
            f"Số liệu không tính các đơn đã hủy.")

HELP_TEXT = """Mình có thể trả lời các câu như:
• "Doanh thu hôm nay / tuần này / tháng này?"
• "Sản phẩm nào sắp hết hàng?"
• "Top bán chạy tháng này?"
• "Khách nào mua nhiều nhất?"
• "Các hóa đơn gần đây?"
• "Cách hủy hóa đơn / xuất Excel / thêm sản phẩm?"
(Thêm GEMINI_API_KEY vào file .env để mình trả lời tự nhiên hơn bằng Gemini.)"""

USAGE = {
    ("huy", "hoan"): "Hủy hóa đơn: mở màn Hóa đơn, chọn đơn rồi bấm nút \"Hủy đơn\" "
                     "(hoặc mở chi tiết để xem trước). Tồn kho được cộng trả lại và "
                     "thống kê sẽ bỏ qua đơn đã hủy.",
    ("excel",): "Xuất Excel: màn Hóa đơn có nút \"Xuất Excel\" (xuất danh sách đang "
                "lọc), màn Thống kê có nút \"Xuất Excel\" (báo cáo 4 sheet). File nằm "
                "trong thư mục exports/.",
    ("pdf",): "Xuất PDF: màn Hóa đơn → chọn đơn → \"Xuất PDF\", hoặc bấm trong cửa "
              "sổ chi tiết. File nằm trong thư mục exports/.",
    ("them san pham", "tao san pham"): "Thêm sản phẩm: màn Sản phẩm (cần tài khoản "
                                       "Quản lý) → điền form bên phải → \"Thêm mới\". "
                                       "Mã SKU không được trùng.",
    ("ban hang", "thanh toan", "gio hang"): "Bán hàng: tìm sản phẩm (gõ là lọc ngay), "
                                            "double-click để thêm vào giỏ. Gõ đúng mã SKU "
                                            "rồi Enter là thêm thẳng vào giỏ — dùng được với "
                                            "máy quét mã vạch. Điền khách + giảm giá rồi bấm "
                                            "THANH TOÁN.",
    ("khach",): "Màn Khách hàng: khách được tạo tự động khi thanh toán có số điện "
                "thoại. Double-click một khách để xem toàn bộ lịch sử mua.",
    ("dang nhap", "mat khau", "tai khoan"): "Tài khoản mặc định: admin/admin123 "
                                            "(Quản lý — thấy hết menu), nhanvien/123456 "
                                            "(Nhân viên — chỉ bán hàng, hóa đơn, khách hàng).",
    # "toi"/"sang" tran lan trong cau thuong ("tôi muốn...") nen phai dung
    # cum du dai moi khong khop nham
    ("giao dien", "che do toi", "che do sang", "dark mode"):
        "Đổi giao diện sáng/tối: bấm nút 🌙 ở góc dưới thanh bên trái. "
        "Lựa chọn được nhớ cho lần mở sau.",
    ("nhap hang", "ton kho"): "Nhập thêm hàng: màn Tồn kho (tài khoản Quản lý) → chọn "
                              "sản phẩm → \"Nhập thêm hàng\". Sản phẩm dưới mức tối "
                              "thiểu được tô màu cảnh báo.",
}


def _extract_product_keyword(question: str) -> tuple[str, str, bool]:
    """Tách từ khóa tìm kiếm (cả có dấu và không dấu) và kiểm tra cờ câu hỏi còn hàng."""
    raw = question.strip().rstrip("?!.,")
    q_norm = search_key(raw)

    is_asking = False
    ask_patterns = [
        r"^(?:con|co|tim|kiem|xem|muon mua|hoi ve|co ban|ban co|shop co|cua hang co)\s+",
        r"\s+(?:khong|ko|k|ha|nhi|vay|the|a|nua khong|con khong)$",
    ]
    for pat in ask_patterns:
        if re.search(pat, q_norm):
            is_asking = True
            break

    # Làm sạch bản không dấu
    cleaned_norm = re.sub(
        r"^(?:cho\s+minh\s+hoi\s+|hoi\s+|shop\s+|ad\s+|ban\s+)?(?:con\s+hang\s+|con\s+|co\s+ban\s+|co\s+|tim\s+kiem\s+|tim\s+|kiem\s+tra\s+|kiem\s+|xem\s+|san\s+pham\s+|gia\s+)?",
        "", q_norm)
    cleaned_norm = re.sub(
        r"(?:\s+khong\s+a|\s+khong|\s+k|\s+ko|\s+ha|\s+nhi|\s+nua\s+khong|\s+con\s+khong|\s+vay|\s+the|\s+a)+$",
        "", cleaned_norm).strip()
    cleaned_norm = re.sub(r"\s+(?:loai|mau)?\s*(?:nao|gi)$", "", cleaned_norm).strip()

    # Làm sạch bản gốc có dấu
    cleaned_orig = re.sub(
        r"^(?:cho\s+mình\s+hỏi\s+|hỏi\s+|shop\s+|ad\s+|bạn\s+)?(?:còn\s+hàng\s+|còn\s+|có\s+bán\s+|có\s+|tìm\s+kiếm\s+|tìm\s+|kiểm\s+tra\s+|kiểm\s+|xem\s+|sản\s+phẩm\s+|giá\s+)?",
        "", raw, flags=re.IGNORECASE)
    cleaned_orig = re.sub(
        r"(?:\s+không\s+ạ|\s+không|\s+k|\s+ko|\s+hả|\s+nhỉ|\s+nữa\s+không|\s+còn\s+không|\s+vậy|\s+thế|\s+ạ)+$",
        "", cleaned_orig, flags=re.IGNORECASE).strip()
    cleaned_orig = re.sub(r"\s+(?:loại|màu)?\s*(?:nào|gì)$", "", cleaned_orig, flags=re.IGNORECASE).strip()

    return cleaned_orig, cleaned_norm, is_asking


def _answer_product_search(question: str) -> str | None:
    """Truy vấn collection products trong MongoDB để tìm sản phẩm theo tên, danh mục hoặc SKU."""
    kw_orig, kw_norm, is_asking = _extract_product_keyword(question)
    search_term = kw_norm or search_key(question)
    if not search_term or len(search_term) < 2:
        return None

    try:
        from app.database.connection import get_db
        db = get_db()
        safe_orig = re.escape(kw_orig) if kw_orig else ""
        safe_norm = re.escape(kw_norm) if kw_norm else re.escape(search_term)

        query = {
            "is_active": True,
            "$or": [
                {"name": {"$regex": safe_norm, "$options": "i"}},
                {"name_search": {"$regex": safe_norm, "$options": "i"}},
                {"category": {"$regex": safe_norm, "$options": "i"}},
                {"sku": {"$regex": safe_norm, "$options": "i"}},
            ]
        }
        if safe_orig:
            query["$or"].extend([
                {"name": {"$regex": safe_orig, "$options": "i"}},
                {"category": {"$regex": safe_orig, "$options": "i"}},
            ])

        matched = list(db.products.find(query).limit(10))
    except Exception:
        return None

    if matched:
        kw_display = kw_orig if kw_orig else kw_norm
        lines = [f"Tìm thấy {len(matched)} sản phẩm phù hợp với '{kw_display}':"]
        for p in matched:
            name = p.get("name", "Sản phẩm")
            price_str = money(p.get("price", 0))
            stock = p.get("stock", 0)
            stock_str = f"còn {stock} cái" if stock > 0 else "đã hết hàng"
            lines.append(f"• {name} — Giá: {price_str} (Tồn kho: {stock_str})")
        return "\n".join(lines)

    if is_asking and len(search_term) >= 2:
        kw_display = kw_orig if kw_orig else kw_norm
        return f"Hiện không tìm thấy sản phẩm nào khớp với '{kw_display}' trong cửa hàng."

    return None


def _ask_rules(question: str) -> str:
    q = search_key(question)

    if any(w in q for w in ("chao", "hello", "hi ", "xin chao")) and len(q) < 25:
        return ("Chào bạn! Mình là trợ lý của TechStore. Hỏi mình về doanh thu, "
                "tồn kho, sản phẩm bán chạy, khách hàng hoặc cách dùng phần mềm nhé.")

    # cau hoi "cach ...": tra cuu bang huong dan truoc
    if any(w in q for w in ("cach", "lam sao", "lam the nao", "huong dan",
                            "o dau", "the nao")):
        for keywords, answer in USAGE.items():
            if any(k in q for k in keywords):
                return answer

    if "doanh thu" in q or "ban duoc bao nhieu" in q:
        return _answer_revenue(q)
    if "sap het" in q or "het hang" in q or "ton kho" in q:
        return _answer_low_stock()
    if "ban chay" in q or "top" in q or "ban nhieu" in q:
        return _answer_top_products(q)
    if "khach" in q:
        return _answer_customers()
    if "hoa don" in q or "don hang" in q or "gan day" in q:
        return _answer_recent_orders()
    if "loi nhuan" in q or "lai" in q:
        return _answer_profit(q)

    # van la cau hoi cach dung nhung khong mo dau bang "cach..."
    for keywords, answer in USAGE.items():
        if any(k in q for k in keywords):
            return answer

    # Tìm kiếm sản phẩm trong database MongoDB thay vì trả về HELP_TEXT
    product_ans = _answer_product_search(question)
    if product_ans:
        return product_ans

    return HELP_TEXT


# ---------- che do GEMINI API ----------

def _ask_gemini(question: str, history: list[dict]) -> str:
    import google.generativeai as genai

    api_key = os.getenv("GEMINI_API_KEY")
    genai.configure(api_key=api_key)

    # Kiểm tra xem người dùng có hỏi một tháng cụ thể nào không
    q_normalized = search_key(question)
    month, year = _extract_month_year(q_normalized)
    
    extra_context = ""
    if month and year:
        from calendar import monthrange
        start_date = datetime(year, month, 1)
        last_day = monthrange(year, month)[1]
        end_date = datetime(year, month, last_day)
        
        specific_stats = report_service.summary(start_date, end_date)
        extra_context = (
            f"\n--- SỐ LIỆU YÊU CẦU CHO THÁNG {month}/{year} ---\n"
            f"Doanh thu tháng {month}/{year}: {money(specific_stats['revenue'])}, "
            f"Lợi nhuận: {money(specific_stats.get('profit', 0))}, "
            f"{specific_stats['orders']} đơn hàng, {specific_stats['products_sold']} sản phẩm bán ra."
        )

    # Kết hợp cẩm nang RAG, số liệu chung và số liệu cụ thể theo tháng nếu có
    relevant_knowledge = query_rag_context(question, n_results=2)

    try:
        data_summary = _data_snapshot()
    except Exception:
        data_summary = "Không thể lấy số liệu thực tế tại thời điểm này."

    system_instruction = (
        f"{APP_GUIDE}\n\n"
        f"--- TÀI LIỆU LIÊN QUAN (RAG) ---\n{relevant_knowledge}\n\n"
        f"--- SỐ LIỆU THỰC TẾ HỆ THỐNG ---\n{data_summary}"
        f"{extra_context}"
    )

    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=system_instruction
    )

    chat_history = []
    for h in history:
        role = "user" if h["role"] == "user" else "model"
        chat_history.append({
            "role": role,
            "parts": [h["content"]]
        })

    chat = model.start_chat(history=chat_history)
    response = chat.send_message(
        question,
        request_options={"timeout": 15.0, "retry": None}
    )
    
    return response.text


def _extract_month_year(q: str):
    """Bóc tách tháng và năm từ câu hỏi nếu có (ví dụ: tháng 5/2026, tháng 5 năm 2026)."""
    match = re.search(r"thang\s*(\d{1,2})[/\s-]*(?:nam\s*)?(\d{4})", q)
    if match:
        month = int(match.group(1))
        year = int(match.group(2))
        return month, year
    return None, None


QUICK_GREETING_ANSWER = (
    "Chào bạn! Mình là trợ lý AI của TechStore. "
    "Hỏi mình về doanh thu, tồn kho, sản phẩm bán chạy, khách hàng hoặc cách dùng phần mềm nhé!"
)


def _is_quick_greeting(question: str) -> bool:
    """Kiểm tra nhanh các câu chào hỏi thông dụng để phản hồi tức thì."""
    q = search_key(question).strip().rstrip("?!.,")
    # Bỏ các từ đệm cuối câu (ạ, nha, nhé, ơi...)
    q = re.sub(r"(?:\s+a|\s+nha|\s+nhe|\s+oi|\s+nhie)+$", "", q).strip()

    quick_set = {
        "alo", "alo shop", "alo ad", "alo bot", "alo ban",
        "hi", "hi ban", "hi shop", "hi ad", "hi bot", "hi all", "hi cac ban",
        "hello", "hello ban", "hello shop", "hello ad", "hello bot", "hello all",
        "hey", "hey shop", "hey bot", "hey ad",
        "chao", "chao ban", "chao shop", "chao ad", "chao bot", "chao em", "chao anh", "chao chi", "chao mn", "chao moi nguoi",
        "xin chao", "xin chao ban", "xin chao shop", "xin chao ad", "xin chao bot", "xin chao moi nguoi"
    }
    return q in quick_set


def _handle_quota_exceeded(question: str) -> str:
    """Ghi log cảnh báo hết quota (429) và chuyển sang trả lời bằng dữ liệu nội bộ."""
    print("\n>>> [CẢNH BÁO QUOTA - LỖI 429]: Gemini API đã hết lượt gọi miễn phí!\n")
    return _ask_rules(question) + "\n\n(Thông báo: Gemini API hiện đã hết quota, hệ thống đang trả lời bằng dữ liệu nội bộ.)"


def ask(question: str, history: list[dict] | None = None) -> str:
    question = (question or "").strip()
    if not question:
        return HELP_TEXT

    # 1. Bắt nhanh các câu chào hỏi thông dụng, phản hồi tức thì không cần gọi RAG/API
    if _is_quick_greeting(question):
        return QUICK_GREETING_ANSWER

    if has_api():
        try:
            return _ask_gemini(question, history or [])
        except ResourceExhausted:
            return _handle_quota_exceeded(question)
        except (ServiceUnavailable, DeadlineExceeded):
            print("\n>>> [CẢNH BÁO KẾT NỐI]: Máy chủ Google quá tải hoặc phản hồi chậm.\n")
            return _ask_rules(question) + "\n\n(Thông báo: Kết nối tới Gemini AI đang gián đoạn, hệ thống tạm chuyển sang chế độ offline.)"
        except Exception as e:
            err_msg = str(e).lower()
            if "429" in err_msg or "quota" in err_msg:
                return _handle_quota_exceeded(question)
            print(f"\n>>> [LỖI GEMINI]: {e}\n")
            return _ask_rules(question)
    return _ask_rules(question)