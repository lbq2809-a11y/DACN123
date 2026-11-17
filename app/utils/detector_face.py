import cv2
import os
import time
import numpy as np
import threading
from pathlib import Path
from deepface import DeepFace
from app.database.connection import get_db
from tkinter import messagebox

def draw_hud_face_box(img, x, y, w, h, label_text="", color=(0, 140, 255), thickness=3, line_length=40, progress=1.0, elapsed_time=0.0, state_manager=None):
    padding_x = int(w * 0.3)
    padding_top = int(h * 0.2)
    padding_bottom = int(h * 0.1) - 5
    
    x_new = max(0, x - padding_x)
    y_new = max(0, y - padding_top - 20)
    w_new = w + (padding_x * 2)
    h_new = (y + h + padding_bottom) - y_new

    # Top-left
    cv2.line(img, (x_new, y_new), (x_new + line_length, y_new), color, thickness, cv2.LINE_AA)
    cv2.line(img, (x_new, y_new), (x_new, y_new + line_length), color, thickness, cv2.LINE_AA)
    # Top-right
    cv2.line(img, (x_new + w_new, y_new), (x_new + w_new - line_length, y_new), color, thickness, cv2.LINE_AA)
    cv2.line(img, (x_new + w_new, y_new), (x_new + w_new, y_new + line_length), color, thickness, cv2.LINE_AA)
    # Bottom-left
    cv2.line(img, (x_new, y_new + h_new), (x_new + line_length, y_new + h_new), color, thickness, cv2.LINE_AA)
    cv2.line(img, (x_new, y_new + h_new), (x_new, y_new + h_new - line_length), color, thickness, cv2.LINE_AA)
    # Bottom-right
    cv2.line(img, (x_new + w_new, y_new + h_new), (x_new + w_new - line_length, y_new + h_new), color, thickness, cv2.LINE_AA)
    cv2.line(img, (x_new + w_new, y_new + h_new), (x_new + w_new, y_new + h_new - line_length), color, thickness, cv2.LINE_AA)
    # Rectangle
    margin = 10
    cv2.rectangle(img, (x_new - margin, y_new - margin), (x_new + w_new + margin, y_new + h_new + margin), (0, 255, 0), 1, cv2.LINE_AA)
    # Line 1
    m1 = 3
    cv2.line(img, (x_new + line_length*2, y_new - m1), (x_new + w_new - line_length*2, y_new - m1), (150, 255, 150), 1, cv2.LINE_AA)
    cv2.line(img, (x_new + line_length*2, y_new + h_new + m1), (x_new + w_new - line_length*2, y_new + h_new + m1), (150, 255, 150), 1, cv2.LINE_AA)
    cv2.line(img, (x_new - m1, y_new + line_length*2), (x_new - m1, y_new + int(h_new * 0.5) - 10), (150, 255, 150), 1, cv2.LINE_AA)
    cv2.line(img, (x_new - m1, y_new + int(h_new * 0.5) + 10), (x_new - m1, y_new + h_new - line_length*2), (150, 255, 150), 1, cv2.LINE_AA)
    cv2.line(img, (x_new + w_new + m1, y_new + line_length*2), (x_new + w_new + m1, y_new + int(h_new * 0.5) - 10), (150, 255, 150), 1, cv2.LINE_AA)
    cv2.line(img, (x_new + w_new + m1, y_new + int(h_new * 0.5) + 10), (x_new + w_new + m1, y_new + h_new - line_length*2), (150, 255, 150), 1, cv2.LINE_AA)
    # Line 2
    m2 = int(margin * 0.5)
    cv2.line(img, (x_new - m2, y_new + int(h_new * 0.5)), (x_new + line_length + m2, y_new + int(h_new * 0.5)), color, thickness, cv2.LINE_AA)
    cv2.line(img, (x_new + w_new + m2, y_new + int(h_new * 0.5)), (x_new + w_new - line_length - m2, y_new + int(h_new * 0.5)), color, thickness, cv2.LINE_AA)

    # Label
    if label_text:
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.65
        thickness_text = 2
        (text_w, text_h), baseline = cv2.getTextSize(label_text, font, font_scale, thickness_text)
        
        # Tọa độ nền chứa text bên dưới khung
        box_x1 = x_new + int(line_length * 0.5)
        box_y1 = y_new + h_new + 10

        # Định nghĩa độ rộng tối thiểu cho thanh ngang để chứa chữ + khoảng đệm padding
        padding_text = 20
        min_bar_width = text_w + (padding_text * 2)
        
        # Điểm bắt đầu và kết thúc của thanh ngang (đảm bảo luôn đủ chỗ cho tên dài)
        hx_start = box_x1 + 25
        hx_end = max(x_new + w_new + 5, hx_start + min_bar_width)
        
        # 2. Tính toán tọa độ X để chữ nằm CHÍNH GIỮA khoảng không gian của thanh ngang
        bar_width = hx_end - hx_start
        text_x = hx_start + (bar_width - text_w) // 2
        text_y = box_y1 + 40 - margin

        # Tọa độ đích của toàn bộ đường line
        target_x2 = box_x1 + 25
        target_y2 = box_y1 + 40
        target_x3 = hx_end

        # Nội suy độ dài nét vẽ dựa trên progress (từ 0.0 đến 1.0)
        current_len_progress = progress * (target_x3 - box_x1)

        if current_len_progress > 0:
            p1_x = int(box_x1 + min(25, current_len_progress))
            p1_y = int(box_y1 + min(40, (current_len_progress / 25) * 40))
            cv2.line(img, (box_x1, box_y1), (p1_x, p1_y), (255, 255, 255), thickness_text, cv2.LINE_AA)

        if current_len_progress > 25:
            horiz_len = current_len_progress - 25
            max_horiz_len = target_x3 - target_x2
            p2_x = int(target_x2 + min(max_horiz_len, horiz_len))
            cv2.line(img, (target_x2, target_y2), (p2_x, target_y2), (255, 255, 255), thickness_text, cv2.LINE_AA)

        # Chữ hiện lên khi đường line đã chạy được > 80% tiến trình
        if progress >= 0.8:
            cv2.putText(img, label_text, (text_x, text_y), font, font_scale, (0, 0, 255), thickness_text + 1, cv2.LINE_AA)
            cv2.putText(img, label_text, (text_x, text_y), font, font_scale, (255, 255, 255), thickness_text, cv2.LINE_AA)

        anim_duration = 0.7
        delay_time = 1

        if elapsed_time >= anim_duration + delay_time:
            clear_text = "SUCCESS"
            font_clear = cv2.FONT_HERSHEY_SIMPLEX
            scale_clear = 3
            thick_clear = 10
            img_h, img_w, _ = img.shape
            
            # Tính kích thước chữ CLEAR
            (cw, ch), c_base = cv2.getTextSize(clear_text, font_clear, scale_clear, thick_clear)

            # Cấu hình kích thước Banner
            banner_w = cw + 140
            banner_h = ch + 80
            
            # Tính tọa độ để đặt Banner vào CHÍNH GIỮA MÀN HÌNH
            bx1 = (img_w - banner_w) // 2
            by1 = (img_h - banner_h) // 2
            bx2 = bx1 + banner_w
            by2 = by1 + banner_h

            # --- 1. TẠO PHẦN NỀN TRONG SUỐT (SEMI-TRANSPARENT GREEN) ---
            overlay = img.copy()
            
            # Đỉnh đa giác vắt góc top-left (Chamfer corner)
            cut_size = 25
            pts = np.array([
                [bx1 + cut_size, by1],       # Top-left (vắt chéo)
                [bx2, by1],                  # Top-right
                [bx2, by2],                  # Bottom-right
                [bx1, by2],                  # Bottom-left
                [bx1, by1 + cut_size]        # Điểm nối vắt chéo
            ], np.int32)
            pts = pts.reshape((-1, 1, 2))

            # Tô màu nền xanh lục Sci-Fi (BGR: Green-Yellowish)
            cv2.fillPoly(overlay, [pts], (40, 220, 80))

            # Trộn overlay để tạo độ trong suốt (alpha = 0.7)
            alpha = 0.7
            cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)

            # --- 2. VẼ VIỀN BẢNG HUD (BORDER & ACCENT CORNER) ---
            cv2.polylines(img, [pts], isClosed=True, color=(100, 255, 150), thickness=2, lineType=cv2.LINE_AA)
            cv2.line(img, (bx1, by1 + cut_size), (bx1 + cut_size, by1), (0, 255, 255), 2, cv2.LINE_AA)

            # --- 3. VẼ CHỮ "SUCCESS" CÓ VIỀN TẠO HIỆU ỨNG NỔI (STROKE TEXT) ---
            tx = bx1 + (banner_w - cw) // 2
            ty = by1 + (banner_h + ch) // 2 - 4

            # --- 4. VẼ THÊM HÌNH TAM GIÁC VUÔNG
            offset_x = 24   # Khoảng cách lùi sang trái/phải
            offset_y = -1  # Khoảng cách dịch dọc (giảm xuống để kéo tam giác thấp xuống sát góc khuyết)
            tri_size = 15  # Kích thước cạnh tam giác
            
            base_x = (bx1 + cut_size) - offset_x
            base_y = by1 - offset_y

            tri_pts = np.array([
                [base_x, base_y],                               # Đỉnh góc vuông
                [base_x + tri_size, base_y],                    # Cạnh kéo dài sang phải
                [base_x, base_y + tri_size]                     # Cạnh kéo dài xuống dưới
            ], np.int32)
            tri_pts = tri_pts.reshape((-1, 1, 2))
            tri_overlay = img.copy()
            # Tô màu nền và vẽ viền sắc nét cho tam giác
            cv2.fillPoly(overlay, [tri_pts], (40, 200, 80))
            cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)
            cv2.polylines(img, [tri_pts], isClosed=True, color=(40, 255, 80), thickness=2, lineType=cv2.LINE_AA)

            # Viền ngoài chữ
            cv2.putText(img, clear_text, (tx, ty), font_clear, scale_clear, (10, 60, 20), thick_clear + 3, cv2.LINE_AA)
            # Lớp chữ chính màu trắng sáng ở giữa
            cv2.putText(img, clear_text, (tx, ty), font_clear, scale_clear, (255, 255, 255), thick_clear, cv2.LINE_AA)
            if state_manager is not None and not state_manager.get("audio_played", False):
                state_manager["audio_played"] = True
                try:
                    import threading
                    import winsound
                    def play_rapid_beeps():
                        try:
                            winsound.Beep(2500, 300)
                        except Exception:
                            print("\a\a")
                    threading.Thread(target=play_rapid_beeps, daemon=True).start()
                except Exception:
                    print("\a\a")
        
BASE_DIR = Path(__file__).resolve().parent.parent.parent
FACE_IMAGES_DIR = BASE_DIR / "data" / "face_images"
os.makedirs(FACE_IMAGES_DIR, exist_ok=True)


def resolve_image_path(raw_path: str) -> str:
    """
    Chuẩn hóa và phân giải đường dẫn ảnh khuôn mặt mẫu:
    - Nếu đường dẫn hiện tại (tuyệt đối hoặc tương đối theo BASE_DIR) tồn tại trên ổ cứng -> trả về đường dẫn đó.
    - Nếu đường dẫn cũ trong DB có dạng 'D:/Image/xyz.jpg' hoặc 'D:\\Image\\xyz.jpg' không tồn tại ở ổ D,
      tách lấy tên file 'xyz.jpg' và tìm trong TechStore/data/face_images/xyz.jpg.
    """
    if not raw_path:
        return ""

    raw_str = str(raw_path).strip()
    if os.path.exists(raw_str):
        return str(Path(raw_str).resolve())

    rel_candidate = BASE_DIR / raw_str
    if rel_candidate.exists():
        return str(rel_candidate.resolve())

    # Tách lấy tên file (hỗ trợ cả '/' và '\' từ đường dẫn cũ như D:/Image/xyz.jpg hoặc D:\Image\xyz.jpg)
    filename = os.path.basename(raw_str.replace("\\", "/"))
    fallback_candidate = FACE_IMAGES_DIR / filename
    if fallback_candidate.exists():
        return str(fallback_candidate.resolve())

    return str(fallback_candidate)


def verify_face_from_camera(username_input):
    if not username_input:
        return False, "Vui lòng nhập tên đăng nhập trước khi xác thực khuôn mặt!", None

    db = get_db()
    user = db.users.find_one({"username": username_input})
    
    if not user:
        return False, f"Không tìm thấy tài khoản '{username_input}' trong hệ thống!", None

    # Hỗ trợ đa ảnh mẫu (Multi-sample)
    stored_paths = user.get("image_paths", [])
    if not stored_paths and user.get("image_path"):
        stored_paths = [user.get("image_path")]

    print(f"\n[DEBUG Face] Danh sách đường dẫn ảnh mẫu từ DB ({username_input}): {stored_paths}")

    # 1. Đảm bảo chạy hoàn toàn Offline: cấu hình DEEPFACE_HOME trỏ tới thư mục weights cục bộ nếu có
    for candidate in [BASE_DIR, BASE_DIR / ".deepface", Path.home() / ".deepface"]:
        if (candidate / "weights" / "arcface_weights.h5").exists():
            os.environ["DEEPFACE_HOME"] = str(candidate.parent if candidate.name == ".deepface" else candidate)
            break

    # Lọc lại các đường dẫn file ảnh mẫu thực sự tồn tại trên ổ cứng qua resolve_image_path
    valid_stored_paths = []
    for p in stored_paths:
        resolved_p = resolve_image_path(p)
        exists = os.path.exists(resolved_p)
        print(f"[DEBUG Face] Resolve: '{p}' -> '{resolved_p}' | Tồn tại trên ổ cứng: {exists}")
        if exists:
            valid_stored_paths.append(resolved_p)
    
    if not valid_stored_paths:
        return False, f"Tài khoản '{username_input}' chưa đăng ký ảnh khuôn mặt mẫu nào trong hệ thống!", None

    # 1. Mở Webcam quét liên tục
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return False, "Không thể kết nối với Webcam!", None
    
    messagebox.showinfo("Thông báo", f"Hệ thống nhận diện khuôn mặt. Hãy nhìn thẳng, xoay nhẹ trái/phải, tìm được khung hình khớp sẽ tự động đăng nhập!")

    cascade_path = str(BASE_DIR / "haarcascade_frontalface_default.xml")
    face_cascade = cv2.CascadeClassifier(cascade_path) if os.path.exists(cascade_path) else None

    if not face_cascade:
        cap.release()
        return False, "Không tìm thấy file Haar Cascade để nhận diện mặt!", None

    start_time = time.time()
    TIMEOUT = 15.0           # Quét tối đa 15 giây
    CHECK_INTERVAL = 0.4     # Khoảng thời gian tối thiểu giữa 2 lần đẩy frame vào luồng AI
    last_check_time = 0.0

    success_start_time = None
    success_result = None
    hud_state = {"audio_played": False}
    CUSTOM_THRESHOLD = 0.25  # Ngưỡng của mô hình ArcFace

    # Bộ nhớ đệm lưu đặc trưng (embedding) của các ảnh mẫu đã trích xuất bằng detector_backend="opencv"
    sample_embeddings_cache = {}

    # Biến trạng thái và Lock đồng bộ đa luồng (Threading)
    thread_lock = threading.Lock()
    is_verifying = False
    verified_success = False

    def async_verification_worker(face_rgb_img, sample_paths, user_data):
        nonlocal is_verifying, verified_success, success_result
        try:
            for sample_path in sample_paths:
                with thread_lock:
                    if verified_success:
                        break
                try:
                    # Đối với img1_path (ảnh mẫu từ ổ cứng): dùng detector_backend="opencv" để trích xuất khuôn mặt
                    # và đồng bộ hệ màu RGB với face_rgb_img
                    if sample_path not in sample_embeddings_cache:
                        sample_bgr = cv2.imread(sample_path)
                        if sample_bgr is not None:
                            sample_rgb = cv2.cvtColor(sample_bgr, cv2.COLOR_BGR2RGB)
                            repr_objs = DeepFace.represent(
                                img_path=sample_rgb,
                                model_name="ArcFace",
                                detector_backend="opencv",
                                enforce_detection=False
                            )
                        else:
                            repr_objs = DeepFace.represent(
                                img_path=sample_path,
                                model_name="ArcFace",
                                detector_backend="opencv",
                                enforce_detection=False
                            )
                        sample_embeddings_cache[sample_path] = repr_objs[0]["embedding"]

                    img1_source = sample_embeddings_cache[sample_path]

                    # Đối với img2_path (face_rgb_img đã được crop sẵn khuôn mặt và đổi sang RGB):
                    # đặt detector_backend="skip" và enforce_detection=False
                    result = DeepFace.verify(
                        img1_path=img1_source,
                        img2_path=face_rgb_img,
                        model_name="ArcFace",
                        distance_metric="cosine",
                        detector_backend="skip",
                        enforce_detection=False
                    )
                    dist = result.get("distance", 1.0)
                    print(f"[DEBUG Face] File: {sample_path} | Distance: {dist:.4f} | Ngưỡng: {CUSTOM_THRESHOLD}")

                    if dist <= CUSTOM_THRESHOLD:
                        with thread_lock:
                            verified_success = True
                            success_result = (True, "Xác thực thành công!", user_data)
                        # Tìm thấy 1 ảnh mẫu đạt ngưỡng -> lập tức break, không quét tiếp
                        break
                except Exception as e:
                    print(f"[DEBUG Face Error]: {e}")
                    continue
        finally:
            with thread_lock:
                is_verifying = False

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        frame = cv2.flip(frame, 1)
        display_frame = frame.copy()
        
        current_time = time.time()
        elapsed = current_time - start_time
        remaining_time = max(0, int(TIMEOUT - elapsed))

        # Phát hiện mặt để vẽ khung xanh hướng dẫn (chạy nhanh trên main thread)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(80, 80))

        # Kiểm tra kết quả từ luồng ngầm
        with thread_lock:
            if verified_success and success_start_time is None:
                success_start_time = current_time

        if success_start_time is not None:
            elapsed_success = current_time - success_start_time
            if elapsed_success >= 3.0:
                break
            if 'anim_start_time' not in locals() or anim_start_time is None:
                anim_start_time = current_time
            anim_duration = 0.7
            progress = min(1.0, (current_time - anim_start_time) / anim_duration)
            for (x, y, w, h) in faces:
                draw_hud_face_box(display_frame, x, y, w, h, label_text=username_input.upper(), color=(0, 200, 0), thickness=3, progress=progress, elapsed_time=elapsed_success, state_manager=hud_state)

        else:
            if len(faces) > 0:
                for (x, y, w, h) in faces:
                    draw_hud_face_box(display_frame, x, y, w, h, label_text="", color=(0, 140, 255), thickness=3)

        window_name = "Face Login"
        cv2.imshow(window_name, display_frame)

        if cv2.waitKey(1) & 0xFF == 27 or cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:  # Hủy đăng nhập
            break

        if elapsed >= TIMEOUT and success_start_time is None:
            break

        # Nếu chưa xác thực và luồng so khớp đang rảnh -> Cắt khuôn mặt, resize (112, 112), đổi sang RGB và gửi vào background thread
        with thread_lock:
            can_dispatch = (not is_verifying) and (not verified_success)

        if can_dispatch and (current_time - last_check_time >= CHECK_INTERVAL) and len(faces) > 0:
            last_check_time = current_time
            
            try:
                # Cắt mặt lớn nhất từ frame gốc (tương đồng với cách detector_backend="opencv" cắt trên ảnh mẫu)
                (x, y, w, h) = max(faces, key=lambda f: f[2] * f[3])
                cropped = frame[y:y+h, x:x+w]

                if cropped.shape[0] > 50 and cropped.shape[1] > 50:
                    face_crop = cropped
                else:
                    face_crop = frame

                # Resize nhẹ frame về kích thước chuẩn của ArcFace (112, 112) để tối ưu tải tính toán
                face_crop = cv2.resize(face_crop, (112, 112), interpolation=cv2.INTER_AREA)

                # Đổi hệ màu từ BGR sang RGB trước khi truyền vào DeepFace
                face_rgb = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)

                with thread_lock:
                    is_verifying = True

                # Đẩy toàn bộ tác vụ so khớp DeepFace vào background thread riêng biệt
                worker_thread = threading.Thread(
                    target=async_verification_worker,
                    args=(face_rgb.copy(), valid_stored_paths, user),
                    daemon=True
                )
                worker_thread.start()

            except Exception as e:
                print(f"[DEBUG Face Error]: {e}")
                with thread_lock:
                    is_verifying = False

    cap.release()
    cv2.destroyAllWindows()

    if success_result:
        return success_result
    else:
        return False, "Hết thời gian quét hoặc không tìm thấy góc khuôn mặt nào khớp!", None