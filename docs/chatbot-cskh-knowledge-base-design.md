# Thiết kế bộ dữ liệu (Knowledge Base + Business Flow) cho Chatbot CSKH Delippy

> Tài liệu phân tích nghiệp vụ (BA + Solution Architect). Không chứa code, JSON, YAML hay thuật toán — chỉ mô tả kiến trúc dữ liệu và thiết kế nghiệp vụ để đội phát triển hiện thực hoá.

## 0. Bối cảnh và nguyên tắc kiến trúc

### 0.1 Vì sao tài liệu này tồn tại

Delippy là app **social commerce / live shopping marketplace** (2 vai trò `seller` và `user`, có livestream bán hàng qua Agora). Module chatbot hiện tại (`lib/features/user/chatbot/`) đã có 2 "mode":

- **Mode `chat`** — AI gợi ý/tìm sản phẩm, đã hoạt động, gọi thẳng một microservice AI ngoài backend chính (`POST /api/v1/chat`).
- **Mode `help`** — chăm sóc khách hàng, hiện đang **khoá** trên UI (bấm vào chỉ hiện thông báo "tính năng đang phát triển"). Đây chính là phần cần bộ dữ liệu mà tài liệu này thiết kế.

Điểm quan trọng cần lưu ý xuyên suốt: nhiều domain nghiệp vụ CSKH (đổi trả, hoàn tiền, bảo hành) **hiện chưa có API thật ở backend chính** — ví dụ `return_request` mới chỉ có local data source, chưa có remote API; không có model "refund" hay "warranty" riêng. Tài liệu này thiết kế bộ data ở mức đầy đủ như một hệ thống CSKH trưởng thành cần có; phần "API cần gọi" của từng domain sẽ ghi rõ trạng thái **[ĐÃ CÓ]** hay **[CẦN BỔ SUNG]** dựa trên khảo sát codebase hiện tại, để đội backend biết cần xây thêm gì.

### 0.2 Kiến trúc xử lý

Rule Engine → Intent Detection → Business Flow → API → Response Template.

- **Rule Engine**: lớp đầu tiên nhận input, chuẩn hoá câu (bỏ dấu câu thừa, lowercase để match keyword), áp các rule cứng có độ ưu tiên cao (ví dụ: chứa số đơn hàng dạng `DELXXXXXXXX` → chắc chắn thuộc domain Order/Shipping) trước khi giao cho tầng intent.
- **Intent Detection (LLM)**: chỉ dùng LLM để hiểu câu tự nhiên, chấm điểm intent, và trích entity. LLM **không được** tự sinh câu trả lời nghiệp vụ (số tiền, chính sách, trạng thái đơn) — mọi con số/chính sách phải lấy từ Knowledge Base hoặc API.
- **Business Flow**: máy trạng thái (state machine) hội thoại, quyết định bước tiếp theo — hỏi thêm entity còn thiếu, gọi API, hay escalate CSKH người thật.
- **API**: lớp gọi dịch vụ backend thật để lấy dữ liệu động (trạng thái đơn, số tiền hoàn...). Static knowledge (chính sách, FAQ) không cần API, chỉ đọc từ Knowledge Base.
- **Response Template**: câu trả lời luôn được ghép từ template có sẵn + biến số lấy từ API/KB. Không có phần nào do LLM tự do sinh nội dung nghiệp vụ.

### 0.3 Quy ước chung áp dụng cho mọi domain

- **Định danh thực thể**: mọi domain tham chiếu chéo bằng ID chuẩn hoá — `order_id`, `user_id`, `product_id`, `seller_id`, `return_request_id`, `payment_transaction_id`, `ticket_id`. Không dùng tên hiển thị để join dữ liệu.
- **Ngôn ngữ**: knowledge base lưu song song **có dấu** và **bản chuẩn hoá không dấu/lowercase** cho keyword/synonym, vì người dùng Việt Nam gõ tắt, không dấu, sai chính tả rất phổ biến (ví dụ "hoan tien", "hủy đơn", "ship").
- **Độ tin cậy (confidence)**: mỗi domain phải khai báo ngưỡng confidence intent tối thiểu để tự động trả lời; dưới ngưỡng → hỏi lại làm rõ; dưới ngưỡng thấp hơn nữa hoặc lặp lại 2 lần không rõ → escalate CSKH.
- **Escalation CSKH** là một domain xuyên suốt (không phải domain riêng trong 18 domain, mà là hành vi chung): mọi domain đều có "cửa thoát" sang người thật khi (a) không đủ entity sau N lần hỏi, (b) API lỗi/timeout, (c) người dùng yêu cầu gặp người thật, (d) tình huống nhạy cảm (khiếu nại, tố cáo gian lận, yêu cầu pháp lý).
- **Logging & Analytics**: mọi lượt hội thoại đều ghi lại tối thiểu — session_id, user_id (nếu đăng nhập), domain, intent, entity trích được, confidence, API đã gọi, kết quả (trả lời/escalate/bỏ dở), thời gian phản hồi. Đây là input cho phân tích ở mục Analytics của từng domain và để huấn luyện lại rule/intent.

### 0.4 Danh sách 18 domain

| # | Domain | Vai trò chính |
|---|--------|----------------|
| 01 | company | Thông tin công ty, pháp lý, giới thiệu |
| 02 | account | Đăng ký/đăng nhập/trạng thái tài khoản |
| 03 | order | Vòng đời và tra cứu đơn hàng |
| 04 | payment | Thanh toán, giao dịch, hoá đơn |
| 05 | shipping | Vận chuyển, tracking, giao nhận |
| 06 | return_refund | Đổi trả và hoàn tiền |
| 07 | warranty | Bảo hành sản phẩm |
| 08 | profile | Thông tin cá nhân, địa chỉ, sổ địa chỉ |
| 09 | promotion | Voucher, mã giảm giá, chương trình khuyến mãi |
| 10 | policy | Chính sách chung của sàn |
| 11 | security | Bảo mật tài khoản, chống gian lận |
| 12 | contact | Kênh liên hệ CSKH |
| 13 | faq | Câu hỏi thường gặp không thuộc domain nghiệp vụ cụ thể |
| 14 | error_message | Thư viện thông báo lỗi chuẩn hoá |
| 15 | tool | Danh mục "công cụ" (API/action) mà business flow có thể gọi |
| 16 | dictionary | Từ điển thuật ngữ, viết tắt, chuẩn hoá ngôn ngữ dùng chung |
| 17 | response_template | Kho mẫu câu trả lời dùng chung |
| 18 | business_flow | Danh mục và cấu hình các luồng hội thoại |

(01–14 là domain **nội dung nghiệp vụ**; 15–18 là domain **hạ tầng/dùng chung**, được mọi domain nghiệp vụ tham chiếu tới — mô tả ở cuối tài liệu theo cách diễn giải phù hợp với vai trò hạ tầng của chúng.)

---

## 01_company — Thông tin công ty

**1. Mục đích**: trả lời các câu hỏi về Delippy là ai, mô hình kinh doanh (marketplace + livestream), pháp lý, để tăng độ tin cậy và giảm câu hỏi lặp cho CSKH người thật.

**2. Dữ liệu cần lưu**: tên pháp nhân, mã số thuế/giấy phép kinh doanh, mô hình hoạt động (sàn TMĐT trung gian giữa seller và người mua — không phải Delippy trực tiếp bán hàng), địa chỉ trụ sở, giờ làm việc tổng đài, các mốc lịch sử/quy mô (tuỳ chính sách truyền thông), liên kết điều khoản sử dụng/chính sách bảo mật.

**3. Cấu trúc**: bản ghi tĩnh dạng "hồ sơ công ty" (key–value), không có vòng đời, không có trạng thái; version hoá theo ngày cập nhật để chatbot luôn trả lời bản mới nhất.

**4. Quan hệ với domain khác**: nền tảng cho `10_policy` (chính sách dẫn chiếu ngược lại pháp nhân), `12_contact` (kênh liên hệ chính thức), `11_security` (khẳng định kênh chính thức để chống giả mạo/lừa đảo).

**5. Intent**: `hoi_gioi_thieu_cong_ty`, `hoi_phap_ly_cong_ty`, `hoi_mo_hinh_hoat_dong`, `xac_minh_kenh_chinh_thuc` (khi nghi ngờ lừa đảo mạo danh Delippy).

**6. Entity**: không cần trích entity động — domain gần như trả lời tĩnh; entity duy nhất có thể xuất hiện là `chu_de_hoi` (giới thiệu/pháp lý/mô hình) để chọn đúng template.

**7. Keyword**: "Delippy là gì", "công ty nào", "sàn của ai", "giấy phép kinh doanh", "trụ sở ở đâu".

**8. Synonym**: "Delippy" ~ "app Delippy" ~ "sàn Delippy"; "công ty" ~ "đơn vị vận hành" ~ "chủ sàn".

**9. Business Flow**: nhận diện intent → không cần hỏi thêm gì (không có entity bắt buộc) → trả lời trực tiếp bằng template tĩnh từ Knowledge Base.

**10. Response Template**: mẫu giới thiệu ngắn (1 đoạn), mẫu pháp lý (kèm mã số thuế/giấy phép nếu được phép công khai), mẫu "xác minh kênh chính thức" dùng khi người dùng nghi ngờ bị lừa đảo mạo danh.

**11. API cần gọi**: không cần API động — dữ liệu tĩnh đọc trực tiếp từ Knowledge Base, do nội dung ít thay đổi và không phụ thuộc theo user.

**12. Điều kiện gọi API**: N/A.

**13. Validation**: kiểm tra Knowledge Base không có bản ghi hết hạn (ví dụ đổi địa chỉ trụ sở) — cảnh báo nội bộ nếu bản ghi quá cũ (ví dụ > 12 tháng chưa review).

**14. Exception**: nếu câu hỏi lẫn giữa "công ty Delippy" và "shop/seller cụ thể trên sàn" (rất dễ nhầm vì marketplace có nhiều seller) → phải làm rõ trước khi trả lời, tránh nhận nhầm trách nhiệm pháp lý của seller thành của Delippy.

**15. Escalation CSKH**: câu hỏi pháp lý phức tạp (tranh chấp hợp đồng, yêu cầu văn bản chính thức, cơ quan chức năng liên hệ) → escalate ngay, không trả lời tự động.

**16. Logging**: ghi nhận tần suất hỏi để phát hiện làn sóng nghi ngờ lừa đảo mạo danh (spike bất thường ở intent `xac_minh_kenh_chinh_thuc`).

**17. Analytics**: tỷ lệ câu hỏi công ty/pháp lý theo thời gian; dùng để phát hiện khủng hoảng truyền thông sớm.

---

## 02_account — Tài khoản (đăng ký / đăng nhập / trạng thái)

*Domain trọng tâm — phân tích sâu.*

**1. Mục đích**: xử lý toàn bộ vấn đề liên quan đến việc **truy cập** vào tài khoản: đăng ký, đăng nhập, đăng xuất, quên mật khẩu, liên kết mạng xã hội, trạng thái tài khoản (hoạt động/khoá/đã xoá). Phân biệt với `08_profile` (thông tin cá nhân bên trong tài khoản) và `11_security` (bảo vệ nâng cao/chống gian lận).

**2. Dữ liệu cần lưu**: loại tài khoản (user/seller), phương thức đăng ký (số điện thoại/email/mạng xã hội), trạng thái tài khoản (đang hoạt động, chờ xác minh, bị khoá tạm thời, bị khoá vĩnh viễn, đã yêu cầu xoá), lý do khoá (nếu có, ở mức tóm tắt không lộ thông tin nội bộ), lịch sử xác minh OTP, thời điểm tạo tài khoản.

**3. Cấu trúc**: hồ sơ tài khoản có vòng đời trạng thái (state machine): `chưa xác minh → đang hoạt động → (tạm khoá ↔ đang hoạt động) → đã xoá`. Mỗi chuyển trạng thái có timestamp và nguyên nhân.

**4. Quan hệ với domain khác**: là điều kiện tiên quyết để dùng `03_order` (phải đăng nhập mới xem đơn), `08_profile` (chỉnh sửa thông tin), `04_payment` (ví/phương thức thanh toán gắn với tài khoản); liên kết chặt với `11_security` (đổi mật khẩu, đăng nhập bất thường) và `12_contact` khi cần xác minh danh tính qua CSKH.

**5. Intent**: `dang_ky_tai_khoan`, `dang_nhap_loi`, `quen_mat_khau`, `khong_nhan_duoc_otp`, `tai_khoan_bi_khoa`, `yeu_cau_xoa_tai_khoan`, `lien_ket_mang_xa_hoi`, `kiem_tra_trang_thai_tai_khoan`.

**6. Entity**: `so_dien_thoai`/`email` (định danh đăng nhập), `loai_tai_khoan` (user/seller), `ma_otp`, `kenh_dang_nhap` (Google/Facebook/Apple/số điện thoại), `thoi_diem_thao_tac`.

**7. Keyword**: "không đăng nhập được", "quên mật khẩu", "không nhận được mã", "tài khoản bị khoá", "sao không vào được app", "xoá tài khoản".

**8. Synonym**: "mã OTP" ~ "mã xác nhận" ~ "code"; "khoá tài khoản" ~ "bị chặn" ~ "bị đình chỉ" ~ "không vào được"; "đăng nhập" ~ "login" ~ "vào app".

**9. Business Flow**:
- *Quên mật khẩu*: xác nhận định danh (SĐT/email) → kiểm tra tài khoản tồn tại qua API → hướng dẫn gửi lại OTP/link đặt lại mật khẩu → xác nhận đã gửi.
- *Không nhận được OTP*: hỏi kênh nhận (SMS/Zalo/email) → kiểm tra qua API xem OTP có được gửi thành công không → nếu hệ thống báo gửi thành công nhưng người dùng không nhận, hướng dẫn kiểm tra chặn tin nhắn rác/thử kênh khác → nếu vẫn lỗi, escalate.
- *Tài khoản bị khoá*: tra cứu trạng thái qua API → nếu do vi phạm chính sách, trả lời bằng template chung (không tiết lộ chi tiết điều tra nội bộ) và hướng dẫn quy trình khiếu nại → escalate CSKH để xử lý mở khoá (chatbot không tự mở khoá).
- *Yêu cầu xoá tài khoản*: đây là hành động không thể tự động hoá hoàn toàn do liên quan dữ liệu cá nhân/pháp lý (GDPR-like) → chatbot xác nhận yêu cầu, giải thích hệ quả (mất lịch sử đơn, voucher, ví...), rồi tạo yêu cầu và escalate/tạo ticket cho bộ phận xử lý, không xoá ngay lập tức qua chatbot.

**10. Response Template**: mẫu hướng dẫn gửi lại OTP; mẫu giải thích trạng thái khoá tài khoản (không tiết lộ lý do nội bộ chi tiết); mẫu xác nhận đã tiếp nhận yêu cầu xoá tài khoản kèm mã ticket; mẫu hướng dẫn liên kết/gỡ liên kết mạng xã hội.

**11. API cần gọi**:
- `[CẦN XÁC NHẬN]` API kiểm tra tồn tại tài khoản theo SĐT/email (dùng chung với luồng đăng ký/đăng nhập ở `lib/features/user/auth/`).
- `[CẦN XÁC NHẬN]` API gửi lại OTP.
- `[CẦN BỔ SUNG]` API tra cứu trạng thái khoá tài khoản dành riêng cho chatbot (hiện chưa thấy endpoint tra cứu trạng thái tài khoản lộ ra cho mục đích CSKH).
- `[CẦN BỔ SUNG]` API tạo yêu cầu xoá tài khoản (ticket hoá, không xoá tức thời).

**12. Điều kiện gọi API**: chỉ gọi API tra cứu trạng thái/OTP sau khi đã xác thực được người hỏi đúng là chủ tài khoản (qua OTP hoặc đã đăng nhập sẵn trong app) — **không bao giờ** tiết lộ tồn tại/không tồn tại tài khoản theo SĐT/email cho người chưa xác thực, để tránh rò rỉ thông tin (user enumeration).

**13. Validation**: định dạng SĐT/email hợp lệ trước khi gọi API; giới hạn số lần thử OTP/gửi lại trong một khoảng thời gian (rate limit) để chống spam.

**14. Exception**: tài khoản không tồn tại; tài khoản seller bị nhầm hỏi ở luồng user (và ngược lại); API timeout khi tra cứu trạng thái; người dùng cung cấp SĐT không khớp với tài khoản đang đăng nhập.

**15. Escalation CSKH**: mọi yêu cầu **mở khoá tài khoản**, **xoá tài khoản**, **nghi ngờ tài khoản bị chiếm quyền** đều bắt buộc escalate — chatbot chỉ hỗ trợ tiếp nhận và hướng dẫn, không có quyền thực thi các hành động nhạy cảm này.

**16. Logging**: log riêng biệt các sự kiện bảo mật (khoá/mở/xoá/đăng nhập bất thường) với mức độ nhạy cảm cao hơn log thông thường, lưu trữ theo chính sách bảo mật dữ liệu.

**17. Analytics**: tỷ lệ intent `dang_nhap_loi`/`quen_mat_khau` theo thời gian (chỉ báo chất lượng UX đăng nhập); tỷ lệ escalate trên tổng hội thoại account (chỉ báo domain này tự động hoá được bao nhiêu %).

---

## 03_order — Đơn hàng

*Domain trọng tâm — phân tích sâu.*

**1. Mục đích**: cho phép người dùng tra cứu trạng thái đơn, lịch sử đơn, chi tiết đơn, và thực hiện các hành động được phép (huỷ đơn) ngay trong chatbot mà không cần chờ CSKH người thật.

**2. Dữ liệu cần lưu**: mã đơn hàng, danh sách sản phẩm/số lượng/giá trong đơn, seller sở hữu đơn (marketplace nhiều seller — một "đơn" của người mua có thể tách theo từng seller), trạng thái đơn hiện tại, lịch sử chuyển trạng thái kèm timestamp, phương thức thanh toán đã chọn, phương thức vận chuyển, địa chỉ giao, tổng tiền, voucher áp dụng.

**3. Cấu trúc**: đơn hàng là thực thể trung tâm, có **vòng đời trạng thái** là xương sống của toàn bộ trải nghiệm CSKH. Theo hệ thống hiện tại, trạng thái chính thức ở phía client gồm 5 giá trị: **Chờ xử lý (pending) → Đang xử lý (processing) → Đang giao (on delivery) → Hoàn tất (completed)**, và nhánh **Từ chối/Đã huỷ (declined)**. Việc huỷ đơn được xử lý như một **hành động** (gọi API huỷ) chứ không phải một nhánh trạng thái tách rời trong dữ liệu hiện có — về mặt thiết kế bộ data cho chatbot, cần **ánh xạ thêm các trạng thái "ẩn"** mà người dùng cảm nhận được (ví dụ "đang đóng gói", "đang giao thất bại", "đang chờ hoàn tiền") lên trên 5 trạng thái kỹ thuật này, vì người dùng sẽ hỏi bằng ngôn ngữ trải nghiệm chứ không phải bằng tên field kỹ thuật. Xem chi tiết ánh xạ đầy đủ ở mục `05_shipping` (vòng đời được yêu cầu phân tích sâu riêng).

**4. Quan hệ với domain khác**: là hub liên kết `04_payment` (trạng thái thanh toán của đơn), `05_shipping` (trạng thái vận chuyển chi tiết hơn trạng thái đơn), `06_return_refund` (chỉ tạo được yêu cầu đổi trả/hoàn tiền từ một đơn cụ thể), `09_promotion` (voucher áp dụng trong đơn), `02_account`/`08_profile` (chủ đơn, địa chỉ giao).

**5. Intent**: `tra_cuu_don_hang`, `kiem_tra_trang_thai_don`, `xem_lich_su_don`, `huy_don_hang`, `sao_don_chua_duoc_xac_nhan`, `don_hang_bi_sai_sot` (sai sản phẩm/số lượng — thường dẫn sang `06_return_refund`), `khong_thay_don_hang`.

**6. Entity**: `ma_don_hang` (bắt buộc cho hầu hết intent, dạng mã có prefix cố định), `khoang_thoi_gian` (khi hỏi "đơn tuần trước"), `ten_san_pham` (khi không nhớ mã đơn, tìm theo tên sản phẩm đã mua), `ly_do_huy` (khi huỷ đơn).

**7. Keyword**: "đơn hàng của tôi", "đơn X", "tình trạng đơn", "sao chưa xác nhận", "huỷ đơn", "đơn đang ở đâu", "chưa thấy đơn".

**8. Synonym**: "đơn hàng" ~ "order" ~ "đơn"; "huỷ đơn" ~ "cancel" ~ "không mua nữa" ~ "đổi ý"; "xác nhận đơn" ~ "duyệt đơn" ~ "seller nhận đơn".

**9. Business Flow**:
- *Tra cứu trạng thái*: nếu người dùng cung cấp mã đơn → gọi API chi tiết đơn trực tiếp; nếu không có mã đơn → gọi API danh sách đơn của user (đã đăng nhập) → nếu nhiều hơn 1 đơn khớp mô tả, liệt kê để người dùng chọn → trả lời trạng thái bằng template tương ứng với trạng thái đó (mỗi trạng thái có 1 template riêng, xem `05_shipping`).
- *Huỷ đơn*: xác định đơn → kiểm tra trạng thái hiện tại có cho phép huỷ hay không (chỉ cho phép ở trạng thái pending/processing, **không** cho phép khi đã "on delivery" theo quy tắc nghiệp vụ chuẩn của các sàn TMĐT) → nếu được phép, hỏi xác nhận + lý do huỷ → gọi API huỷ → xác nhận kết quả. Nếu không được phép huỷ (đã giao hàng) → giải thích và chuyển hướng sang `06_return_refund` (đổi trả) thay vì huỷ.
- *Đơn chưa được xác nhận lâu*: kiểm tra thời gian đơn ở trạng thái pending — nếu vượt ngưỡng SLA xác nhận của seller mà hệ thống định nghĩa, trả lời kèm giải thích + đề xuất tự huỷ nếu người dùng không muốn chờ, hoặc escalate để CSKH thúc seller xác nhận.

**10. Response Template**: 1 template gốc theo từng trạng thái (5 trạng thái kỹ thuật + các biến thể trải nghiệm), template xác nhận huỷ thành công, template từ chối huỷ (kèm lý do + hướng dẫn sang đổi trả), template "không tìm thấy đơn khớp mô tả".

**11. API cần gọi**: `[ĐÃ CÓ]` `GET /orders` (danh sách), `GET /orders/{id}` (chi tiết), `GET /orders/{id}/payment-status` (trạng thái thanh toán kèm theo), `POST /orders/{id}/cancel` (huỷ đơn).

**12. Điều kiện gọi API**: chỉ gọi các API đơn hàng khi user đã xác thực đăng nhập và `order.user_id` khớp với người đang hội thoại (chặn truy vấn chéo đơn của người khác dù có mã đơn).

**13. Validation**: định dạng mã đơn hợp lệ; đơn phải thuộc về chính người dùng đang chat; với huỷ đơn — validate trạng thái hiện tại nằm trong tập trạng thái được phép huỷ trước khi gọi API (tránh gọi API rồi nhận lỗi mới báo người dùng, nên chặn sớm ở business flow để trả lời nhanh và rõ ràng hơn).

**14. Exception**: mã đơn không tồn tại; đơn thuộc tài khoản khác; API huỷ trả lỗi vì seller đã xử lý ngay trước đó (race condition giữa lúc chatbot kiểm tra trạng thái và lúc gọi huỷ — cần gọi lại API lấy trạng thái mới nhất ngay trước khi xác nhận huỷ với người dùng); timeout API.

**15. Escalation CSKH**: seller không xác nhận đơn quá lâu (vi phạm SLA), người dùng khiếu nại "đơn tôi bị huỷ mà tôi không huỷ", tranh chấp giá trị đơn khác với lúc đặt, mọi trường hợp API báo lỗi nghiệp vụ không nằm trong danh sách exception đã biết.

**16. Logging**: log toàn bộ transition trạng thái được chatbot đọc ra (phục vụ audit "chatbot đã nói gì với khách tại thời điểm nào"), log riêng các lượt huỷ đơn qua chatbot (lý do huỷ là dữ liệu quý cho seller/product team).

**17. Analytics**: tỷ lệ đơn bị huỷ qua chatbot vs qua CSKH người; top lý do huỷ; thời gian trung bình đơn nằm ở "pending" trước khi bị hỏi (chỉ báo SLA xác nhận của seller); tỷ lệ hội thoại tra cứu đơn không tìm thấy đơn khớp (có thể chỉ báo lỗi UX tìm kiếm hoặc gian lận).

---

## 04_payment — Thanh toán

*Domain trọng tâm — phân tích sâu.*

**1. Mục đích**: giải đáp và xử lý các vấn đề về phương thức thanh toán, trạng thái giao dịch, hoá đơn, và các lỗi thanh toán phổ biến (đã trừ tiền nhưng đơn chưa lên, thanh toán thất bại...).

**2. Dữ liệu cần lưu**: danh mục phương thức thanh toán khả dụng (mã, tên hiển thị, mô tả, đang bật/tắt), với Delippy hiện có **thanh toán chuyển khoản/QR qua SePay** là phương thức xác nhận đã tích hợp, ngoài ra danh sách cụ thể (COD, ví nội bộ, thẻ...) lấy động từ hệ thống chứ không cố định cứng trong knowledge base; trạng thái giao dịch (khởi tạo, chờ xác nhận, thành công, thất bại, hết hạn); mã giao dịch tham chiếu; số tiền; thời gian thanh toán.

**3. Cấu trúc**: giao dịch thanh toán là thực thể con gắn 1-1 hoặc 1-nhiều với đơn hàng (một đơn có thể có nhiều lần thử thanh toán nếu lần đầu thất bại). Vòng đời giao dịch: `khởi tạo → chờ xác nhận (đang chờ webhook/polling từ cổng thanh toán) → thành công | thất bại | hết hạn`.

**4. Quan hệ với domain khác**: gắn chặt với `03_order` (đơn chỉ chuyển sang "processing" khi thanh toán thành công, trừ COD), là điểm khởi đầu của `06_return_refund` (hoàn tiền phải hoàn theo đúng phương thích đã thanh toán), liên quan `09_promotion` (voucher giảm giá trị thanh toán), `11_security` (giao dịch bất thường/nghi gian lận).

**5. Intent**: `hoi_phuong_thuc_thanh_toan`, `kiem_tra_trang_thai_thanh_toan`, `da_thanh_toan_nhung_don_chua_len`, `thanh_toan_that_bai`, `hoi_hoa_don_vat`, `bi_tru_tien_hai_lan`.

**6. Entity**: `ma_don_hang`, `phuong_thuc_thanh_toan` (SePay/COD/ví...), `so_tien`, `thoi_diem_thanh_toan`, `ma_giao_dich` (nếu người dùng có mã tham chiếu ngân hàng).

**7. Keyword**: "thanh toán", "chuyển khoản", "quét mã QR", "đã chuyển tiền mà chưa lên đơn", "bị trừ tiền", "thanh toán lỗi", "hoá đơn".

**8. Synonym**: "thanh toán" ~ "pay" ~ "trả tiền"; "chuyển khoản" ~ "banking" ~ "quét QR"; "trừ tiền" ~ "bị charge" ~ "bị trừ";"thất bại" ~ "lỗi" ~ "không thành công".

**9. Business Flow**:
- *Hỏi phương thức thanh toán khả dụng*: trả lời tĩnh/động từ danh mục phương thức đang bật, không cần theo đơn cụ thể.
- *Đã chuyển khoản nhưng đơn chưa cập nhật*: xác định đơn (mã đơn hoặc đơn gần nhất chưa thanh toán) → gọi API trạng thái thanh toán → nếu hệ thống đã ghi nhận thành công nhưng UI đơn chưa refresh, giải thích và đề xuất tải lại/chờ vài phút (đồng bộ có độ trễ) → nếu hệ thống **chưa** ghi nhận, hỏi thêm thông tin xác nhận từ phía ngân hàng người dùng (thời gian chuyển, số tiền) để CSKH đối soát → escalate kèm theo entity đã thu thập (đối soát giao dịch ngân hàng là việc chatbot không tự làm được).
- *Thanh toán thất bại*: kiểm tra trạng thái qua API → nếu thất bại do hết hạn phiên thanh toán, hướng dẫn thử lại từ đầu; nếu thất bại không rõ nguyên nhân kỹ thuật, escalate.
- *Bị trừ tiền hai lần*: đây luôn là trường hợp nhạy cảm liên quan tiền thật của khách — chatbot chỉ thu thập bằng chứng (thời gian, số tiền, số lần) rồi escalate ngay, không tự kết luận đúng/sai.

**10. Response Template**: mẫu liệt kê phương thức thanh toán; mẫu giải thích trạng thái đang chờ xác nhận (kèm thời gian đồng bộ dự kiến); mẫu xác nhận thanh toán thành công; mẫu hướng dẫn thử lại khi hết hạn; mẫu chuyển CSKH cho tranh chấp giao dịch tiền.

**11. API cần gọi**: `[ĐÃ CÓ]` `GET /payment-methods`, `GET /orders/{id}/payment-status`. `[CẦN XÁC NHẬN]` API chi tiết lịch sử các lần thử thanh toán của một đơn (để phân biệt "lần 1 thất bại, lần 2 thành công" khi giải thích cho khách). `[CẦN BỔ SUNG]` API tra cứu/xuất hoá đơn VAT nếu sàn có hỗ trợ xuất hoá đơn.

**12. Điều kiện gọi API**: chỉ tra cứu trạng thái thanh toán của đơn thuộc chính người dùng đang chat; với các case liên quan tranh chấp tiền, luôn kèm theo bước xác thực danh tính mạnh hơn (đã đăng nhập + đúng chủ đơn) trước khi tiết lộ chi tiết số tiền/thời gian giao dịch.

**13. Validation**: số tiền/mã giao dịch người dùng cung cấp phải đúng định dạng trước khi dùng làm entity đối soát; kiểm tra đơn có ở trạng thái chờ thanh toán trước khi trả lời "đang chờ xác nhận" (tránh trả lời sai nếu đơn thực ra đã completed từ lâu).

**14. Exception**: cổng thanh toán báo thành công nhưng hệ thống order chưa nhận webhook (độ trễ đồng bộ); người dùng nhầm đơn (thanh toán cho đơn A nhưng hỏi về đơn B); giao dịch trùng do người dùng bấm thanh toán nhiều lần.

**15. Escalation CSKH**: mọi khiếu nại về **tiền đã mất nhưng hệ thống không ghi nhận**, nghi ngờ gian lận thanh toán, yêu cầu xuất hoá đơn VAT nếu chưa có API tự động, sai lệch số tiền giữa hoá đơn và số tiền bị trừ thực tế.

**16. Logging**: log chi tiết hơn mức bình thường cho mọi hội thoại thuộc domain payment (vì liên quan tiền thật), lưu kèm entity số tiền/mã giao dịch để phục vụ đối soát sau này nếu escalate.

**17. Analytics**: tỷ lệ thanh toán thất bại theo phương thức (chỉ báo chất lượng tích hợp cổng thanh toán); độ trễ trung bình giữa lúc thanh toán và lúc hệ thống ghi nhận (chỉ báo cần cải thiện đồng bộ hay không); tần suất khiếu nại "bị trừ tiền" theo phương thức thanh toán.

---

## 05_shipping — Vận chuyển

*Domain trọng tâm — phân tích sâu, bao gồm vòng đời đầy đủ theo yêu cầu.*

**1. Mục đích**: đây là domain người dùng hỏi nhiều nhất trong CSKH thương mại điện tử ("hàng tôi đâu rồi"). Mục tiêu là chatbot có thể tự trả lời chính xác trạng thái vận chuyển theo từng giai đoạn, biết khi nào cần hỏi thêm, và khi nào phải escalate.

**2. Dữ liệu cần lưu**: phương thức vận chuyển đã chọn (đối tác giao hàng), mã vận đơn, trạng thái vận chuyển hiện tại, lịch sử mốc tracking (mỗi mốc kèm timestamp + địa điểm nếu đối tác cung cấp), số lần giao thất bại, lý do giao thất bại, địa chỉ giao, thông tin liên hệ người nhận, thời gian giao dự kiến (ETA).

**3. Cấu trúc**: `05_shipping` là lớp **chi tiết hoá** của trạng thái đơn hàng (`03_order`) — một trạng thái đơn kỹ thuật (ví dụ "on delivery") có thể trải qua nhiều trạng thái vận chuyển chi tiết hơn mà người dùng cảm nhận riêng biệt (đang đóng gói, đã bàn giao đơn vị vận chuyển, đang giao, giao thất bại...). Thiết kế data cần một bảng ánh xạ **trạng thái trải nghiệm ↔ trạng thái kỹ thuật ↔ hành động được phép ↔ nội dung chatbot phải nói/phải hỏi ↔ API liên quan ↔ điều kiện escalate**, trình bày đầy đủ ở mục 3.1 bên dưới.

**4. Quan hệ với domain khác**: là phần mở rộng trực tiếp của `03_order`; là điều kiện để mở `06_return_refund` (chỉ tạo được yêu cầu đổi trả sau khi trạng thái vận chuyển là "đã giao"); liên quan `12_contact` khi cần chuyển thông tin cho đơn vị vận chuyển đối soát.

### 3.1 Vòng đời đầy đủ của đơn hàng qua lăng kính Shipping

| Giai đoạn | Trạng thái kỹ thuật tương ứng | Khách được phép làm gì | Chatbot phải trả lời gì | Chatbot cần hỏi gì (nếu thiếu thông tin) | API được gọi | Khi nào chuyển CSKH |
|---|---|---|---|---|---|---|
| **1. Đặt hàng** | `pending` | Huỷ đơn tự do | Xác nhận đơn đã được ghi nhận, đang chờ seller xác nhận, thời gian dự kiến seller phản hồi | Không cần hỏi thêm nếu đã có mã đơn | `GET /orders/{id}` | Nếu quá SLA xác nhận mà seller chưa phản hồi |
| **2. Đã xác nhận** | `processing` (giai đoạn đầu) | Huỷ đơn (còn cho phép, thường có phí/điều kiện tuỳ chính sách) | Đơn đã được seller xác nhận, đang chuẩn bị hàng, chưa có mã vận đơn | Không cần hỏi thêm | `GET /orders/{id}` | Nếu seller xác nhận rồi nhưng đứng yên quá lâu không chuyển sang đóng gói |
| **3. Đóng gói** | `processing` (giai đoạn sau, trước khi có tracking) | Huỷ đơn thường bị hạn chế hơn (có thể mất phí hoặc cần seller đồng ý) | Đơn đang được chuẩn bị/đóng gói, sắp bàn giao vận chuyển | Không cần hỏi thêm | `GET /orders/{id}` | Nếu thời gian đóng gói vượt cam kết của seller |
| **4. Đã bàn giao vận chuyển** | `onDelivery` (bắt đầu) | Không huỷ được nữa qua chatbot (chính sách chuẩn — huỷ lúc này cần seller/CSKH duyệt) | Đơn đã rời kho, cung cấp mã vận đơn và đơn vị vận chuyển | Không cần hỏi thêm, trừ khi cần xác nhận địa chỉ giao | `GET /orders/{id}` (đọc trạng thái/tracking đi kèm) | Nếu người dùng muốn huỷ ở giai đoạn này → giải thích chính sách + escalate nếu khách vẫn kiên quyết |
| **5. Đang giao** | `onDelivery` | Đổi địa chỉ/thời gian giao (nếu chính sách/đối tác vận chuyển cho phép — thường giới hạn) | Vị trí/mốc tracking gần nhất, ETA dự kiến | Nếu ETA đã trôi qua mà chưa giao: hỏi khách đã liên hệ tài xế/đơn vị vận chuyển chưa | `GET /orders/{id}` (tracking) | Nếu quá ETA nhiều giờ/ngày không có cập nhật tracking mới |
| **6. Giao thất bại** | `onDelivery` (nhánh lỗi) hoặc chuyển hướng tới `declined` tuỳ chính sách xử lý sau nhiều lần thất bại | Chọn giao lại, đổi địa chỉ/SĐT liên hệ, hoặc yêu cầu huỷ | Lý do giao thất bại (không liên lạc được, sai địa chỉ, khách từ chối nhận...), số lần đã thử, các lựa chọn tiếp theo | Xác nhận khách còn muốn nhận hàng không; nếu có, xác nhận lại địa chỉ/SĐT | `GET /orders/{id}` (đọc lý do thất bại nếu đối tác vận chuyển trả về) | Ngay khi giao thất bại từ lần thứ 2 trở lên, hoặc lần đầu nếu lý do là lỗi hệ thống/địa chỉ không xác định |
| **7. Đã giao** | `completed` | Yêu cầu đổi trả/hoàn tiền (mở `06_return_refund`), đánh giá sản phẩm | Xác nhận đã giao thành công, thời gian giao, hướng dẫn quy trình đổi trả nếu có vấn đề, nhắc hạn đổi trả còn lại | Nếu khách báo "chưa nhận được hàng nhưng hệ thống nói đã giao" → hỏi thời gian/người nhận hộ | `GET /orders/{id}` | Nếu khách khẳng định chưa nhận được hàng dù hệ thống ghi "đã giao" (nghi ngờ giao sai người/mất hàng) → escalate ngay |
| **8. Đổi trả** | Trạng thái riêng của **yêu cầu đổi trả**, độc lập với 5 trạng thái đơn (xem `06_return_refund`) | Gửi yêu cầu kèm lý do + hình ảnh, theo dõi trạng thái duyệt | Đã ghi nhận yêu cầu, các bước tiếp theo (seller/CSKH duyệt, gửi trả hàng nếu cần) | Lý do đổi trả, hình ảnh minh chứng, sản phẩm/dòng hàng cụ thể trong đơn | Xem `06_return_refund` — **hiện chưa có remote API**, chỉ có luồng ghi nhận cục bộ | Toàn bộ domain đổi trả hiện có mức độ tự động hoá thấp do thiếu API — cân nhắc escalate sớm hơn cho tới khi backend hoàn thiện |
| **9. Hoàn tiền** | Không có model riêng ở hệ thống hiện tại — cần domain `06_return_refund` định nghĩa như một trạng thái con của yêu cầu đổi trả | Theo dõi tiến độ hoàn tiền, chọn lại phương thức nhận hoàn tiền nếu được hỗ trợ | Xác nhận yêu cầu hoàn tiền đã được duyệt, số tiền, phương thức hoàn, thời gian dự kiến | Không cần hỏi thêm nếu đã có yêu cầu đổi trả liên kết | `[CẦN BỔ SUNG]` API tra cứu trạng thái hoàn tiền | Escalate khi quá thời gian cam kết hoàn tiền mà chưa nhận được, hoặc số tiền hoàn không khớp kỳ vọng của khách |

Ghi chú thiết kế quan trọng: 5 trạng thái kỹ thuật hiện có (`pending/processing/onDelivery/completed/declined`) **không đủ chi tiết** để tự thân trả lời đúng cho 9 giai đoạn trải nghiệm ở trên. Bộ Knowledge Base của domain Shipping cần một tầng "trạng thái phụ" (sub-status) bổ sung — ví dụ lấy từ lịch sử tracking chi tiết (`order_track`) hoặc từ trường trạng thái riêng bên phía seller — để phân biệt được "processing = đã xác nhận" với "processing = đang đóng gói", và "onDelivery = đang giao" với "onDelivery = giao thất bại". Đây là điểm cần đội backend bổ sung field trạng thái chi tiết hơn hoặc expose lịch sử tracking đầy đủ cho chatbot đọc.

**5. Intent**: `tra_cuu_van_don`, `hang_dang_o_dau`, `giao_thieu_du_kien_bao_lau`, `giao_that_bai`, `doi_dia_chi_giao`, `chua_nhan_duoc_hang_du_he_thong_bao_da_giao`.

**6. Entity**: `ma_don_hang`, `ma_van_don`, `dia_chi_giao_moi` (khi yêu cầu đổi địa chỉ), `so_dien_thoai_nguoi_nhan`, `ly_do_giao_that_bai` (nếu khách tự thuật lại).

**7. Keyword**: "hàng tới đâu rồi", "shipper", "giao hàng", "vận đơn", "sao chưa giao", "giao thất bại", "đổi địa chỉ nhận".

**8. Synonym**: "shipper" ~ "người giao hàng" ~ "đơn vị vận chuyển"; "vận đơn" ~ "mã tracking" ~ "mã theo dõi"; "giao thất bại" ~ "giao không thành công" ~ "không gặp được người nhận".

**9. Business Flow**: xem chi tiết theo từng giai đoạn ở bảng 3.1; nguyên tắc chung — luôn ưu tiên đọc **lịch sử tracking chi tiết nhất có thể** trước khi trả lời bằng trạng thái kỹ thuật thô, vì trạng thái thô dễ gây hiểu lầm (ví dụ trả lời "đang giao" trong khi thực tế vừa giao thất bại lần 2).

**10. Response Template**: một template cho mỗi hàng trong bảng 3.1 (9 template chính), cộng thêm template biến thể khi có ETA cụ thể, template biến thể khi không có ETA (một số phương thức vận chuyển không cung cấp ETA), template escalate riêng cho "chưa nhận được hàng dù hệ thống báo đã giao" (đây là template nhạy cảm nhất của toàn domain, cần văn phong trấn an + cam kết xử lý rõ ràng thay vì chỉ báo lỗi kỹ thuật).

**11. API cần gọi**: `[ĐÃ CÓ]` `GET /orders/{id}` (trạng thái tổng quát), cơ chế tracking hiện có ở tầng hiển thị (`order_track`, `order_tracking_utils`) — **cần xác nhận với backend liệu các mốc tracking chi tiết có API riêng lộ ra được hay chỉ tính toán ở phía client**. `[CẦN BỔ SUNG]` API tra cứu chi tiết lý do giao thất bại theo từng lần thử, API yêu cầu đổi địa chỉ giao giữa chừng.

**12. Điều kiện gọi API**: chỉ trả lời tracking chi tiết cho đúng chủ đơn; nếu đơn thuộc diện đang có khiếu nại/escalate đang mở, chatbot nên ưu tiên nhắc "yêu cầu của bạn đang được CSKH xử lý" thay vì lặp lại thông tin tracking cũ gây khó chịu.

**13. Validation**: mã vận đơn/đơn phải khớp; địa chỉ giao mới (nếu cho đổi) phải qua validate định dạng địa chỉ trước khi xác nhận với khách là "đã ghi nhận yêu cầu đổi địa chỉ" (bản thân việc đổi thực tế có thể cần seller/đơn vị vận chuyển duyệt, không phải lúc nào chatbot cũng tự làm được).

**14. Exception**: đơn vị vận chuyển chưa cập nhật tracking kịp thời (dữ liệu trễ so với thực tế); đơn có nhiều kiện hàng tách lẻ (marketplace nhiều seller trong 1 đơn) dẫn tới trạng thái không đồng nhất giữa các kiện; ETA bị lệch do yếu tố ngoài hệ thống (thời tiết, khu vực xa).

**15. Escalation CSKH**: giao thất bại từ lần 2 trở lên; "chưa nhận được hàng" dù hệ thống báo đã giao; yêu cầu đổi địa chỉ khi hàng đã đang trên xe giao (rủi ro cao, cần con người quyết định); mọi khiếu nại về thái độ shipper/đơn vị vận chuyển.

**16. Logging**: log đầy đủ chuỗi mốc tracking đã đọc cho khách tại từng thời điểm hỏi (để đối chiếu sau này nếu có khiếu nại "chatbot nói khác với thực tế"); log riêng số lần giao thất bại theo đơn/khu vực.

**17. Analytics**: tỷ lệ giao thất bại theo khu vực/đơn vị vận chuyển (input quan trọng để đàm phán lại với đối tác vận chuyển); thời gian trung bình từ "đã bàn giao vận chuyển" đến "đã giao" theo khu vực; tỷ lệ hội thoại shipping phải escalate (chỉ báo mức độ hoàn thiện của tracking data).

---

## 06_return_refund — Đổi trả và hoàn tiền

*Domain trọng tâm — phân tích sâu.*

**1. Mục đích**: xử lý toàn bộ luồng khách muốn trả lại sản phẩm và/hoặc nhận lại tiền sau khi đơn đã giao (hoặc trong một số trường hợp đặc biệt, sau khi giao thất bại nhiều lần dẫn tới huỷ).

**2. Dữ liệu cần lưu**: mã yêu cầu đổi trả, đơn hàng gốc, dòng sản phẩm cụ thể trong đơn được yêu cầu đổi trả (một đơn nhiều sản phẩm có thể chỉ đổi trả một phần), lý do đổi trả (nhóm lý do chuẩn hoá: sai sản phẩm, lỗi/hư hỏng, không đúng mô tả, đổi ý...), hình ảnh/video minh chứng, trạng thái yêu cầu, phương thức hoàn tiền mong muốn, số tiền hoàn dự kiến/thực tế, lịch sử duyệt (seller/CSKH).

**3. Cấu trúc**: theo dữ liệu hiện có, thực thể `ReturnRequest` gồm lý do, danh sách ảnh, danh sách dòng sản phẩm liên quan trong đơn, và trạng thái — đây là **thực thể độc lập, tham chiếu tới đơn hàng**, không phải một field trạng thái nằm trong đơn. Vòng đời đề xuất: `mới tạo → chờ seller/CSKH duyệt → được duyệt (chờ khách gửi trả hàng nếu cần) → đã nhận hàng trả (nếu áp dụng) → hoàn tiền đang xử lý → hoàn tiền hoàn tất`, hoặc rẽ nhánh `bị từ chối` ở bước duyệt. Hiện trạng backend: module này **mới chỉ có phần lưu cục bộ trên thiết bị (local data source), chưa có API thật** — nghĩa là quy trình duyệt/hoàn tiền thực tế **hiện đang hoàn toàn phụ thuộc CSKH người thật xử lý thủ công**, chatbot chỉ đóng vai trò tiếp nhận yêu cầu có cấu trúc.

**4. Quan hệ với domain khác**: bắt buộc phải có `03_order` (và trạng thái "đã giao" ở `05_shipping`) làm điều kiện tiên quyết; liên quan `04_payment` (hoàn tiền phải theo đúng phương thức đã thanh toán, hoặc phương thức thay thế khách chọn); liên quan `09_promotion` (nếu đơn dùng voucher, cần quy tắc rõ giá trị hoàn có bao gồm phần được giảm hay không); có thể liên quan `07_warranty` nếu lý do đổi trả là lỗi sản phẩm trong thời hạn bảo hành.

**5. Intent**: `yeu_cau_doi_tra`, `yeu_cau_hoan_tien`, `kiem_tra_trang_thai_doi_tra`, `san_pham_bi_loi`, `giao_sai_san_pham`, `khong_dung_mo_ta`, `huy_yeu_cau_doi_tra`.

**6. Entity**: `ma_don_hang`, `san_pham_can_doi_tra` (dòng cụ thể trong đơn), `ly_do_doi_tra` (chuẩn hoá theo nhóm), `hinh_anh_minh_chung` (đính kèm), `phuong_thuc_hoan_tien_mong_muon`.

**7. Keyword**: "trả hàng", "đổi hàng", "hoàn tiền", "hàng lỗi", "sai sản phẩm", "không giống hình", "muốn trả lại".

**8. Synonym**: "đổi trả" ~ "return" ~ "trả hàng hoàn tiền"; "hoàn tiền" ~ "refund" ~ "trả lại tiền"; "hàng lỗi" ~ "hư" ~ "hỏng" ~ "không hoạt động".

**9. Business Flow**:
- *Tạo yêu cầu đổi trả*: xác nhận đơn đã ở trạng thái "đã giao" và còn trong hạn đổi trả theo `10_policy` → xác định (các) dòng sản phẩm cụ thể cần đổi trả trong đơn (không mặc định cả đơn) → hỏi lý do (chọn theo nhóm chuẩn hoá, tránh để khách tự do gõ khiến khó xử lý) → yêu cầu đính kèm hình ảnh nếu lý do thuộc nhóm "lỗi/hư hỏng/không đúng mô tả" → xác nhận lại toàn bộ thông tin với khách → ghi nhận yêu cầu (hiện tại: lưu cục bộ + tạo ticket cho CSKH xử lý thủ công, do chưa có API duyệt tự động) → thông báo mã yêu cầu và bước tiếp theo dự kiến.
- *Kiểm tra trạng thái yêu cầu đã tạo*: tra cứu theo mã yêu cầu hoặc mã đơn → trả lời theo trạng thái (đang chờ duyệt/đã duyệt/đang hoàn tiền/hoàn tất/bị từ chối) → nếu bị từ chối, giải thích lý do (nếu có) và hướng dẫn khiếu nại tiếp nếu khách không đồng ý.
- *Yêu cầu hoàn tiền không có sản phẩm phải trả lại* (ví dụ: đơn bị lỗi thanh toán, hoặc huỷ đơn sau khi đã thanh toán trước): tách biệt khỏi luồng "trả hàng vật lý" — xác nhận số tiền, phương thức hoàn, rồi escalate/tạo ticket vì đây gần như luôn cần CSKH xác nhận thủ công ở hiện trạng hệ thống.

**10. Response Template**: mẫu xác nhận đã ghi nhận yêu cầu (kèm mã yêu cầu, các bước tiếp theo, thời gian xử lý dự kiến); mẫu nhắc còn trong/đã hết hạn đổi trả; mẫu giải thích trạng thái theo từng bước của vòng đời; mẫu từ chối kèm hướng dẫn khiếu nại; mẫu yêu cầu bổ sung hình ảnh minh chứng còn thiếu.

**11. API cần gọi**: `[ĐÃ CÓ – CỤC BỘ]` lưu yêu cầu đổi trả (`return_request_local_data_source`) — chỉ trên thiết bị, chưa đồng bộ server. `[CẦN BỔ SUNG – ƯU TIÊN CAO]` API tạo yêu cầu đổi trả phía server, API tra cứu trạng thái yêu cầu đổi trả, API tra cứu trạng thái hoàn tiền, API upload hình ảnh minh chứng. Đây là khoảng trống lớn nhất trong toàn bộ 18 domain — nếu muốn mode `help` của chatbot xử lý đổi trả/hoàn tiền tự động thực sự (không chỉ tạo ticket thủ công), backend bắt buộc phải bổ sung các API này trước.

**12. Điều kiện gọi API**: chỉ cho tạo yêu cầu khi đơn thuộc đúng người dùng, đơn đã ở trạng thái "đã giao", còn trong hạn đổi trả theo chính sách, và (các) dòng sản phẩm được chọn thực sự thuộc đơn đó.

**13. Validation**: bắt buộc có lý do thuộc danh mục chuẩn hoá (không nhận lý do tự do không phân loại được, để tránh dữ liệu rác khi seller/CSKH xử lý); bắt buộc có hình ảnh với các nhóm lý do yêu cầu bằng chứng; kiểm tra hạn đổi trả trước khi cho tạo yêu cầu.

**14. Exception**: hết hạn đổi trả nhưng khách vẫn khăng khăng yêu cầu (do lỗi sản phẩm phát sinh muộn — cần xét ngoại lệ, escalate); sản phẩm đã bị đổi trả một phần trước đó và khách yêu cầu đổi trả tiếp phần còn lại; seller từ chối duyệt nhưng khách không đồng ý; đơn dùng nhiều voucher/khuyến mãi khiến việc tính số tiền hoàn phức tạp hơn giá trị đơn thô.

**15. Escalation CSKH**: vì backend hiện chưa có API duyệt/xử lý tự động, **toàn bộ bước duyệt và xử lý hoàn tiền thực tế đều cần escalate/tạo ticket cho người xử lý** — chatbot ở giai đoạn hiện tại đóng vai trò "thu thập thông tin có cấu trúc và tạo ticket chuẩn hoá" nhiều hơn là "tự động hoàn tất luồng". Ngoài ra escalate bắt buộc khi: hết hạn đổi trả nhưng có lý do chính đáng, tranh chấp số tiền hoàn, từ chối mà khách không đồng ý.

**16. Logging**: lưu đầy đủ lý do + hình ảnh + dòng sản phẩm liên quan cho mỗi yêu cầu (đây là dữ liệu chất lượng sản phẩm/seller quan trọng); log riêng thời gian từ lúc tạo yêu cầu tới lúc được xử lý thực tế (khi có API thật, đây sẽ là SLA cần theo dõi).

**17. Analytics**: top lý do đổi trả theo sản phẩm/seller (feedback chất lượng cho đội quản lý seller); tỷ lệ đơn bị đổi trả trên tổng đơn theo seller (chỉ báo seller có vấn đề chất lượng); thời gian xử lý trung bình một yêu cầu.

---

## 07_warranty — Bảo hành

**1. Mục đích**: hỗ trợ tra cứu điều kiện/thời hạn bảo hành và hướng dẫn quy trình yêu cầu bảo hành cho các sản phẩm có bảo hành (điện tử, gia dụng...). Do Delippy là marketplace nhiều seller, chính sách bảo hành **thuộc về từng seller/sản phẩm**, không phải chính sách thống nhất toàn sàn như đổi trả.

**2. Dữ liệu cần lưu**: thời hạn bảo hành theo sản phẩm/nhóm sản phẩm (do seller khai báo), đơn vị bảo hành (chính hãng/seller tự bảo hành), điều kiện còn hiệu lực bảo hành, kênh nộp yêu cầu bảo hành.

**3. Cấu trúc**: thông tin bảo hành gắn ở cấp **sản phẩm** (thuộc dữ liệu sản phẩm/seller khai báo lúc đăng bán), không phải cấp đơn hàng; khi có yêu cầu bảo hành mới liên kết tới đơn hàng cụ thể để xác nhận đã mua và còn hạn.

**4. Quan hệ với domain khác**: phụ thuộc `03_order` (xác nhận ngày mua để tính hạn bảo hành còn lại), có thể chồng lấn với `06_return_refund` khi lỗi phát sinh sớm (trong hạn đổi trả) — quy tắc cần rõ ràng: lỗi phát hiện trong hạn đổi trả ưu tiên xử lý theo `06_return_refund` (đổi/trả nhanh hơn), lỗi phát hiện sau khi hết hạn đổi trả nhưng còn hạn bảo hành thì xử lý theo domain này.

**5. Intent**: `hoi_thoi_han_bao_hanh`, `yeu_cau_bao_hanh`, `bao_hanh_o_dau`, `san_pham_het_bao_hanh`.

**6. Entity**: `ma_don_hang`, `san_pham`, `ngay_mua`, `mo_ta_loi`.

**7. Keyword**: "bảo hành", "còn bảo hành không", "sản phẩm hỏng sau khi dùng", "trung tâm bảo hành".

**8. Synonym**: "bảo hành" ~ "warranty" ~ "bh"; "hết hạn" ~ "quá hạn" ~ "không còn hiệu lực".

**9. Business Flow**: xác định sản phẩm/đơn hàng → tính thời hạn bảo hành còn lại dựa trên ngày mua + chính sách bảo hành của seller cho sản phẩm đó → nếu còn hạn, hướng dẫn kênh nộp yêu cầu (thường là liên hệ trực tiếp seller hoặc trung tâm bảo hành chính hãng, chatbot đóng vai trò cung cấp thông tin, không tự xử lý bảo hành vật lý) → nếu hết hạn, thông báo rõ và gợi ý các lựa chọn khác (mua mới, dịch vụ sửa chữa ngoài).

**10. Response Template**: mẫu thông báo còn hạn bảo hành kèm hướng dẫn liên hệ; mẫu thông báo hết hạn; mẫu giải thích bảo hành thuộc trách nhiệm seller (không phải Delippy trực tiếp bảo hành).

**11. API cần gọi**: `[CẦN BỔ SUNG]` — hiện không có module bảo hành nào trong hệ thống. Cần API tra cứu chính sách bảo hành theo sản phẩm (nếu seller có khai báo) và API tra cứu ngày mua theo đơn.

**12. Điều kiện gọi API**: chỉ tra cứu khi xác định được cả sản phẩm và đơn hàng gốc thuộc đúng người dùng.

**13. Validation**: sản phẩm được hỏi phải khớp với sản phẩm thực sự có trong đơn của người dùng; nếu seller không khai báo chính sách bảo hành cho sản phẩm, phải trả lời rõ "sản phẩm này không có bảo hành theo khai báo của người bán" thay vì suy đoán.

**14. Exception**: seller không khai báo chính sách bảo hành; sản phẩm mua từ lâu không còn xác định được seller gốc (seller đã ngừng hoạt động trên sàn); tranh chấp về việc lỗi có thuộc diện bảo hành hay do người dùng gây ra.

**15. Escalation CSKH**: mọi tranh chấp "lỗi có được bảo hành hay không", seller ngừng hoạt động không còn ai xử lý bảo hành đã cam kết, sản phẩm bảo hành chính hãng (không qua seller) cần CSKH kết nối với hãng.

**16. Logging**: ghi nhận tần suất yêu cầu bảo hành theo sản phẩm/seller (chỉ báo chất lượng).

**17. Analytics**: sản phẩm/seller có tỷ lệ yêu cầu bảo hành bất thường cao — đưa vào review chất lượng seller định kỳ.

---

## 08_profile — Hồ sơ cá nhân

**1. Mục đích**: hỗ trợ các câu hỏi/thao tác liên quan thông tin cá nhân bên trong tài khoản đã đăng nhập — khác với `02_account` (truy cập) ở chỗ đây là **nội dung** hồ sơ: tên, avatar, sổ địa chỉ, số điện thoại liên hệ hiển thị.

**2. Dữ liệu cần lưu**: họ tên hiển thị, avatar, ngày sinh/giới tính (nếu thu thập), sổ địa chỉ giao hàng (nhiều địa chỉ, một địa chỉ mặc định), số điện thoại/email liên hệ hiển thị trên hồ sơ (có thể khác định danh đăng nhập).

**3. Cấu trúc**: hồ sơ 1-1 với tài khoản; sổ địa chỉ là danh sách con (1 tài khoản – nhiều địa chỉ, đánh dấu 1 địa chỉ mặc định).

**4. Quan hệ với domain khác**: `02_account` (điều kiện truy cập), `03_order`/`05_shipping` (địa chỉ giao hàng của đơn lấy từ sổ địa chỉ tại thời điểm đặt — cần làm rõ với khách rằng sửa sổ địa chỉ **không** tự động cập nhật địa chỉ của đơn đã đặt).

**5. Intent**: `cap_nhat_thong_tin_ca_nhan`, `them_sua_xoa_dia_chi`, `doi_dia_chi_mac_dinh`, `khong_luu_duoc_thong_tin`.

**6. Entity**: `truong_thong_tin` (tên/avatar/ngày sinh...), `dia_chi_moi`, `dia_chi_can_xoa`.

**7. Keyword**: "đổi tên hiển thị", "cập nhật ảnh đại diện", "thêm địa chỉ", "sửa địa chỉ giao hàng", "địa chỉ mặc định".

**8. Synonym**: "hồ sơ" ~ "profile" ~ "thông tin cá nhân"; "sổ địa chỉ" ~ "địa chỉ giao hàng đã lưu".

**9. Business Flow**: hầu hết thao tác hồ sơ (đổi tên/avatar/địa chỉ) là tự phục vụ ngay trong app (không cần chatbot thực hiện hộ) — vai trò chatbot chủ yếu là **hướng dẫn đường dẫn thao tác** trong app và xử lý trường hợp lỗi ("tôi sửa mà không lưu được") bằng cách kiểm tra lỗi phổ biến (định dạng dữ liệu, kết nối mạng) trước khi escalate.

**10. Response Template**: mẫu hướng dẫn từng bước tới màn hình chỉnh sửa hồ sơ/địa chỉ; mẫu xử lý lỗi lưu không thành công thường gặp.

**11. API cần gọi**: `[ĐÃ CÓ]` endpoint hồ sơ (GET lấy thông tin, POST multipart cập nhật) — chatbot chủ yếu dùng chiều **đọc** để xác nhận thông tin hiện tại khi cần (ví dụ đọc địa chỉ mặc định để xác nhận với khách trước khi trỏ sang shipping), việc **ghi/sửa** nên khuyến khích khách tự thao tác trong app hơn là để chatbot thực hiện hộ (giảm rủi ro sai sót dữ liệu cá nhân qua kênh chat).

**12. Điều kiện gọi API**: chỉ đọc hồ sơ của chính người dùng đang đăng nhập.

**13. Validation**: định dạng số điện thoại/email nếu chatbot có hỗ trợ xác nhận trước khi hướng dẫn lưu.

**14. Exception**: lưu thất bại do mất kết nối; ảnh đại diện vượt dung lượng cho phép; địa chỉ nhập thiếu thông tin bắt buộc (phường/xã, số nhà).

**15. Escalation CSKH**: khi thao tác tự phục vụ trong app liên tục lỗi mà đã loại trừ các nguyên nhân phổ biến (nghi ngờ lỗi hệ thống, cần kỹ thuật can thiệp).

**16. Logging**: log các lượt báo lỗi lưu hồ sơ (chỉ báo bug UI/API cần đội kỹ thuật xử lý).

**17. Analytics**: tần suất lỗi lưu hồ sơ theo phiên bản app (giúp phát hiện regression sau mỗi lần release).

---

## 09_promotion — Khuyến mãi

**1. Mục đích**: giải đáp về voucher/mã giảm giá — điều kiện áp dụng, lý do không dùng được, cách nhận voucher mới.

**2. Dữ liệu cần lưu**: danh mục voucher (mã, điều kiện áp dụng — giá trị đơn tối thiểu, ngành hàng/seller áp dụng, thời hạn), voucher đã lưu của người dùng, trạng thái đã dùng/chưa dùng/hết hạn.

**3. Cấu trúc**: voucher là thực thể độc lập với vòng đời `phát hành → người dùng lưu/nhận → sử dụng trong đơn → (đã dùng | hết hạn chưa dùng)`; có thể là voucher toàn sàn hoặc voucher riêng của seller (tương ứng module `coupon` phía user và `voucher` phía seller).

**4. Quan hệ với domain khác**: áp dụng vào `03_order` lúc đặt hàng, ảnh hưởng số tiền ở `04_payment`, ảnh hưởng cách tính hoàn tiền ở `06_return_refund`.

**5. Intent**: `hoi_dieu_kien_voucher`, `sao_khong_ap_dung_duoc_voucher`, `voucher_het_han`, `lam_sao_nhan_voucher`.

**6. Entity**: `ma_voucher`, `ma_don_hang` (khi hỏi tại sao không áp dụng được lúc đặt đơn cụ thể), `gia_tri_don_hang`.

**7. Keyword**: "mã giảm giá", "voucher", "sao không dùng được mã", "mã hết hạn", "khuyến mãi hôm nay".

**8. Synonym**: "voucher" ~ "mã giảm giá" ~ "coupon" ~ "mã ưu đãi".

**9. Business Flow**: xác định mã voucher → tra cứu điều kiện áp dụng qua API/KB → đối chiếu với đơn/giỏ hàng hiện tại của khách (giá trị đơn, ngành hàng, seller) → nếu không đủ điều kiện, giải thích rõ điều kiện còn thiếu (ví dụ "đơn cần tối thiểu X để áp mã này"); nếu voucher hết hạn/đã dùng, thông báo rõ trạng thái.

**10. Response Template**: mẫu giải thích điều kiện voucher; mẫu thông báo lý do không áp dụng được (theo từng nguyên nhân: chưa đủ giá trị đơn/hết hạn/đã dùng/không áp dụng ngành hàng này); mẫu gợi ý cách nhận voucher mới.

**11. API cần gọi**: `[CẦN XÁC NHẬN]` API tra cứu chi tiết điều kiện/trạng thái voucher theo mã (dựa trên module `coupon`/`voucher` đã có trong code, cần xác nhận endpoint cụ thể lộ ra cho mục đích tra cứu CSKH).

**12. Điều kiện gọi API**: đối chiếu điều kiện voucher luôn cần biết giỏ hàng/đơn hiện tại của đúng người dùng đang hỏi.

**13. Validation**: mã voucher phải đúng định dạng; kiểm tra voucher có thuộc phạm vi người dùng được nhận hay không trước khi giải thích chi tiết.

**14. Exception**: voucher đã bị thu hồi do lỗi hệ thống phát hành nhầm; voucher giới hạn số lượt dùng toàn hệ thống đã hết dù người dùng chưa dùng lần nào; xung đột nhiều voucher không được cộng dồn. Ngoài voucher, sàn còn có **điểm thưởng DP** (dùng để trừ vào tổng tiền lúc thanh toán, có giới hạn số điểm tối đa dùng mỗi đơn) — điểm DP đã sử dụng cho một đơn **không được hoàn lại kể cả khi đơn bị huỷ**; đây là rule cần trả lời rõ ràng mỗi khi khách hỏi về hoàn điểm DP sau huỷ đơn, tránh gây hiểu nhầm rồi phải escalate xử lý khiếu nại.

**15. Escalation CSKH**: khách khẳng định đủ điều kiện nhưng hệ thống báo không áp dụng được (nghi ngờ lỗi), tranh chấp về voucher đã hiển thị nhưng biến mất trước khi dùng.

**16. Logging**: log mã voucher + lý do từ chối áp dụng cho mỗi lượt hỏi (dữ liệu để marketing tối ưu điều kiện voucher).

**17. Analytics**: tỷ lệ voucher bị từ chối áp dụng theo lý do (điều kiện voucher có đang gây khó hiểu cho khách hàng không); voucher bị hỏi nhiều nhất nhưng tỷ lệ dùng thành công thấp (ưu tiên rà soát điều kiện).

---

## 10_policy — Chính sách chung

**1. Mục đích**: kho chính sách nền (đổi trả, vận chuyển, thanh toán, bảo mật dữ liệu, quy định seller) mà các domain nghiệp vụ khác trích dẫn thay vì lặp lại nội dung.

**2. Dữ liệu cần lưu**: từng chính sách có mã định danh, tiêu đề, nội dung tóm tắt dùng cho chatbot (khác bản đầy đủ pháp lý dài dùng cho trang điều khoản), phạm vi áp dụng (toàn sàn/theo ngành hàng/theo seller), ngày hiệu lực.

**3. Cấu trúc**: kho tài liệu tĩnh, đánh mã theo domain liên quan (ví dụ `policy.return.timeframe`, `policy.shipping.cancel_window`) để các domain khác (03/05/06/07/09) tham chiếu bằng mã thay vì chép nội dung, tránh sai lệch khi chính sách cập nhật.

**4. Quan hệ với domain khác**: là "nguồn sự thật" (source of truth) được `03/04/05/06/07/09` trích dẫn con số/điều kiện cụ thể (hạn đổi trả, điều kiện huỷ đơn...).

**5. Intent**: `hoi_chinh_sach_doi_tra`, `hoi_chinh_sach_van_chuyen`, `hoi_chinh_sach_bao_mat`, `hoi_dieu_khoan_su_dung`.

**6. Entity**: `loai_chinh_sach`.

**7. Keyword**: "chính sách đổi trả là gì", "điều khoản sử dụng", "chính sách bảo mật", "quy định huỷ đơn".

**8. Synonym**: "chính sách" ~ "quy định" ~ "điều khoản".

**9. Business Flow**: nhận diện loại chính sách được hỏi → trả lời trực tiếp bằng nội dung tóm tắt trong KB, kèm liên kết tới trang điều khoản đầy đủ nếu khách cần chi tiết pháp lý.

**10. Response Template**: một template tóm tắt cho mỗi loại chính sách chính, luôn có câu dẫn "đây là tóm tắt, nội dung đầy đủ tại [liên kết]".

**11. API cần gọi**: không cần — nội dung tĩnh, chỉ cần cơ chế versioning để cập nhật.

**12. Điều kiện gọi API**: N/A.

**13. Validation**: đảm bảo mã chính sách chatbot trích dẫn khớp với bản chính sách mới nhất (quy trình review định kỳ khi chính sách thay đổi).

**14. Exception**: chính sách có ngoại lệ theo từng seller/ngành hàng mà bản tóm tắt chung không phản ánh hết — khi phát hiện câu hỏi rơi vào ngoại lệ, phải nói rõ "chính sách chung là X, tuy nhiên một số ngành hàng/seller có thể áp dụng khác" thay vì khẳng định tuyệt đối.

**15. Escalation CSKH**: khi khách cho rằng chính sách áp dụng cho họ không công bằng/cần ngoại lệ — đây là quyết định con người, không phải chatbot.

**16. Logging**: log loại chính sách được hỏi nhiều nhất (chỉ báo chính sách nào đang gây khó hiểu, cần viết lại rõ hơn).

**17. Analytics**: tương quan giữa lượt hỏi chính sách và tỷ lệ escalate sau đó (chính sách viết chưa đủ rõ nếu tỷ lệ này cao).

---

## 11_security — Bảo mật tài khoản

**1. Mục đích**: xử lý các vấn đề bảo mật nâng cao hơn `02_account` — đổi mật khẩu khi đang đăng nhập, phát hiện đăng nhập bất thường, nghi ngờ tài khoản bị chiếm quyền, cảnh báo lừa đảo mạo danh Delippy.

**2. Dữ liệu cần lưu**: lịch sử đăng nhập (thiết bị, thời gian, có thể kèm khu vực), danh sách phiên đăng nhập đang hoạt động, cảnh báo bất thường đã gửi cho người dùng, báo cáo lừa đảo/phishing mạo danh do người dùng gửi.

**3. Cấu trúc**: sự kiện bảo mật dạng log theo thời gian gắn với tài khoản; báo cáo lừa đảo là thực thể độc lập (người báo cáo, nội dung, kênh nghi ngờ — tin nhắn/cuộc gọi/link giả mạo).

**4. Quan hệ với domain khác**: mở rộng của `02_account`; liên quan `01_company`/`12_contact` khi cần xác minh kênh chính thức để đối chiếu với nghi ngờ lừa đảo; liên quan `04_payment` nếu nghi ngờ giao dịch gian lận.

**5. Intent**: `doi_mat_khau`, `nghi_ngo_bi_chiem_tai_khoan`, `phat_hien_dang_nhap_la`, `bao_cao_lua_dao_mao_danh`, `hoi_bao_mat_thong_tin_ca_nhan`.

**6. Entity**: `thiet_bi_la`, `thoi_diem_dang_nhap_la`, `kenh_nghi_ngo_lua_dao` (SMS/cuộc gọi/link), `noi_dung_nghi_ngo`.

**7. Keyword**: "đổi mật khẩu", "có ai đăng nhập lạ", "tài khoản của tôi bị ai đó vào", "tin nhắn giả mạo Delippy", "lừa đảo".

**8. Synonym**: "chiếm tài khoản" ~ "hack" ~ "bị vào trộm"; "lừa đảo" ~ "scam" ~ "giả mạo".

**9. Business Flow**:
- *Đổi mật khẩu (đang đăng nhập bình thường)*: hướng dẫn tự thao tác trong app; nếu lỗi, kiểm tra nguyên nhân phổ biến trước khi escalate.
- *Nghi ngờ bị chiếm tài khoản*: đây là tình huống ưu tiên cao nhất trong toàn bộ chatbot — xác thực lại danh tính bằng kênh phụ (không chỉ dựa vào phiên đang đăng nhập, vì phiên đó có thể chính là của kẻ chiếm quyền) → hướng dẫn ngay các bước tự bảo vệ (đổi mật khẩu, đăng xuất mọi thiết bị nếu tính năng này tồn tại) → escalate ngay lập tức, ưu tiên khẩn.
- *Báo cáo lừa đảo mạo danh*: thu thập kênh/nội dung nghi ngờ → xác nhận với khách các kênh chính thức thật của Delippy (đối chiếu `01_company`/`12_contact`) → ghi nhận báo cáo → escalate để đội an ninh/pháp lý xử lý và có thể cảnh báo diện rộng nếu là chiến dịch lừa đảo lớn.

**10. Response Template**: mẫu hướng dẫn đổi mật khẩu; mẫu xử lý khẩn nghi ngờ chiếm tài khoản (văn phong trấn an + hành động ngay, không rườm rà); mẫu xác nhận kênh chính thức khi có nghi ngờ mạo danh; mẫu ghi nhận báo cáo lừa đảo.

**11. API cần gọi**: `[CẦN XÁC NHẬN]` API đổi mật khẩu, API danh sách phiên đăng nhập/thiết bị. `[CẦN BỔ SUNG]` API đăng xuất từ xa mọi thiết bị, API ghi nhận báo cáo lừa đảo mạo danh có cấu trúc (hiện có thể chỉ xử lý thủ công qua kênh liên hệ thường).

**12. Điều kiện gọi API**: các thao tác bảo mật (đổi mật khẩu, đăng xuất từ xa) cần xác thực mạnh hơn mức thông thường trước khi thực hiện qua chatbot.

**13. Validation**: mật khẩu mới phải đáp ứng chính sách độ mạnh; xác nhận đúng là chủ tài khoản trước khi thực hiện bất kỳ thay đổi bảo mật nào.

**14. Exception**: người dùng không còn truy cập được kênh xác thực phụ (mất SĐT/email cũ); báo cáo lừa đảo không đủ thông tin xác minh; nhiều báo cáo trùng lặp về cùng một chiến dịch lừa đảo (cần gộp lại thay vì xử lý rời rạc).

**15. Escalation CSKH**: nghi ngờ chiếm tài khoản luôn escalate mức khẩn nhất trong toàn bộ hệ thống; báo cáo lừa đảo mạo danh luôn escalate (có thể cần hành động pháp lý/cảnh báo cộng đồng người dùng).

**16. Logging**: log riêng biệt, bảo mật cao hơn (hạn chế truy cập nội bộ), lưu đủ dài để phục vụ điều tra nếu cần.

**17. Analytics**: số vụ nghi chiếm tài khoản theo thời gian (chỉ báo cần siết bảo mật đăng nhập); các chiến dịch lừa đảo mạo danh được phát hiện qua tổng hợp báo cáo trùng lặp.

---

## 12_contact — Kênh liên hệ CSKH

**1. Mục đích**: cung cấp thông tin kênh liên hệ chính thức (hotline, email, giờ làm việc, live chat người thật) và là điểm đích của mọi hành vi "escalate" từ các domain khác.

**2. Dữ liệu cần lưu**: danh sách kênh liên hệ theo loại vấn đề (kỹ thuật/đơn hàng/thanh toán/khiếu nại), giờ hoạt động từng kênh, SLA phản hồi cam kết theo kênh/mức độ ưu tiên.

**3. Cấu trúc**: danh mục kênh tĩnh, có gắn nhãn mức độ ưu tiên xử lý (thường/khẩn) để business flow của các domain khác biết escalate vào "hàng đợi" nào.

**4. Quan hệ với domain khác**: là đích đến chung của cơ chế escalation xuyên suốt toàn bộ tài liệu (0.3); tham chiếu `01_company` để xác nhận tính chính danh của kênh liên hệ.

**5. Intent**: `hoi_kenh_lien_he`, `muon_gap_nguoi_that`, `hoi_gio_lam_viec_tong_dai`.

**6. Entity**: `loai_van_de` (để định tuyến đúng kênh/hàng đợi).

**7. Keyword**: "hotline", "tổng đài", "gặp nhân viên", "liên hệ CSKH", "giờ làm việc".

**8. Synonym**: "CSKH" ~ "chăm sóc khách hàng" ~ "hỗ trợ khách hàng"; "hotline" ~ "tổng đài" ~ "số điện thoại hỗ trợ".

**9. Business Flow**: khi người dùng chủ động muốn gặp người thật (không qua một escalation nghiệp vụ cụ thể), xác nhận loại vấn đề để định tuyến đúng hàng đợi → cung cấp kênh phù hợp kèm giờ hoạt động → nếu ngoài giờ, thông báo giờ mở lại và (nếu có) kênh dự phòng 24/7.

**10. Response Template**: mẫu liệt kê kênh liên hệ theo loại vấn đề; mẫu thông báo ngoài giờ làm việc; mẫu xác nhận đã tạo ticket khi escalate kèm thời gian phản hồi dự kiến.

**11. API cần gọi**: `[CẦN BỔ SUNG]` API tạo ticket CSKH có cấu trúc (kèm toàn bộ ngữ cảnh hội thoại + entity đã thu thập từ domain gốc) để nhân viên xử lý không phải hỏi lại từ đầu — đây là hạ tầng quan trọng để việc "escalate" ở mọi domain khác thực sự hiệu quả.

**12. Điều kiện gọi API**: mọi lần escalate nên kèm theo toàn bộ context đã thu thập (domain gốc, entity, lịch sử API đã gọi) để tạo ticket đầy đủ, tránh khách phải lặp lại thông tin.

**13. Validation**: đảm bảo loại vấn đề được gắn đúng để định tuyến hàng đợi, tránh vé bị xử lý sai đội.

**14. Exception**: không xác định được loại vấn đề để định tuyến (câu hỏi mơ hồ) → định tuyến vào hàng đợi tổng quát mặc định thay vì chặn người dùng lại.

**15. Escalation CSKH**: domain này chính là "nơi đến" của escalation nên bản thân không có escalation con — chỉ có việc định tuyến đúng hàng đợi.

**16. Logging**: log mọi ticket được tạo kèm domain gốc/lý do escalate (dữ liệu nền cho phân tích ở mục 0.3 và ở từng domain).

**17. Analytics**: tỷ lệ escalate theo domain gốc (domain nào tự động hoá kém nhất); thời gian xử lý thực tế so với SLA cam kết theo kênh.

---

## 13_faq — Câu hỏi thường gặp chung

**1. Mục đích**: chứa các câu hỏi thường gặp **không thuộc rõ về một domain nghiệp vụ cụ thể nào** (ví dụ "app có phí thường niên không", "làm sao đổi ngôn ngữ app", "sao app bị treo") — tránh việc mọi câu hỏi lặt vặt đều phải ép vào 1 trong 17 domain còn lại.

**2. Dữ liệu cần lưu**: cặp câu hỏi chuẩn hoá – câu trả lời, gắn tag chủ đề để dễ rà soát định kỳ, tần suất được hỏi.

**3. Cấu trúc**: danh sách FAQ dạng cặp hỏi–đáp, có thể có nhiều biến thể câu hỏi (paraphrase) trỏ về cùng một câu trả lời gốc.

**4. Quan hệ với domain khác**: là "lưới an toàn" (fallback nội dung) — nếu intent detection không map được vào domain 01–12/14, thử khớp FAQ trước khi rơi vào không xác định/escalate.

**5. Intent**: `hoi_faq_chung` (một intent bao trùm nhiều chủ đề nhỏ, phân biệt bằng entity chủ đề).

**6. Entity**: `chu_de_faq`.

**7. Keyword**: theo từng câu hỏi cụ thể trong kho FAQ (không có bộ keyword cố định chung).

**8. Synonym**: quản lý theo từng cặp hỏi–đáp (nhiều biến thể diễn đạt cùng trỏ một câu trả lời).

**9. Business Flow**: câu hỏi không khớp domain nghiệp vụ cụ thể → thử khớp trong kho FAQ theo độ tương đồng → nếu khớp đủ tin cậy, trả lời trực tiếp; nếu không khớp gì, coi như "không xác định" và áp dụng cơ chế hỏi lại/escalate chung.

**10. Response Template**: câu trả lời chính là nội dung FAQ, không cần thêm template khung ngoài câu trả lời trực tiếp.

**11. API cần gọi**: không cần — nội dung tĩnh.

**12. Điều kiện gọi API**: N/A.

**13. Validation**: rà soát định kỳ để loại bỏ FAQ lỗi thời (tính năng đã đổi cách hoạt động).

**14. Exception**: câu hỏi tưởng là FAQ chung nhưng thực ra cần dữ liệu cá nhân hoá (ví dụ hỏi chung chung nhưng ý thực sự là hỏi về đơn của họ) → cần rule ưu tiên domain nghiệp vụ cụ thể trước khi rơi về FAQ.

**15. Escalation CSKH**: khi câu hỏi không khớp FAQ nào và cũng không thuộc domain nào rõ ràng, sau khi đã hỏi làm rõ 1–2 lần không thành công.

**16. Logging**: log các câu hỏi không khớp được FAQ nào (nguồn để bổ sung FAQ mới định kỳ).

**17. Analytics**: FAQ được hỏi nhiều nhất (ưu tiên đưa lên gợi ý nhanh trong UI chatbot); tỷ lệ câu hỏi rơi vào "không khớp" (chỉ báo độ phủ của kho FAQ).

---

## 14_error_message — Thư viện thông báo lỗi chuẩn hoá

**1. Mục đích**: chuẩn hoá cách chatbot diễn giải các mã lỗi kỹ thuật từ API thành câu nói dễ hiểu cho người dùng, tránh lộ thông tin kỹ thuật nhạy cảm (mã lỗi, stack trace) ra ngoài.

**2. Dữ liệu cần lưu**: bảng ánh xạ mã lỗi/loại lỗi kỹ thuật (timeout, lỗi xác thực, dữ liệu không tồn tại, lỗi hệ thống chung...) sang câu trả lời thân thiện tương ứng, kèm cờ đánh dấu lỗi nào bắt buộc escalate ngay.

**3. Cấu trúc**: bảng ánh xạ `nhóm lỗi kỹ thuật → câu trả lời chuẩn hoá → có escalate ngay hay không`.

**4. Quan hệ với domain khác**: được **mọi domain nghiệp vụ (01–13)** dùng chung mỗi khi lời gọi API thất bại — đây là tầng "dịch lỗi" nằm ngang toàn hệ thống chứ không gắn riêng một domain nghiệp vụ nào.

**5. Intent**: không có intent riêng — đây là domain hạ tầng được kích hoạt bởi kết quả lỗi từ tầng API, không phải bởi câu hỏi trực tiếp của người dùng.

**6. Entity**: `ma_loi_ky_thuat` (input nội bộ từ tầng API, không phải entity trích từ câu nói người dùng).

**7. Keyword**: N/A (không kích hoạt bằng từ khoá người dùng).

**8. Synonym**: N/A.

**9. Business Flow**: bất kỳ lúc nào một domain nghiệp vụ gọi API và nhận lỗi → tra bảng ánh xạ theo nhóm lỗi → nếu nhóm lỗi được đánh dấu "escalate ngay" (ví dụ lỗi xác thực nhạy cảm, lỗi hệ thống nghiêm trọng), bỏ qua bước trả lời thân thiện và chuyển thẳng CSKH kèm mã lỗi gốc (cho nhân viên, không hiển thị cho khách); nếu không, trả lời bằng câu chuẩn hoá và gợi ý thử lại/chờ.

**10. Response Template**: một template thân thiện cho mỗi nhóm lỗi (ví dụ "hệ thống đang bận, vui lòng thử lại sau ít phút", "không tìm thấy thông tin bạn yêu cầu, bạn có thể kiểm tra lại mã đơn giúp mình không").

**11. API cần gọi**: không tự gọi API — chỉ tiêu thụ kết quả lỗi từ các API mà domain khác đã gọi.

**12. Điều kiện gọi API**: N/A.

**13. Validation**: đảm bảo mọi nhóm lỗi kỹ thuật mới phát sinh (khi backend đổi API) đều được bổ sung ánh xạ, tránh lộ lỗi kỹ thuật thô ra người dùng.

**14. Exception**: lỗi không nằm trong bảng ánh xạ đã biết (lỗi mới/hiếm gặp) → luôn có một câu trả lời "mặc định an toàn" cuối cùng (generic fallback) thay vì để trống hoặc hiển thị lỗi thô.

**15. Escalation CSKH**: các nhóm lỗi được gắn cờ "escalate ngay" (thường là lỗi ảnh hưởng tiền/bảo mật/dữ liệu) theo mục 9.

**16. Logging**: log đầy đủ mã lỗi kỹ thuật gốc kèm domain gọi lỗi (dành cho đội kỹ thuật), tách biệt với log hội thoại hiển thị cho người dùng.

**17. Analytics**: tần suất từng nhóm lỗi theo domain/API (chỉ báo API nào đang kém ổn định, ưu tiên đội backend khắc phục).

---

## 15_tool — Danh mục công cụ (API/action) khả dụng

**1. Mục đích**: là "sổ đăng ký" tất cả các hành động (gọi API, hoặc hành vi hệ thống như tạo ticket) mà tầng Business Flow của mọi domain được phép sử dụng — tách biệt khỏi nội dung nghiệp vụ để một hành động dùng chung (ví dụ "tra cứu đơn hàng") không bị định nghĩa lặp lại ở nhiều domain.

**2. Dữ liệu cần lưu**: tên công cụ, mô tả chức năng, domain nào được phép gọi, tham số đầu vào cần có, điều kiện tiên quyết (ví dụ: yêu cầu đã xác thực), trạng thái khả dụng (đã có/chưa có ở backend).

**3. Cấu trúc**: danh mục phẳng, mỗi công cụ là một bản ghi độc lập, được tham chiếu bởi ID từ phần "API cần gọi" của từng domain nghiệp vụ (01–14) thay vì mỗi domain tự mô tả lại chi tiết kỹ thuật của API.

**4. Quan hệ với domain khác**: là lớp hạ tầng dùng chung cho tất cả — mọi mục "API cần gọi" trong các domain 01–14 ở trên thực chất là tham chiếu tới các bản ghi trong domain này.

**5. Intent**: không áp dụng khái niệm intent (đây không phải nội dung hội thoại).

**6. Entity**: không áp dụng — thay vào đó là "tham số công cụ" (khái niệm tương đương ở lớp kỹ thuật, do Business Flow truyền vào dựa trên entity đã trích được từ intent detection).

**7. Keyword**: không áp dụng.

**8. Synonym**: không áp dụng.

**9. Business Flow**: không tự có luồng hội thoại — được các Business Flow của domain nghiệp vụ khác gọi tới như một bước thực thi.

**10. Response Template**: không tự có template hiển thị cho người dùng — kết quả trả về được domain gọi nó dùng để điền vào template của chính domain đó.

**11. API cần gọi**: chính bản thân domain này liệt kê **toàn bộ** API/action hệ thống hỗ trợ (đây là mục lục kỹ thuật trung tâm).

**12. Điều kiện gọi API**: mỗi công cụ tự khai báo điều kiện tiên quyết riêng (đã xác thực, thuộc domain nào được phép gọi).

**13. Validation**: kiểm tra không có công cụ trùng chức năng được định nghĩa hai lần ở hai nơi khác nhau (nguồn gây sai lệch dữ liệu khi một trong hai bản bị lỗi thời).

**14. Exception**: một domain nghiệp vụ cần một công cụ chưa tồn tại trong danh mục → đây chính là các mục đã đánh dấu `[CẦN BỔ SUNG]` xuyên suốt tài liệu, cần được thêm vào danh mục này trước khi domain nghiệp vụ có thể dùng.

**15. Escalation CSKH**: không áp dụng trực tiếp — nhưng khi một công cụ cần thiết chưa tồn tại, hệ quả là domain gọi nó phải escalate thay vì tự động hoá được.

**16. Logging**: log tần suất gọi từng công cụ theo domain (giúp ưu tiên công cụ nào cần tối ưu hiệu năng/độ ổn định trước).

**17. Analytics**: công cụ nào được gọi nhiều nhất nhưng tỷ lệ lỗi cao nhất (ưu tiên đầu tư ổn định hoá).

---

## 16_dictionary — Từ điển thuật ngữ & chuẩn hoá ngôn ngữ

**1. Mục đích**: kho từ vựng dùng chung để chuẩn hoá cách hiểu ngôn ngữ tự nhiên tiếng Việt (có dấu/không dấu, viết tắt, tiếng lóng thương mại điện tử) trước khi đưa vào tầng Intent Detection — tránh mỗi domain phải tự định nghĩa lại synonym trùng lặp.

**2. Dữ liệu cần lưu**: bảng thuật ngữ – định nghĩa chuẩn, bảng viết tắt phổ biến, bảng chuẩn hoá có dấu/không dấu, danh sách tiếng lóng đặc thù thương mại điện tử/mạng xã hội Việt Nam ("ship", "inbox", "chốt đơn", "seller", "shop").

**3. Cấu trúc**: từ điển ánh xạ nhiều-tới-một (nhiều cách viết → một khái niệm chuẩn), phân nhóm theo domain liên quan để dễ tra cứu (ví dụ nhóm từ vựng "shipping", nhóm từ vựng "payment").

**4. Quan hệ với domain khác**: là nguồn cấp cho mục "Synonym" của **tất cả** domain 01–14 — thay vì mỗi domain định nghĩa synonym độc lập, domain này là nơi quản lý tập trung, các domain khác tham chiếu tới đây để tránh một từ bị định nghĩa khác nhau ở hai nơi.

**5. Intent**: không áp dụng — đây là dữ liệu hỗ trợ tiền xử lý ngôn ngữ, không phải nội dung hội thoại trực tiếp.

**6. Entity**: không áp dụng trực tiếp, nhưng từ điển giúp tầng trích entity nhận diện đúng biến thể viết của cùng một entity (ví dụ nhận "đen" trong "áo màu đen" không lẫn với ý khác).

**7. Keyword**: chính nó là kho keyword/chuẩn hoá dùng chung.

**8. Synonym**: chính nó là kho synonym dùng chung.

**9. Business Flow**: được tầng Rule Engine/Intent Detection tra cứu ở bước tiền xử lý câu, trước khi phân loại intent — không có luồng hội thoại riêng.

**10. Response Template**: không áp dụng.

**11. API cần gọi**: không cần — dữ liệu tĩnh, cập nhật định kỳ dựa trên phân tích log các câu người dùng "không hiểu được" (mục 16 của domain 13_faq và log ở 0.3).

**12. Điều kiện gọi API**: N/A.

**13. Validation**: kiểm tra không có ánh xạ mâu thuẫn (một từ trỏ về hai khái niệm chuẩn khác nhau ở hai nơi).

**14. Exception**: tiếng lóng/viết tắt mới xuất hiện chưa có trong từ điển → sinh ra các lượt intent confidence thấp; đây là tín hiệu để bổ sung từ điển định kỳ (không phải lỗi hệ thống).

**15. Escalation CSKH**: không áp dụng trực tiếp — gián tiếp qua việc từ vựng thiếu làm tăng tỷ lệ confidence thấp dẫn tới escalate nhiều hơn ở domain khác.

**16. Logging**: log các cụm từ không khớp bất kỳ mục nào trong từ điển (input để mở rộng từ điển).

**17. Analytics**: xu hướng ngôn ngữ mới (viết tắt/tiếng lóng mới nổi) theo thời gian, đặc biệt quan trọng vì ngôn ngữ mạng xã hội Việt Nam thay đổi nhanh — cần review từ điển định kỳ (đề xuất hàng tháng) chứ không phải một lần.

---

## 17_response_template — Kho mẫu câu trả lời dùng chung

**1. Mục đích**: quản lý tập trung các mẫu câu trả lời được nhiều domain cùng dùng (ví dụ mẫu xin lỗi vì chậm trễ, mẫu chuyển CSKH, mẫu chào hỏi/kết thúc hội thoại) để đảm bảo giọng văn (tone) nhất quán toàn chatbot, thay vì mỗi domain tự viết một kiểu.

**2. Dữ liệu cần lưu**: mã template, nội dung mẫu kèm biến số (placeholder) cần điền, domain nào dùng, ngữ cảnh sử dụng (mở đầu/giữa/kết thúc hội thoại, escalate, xin lỗi, xác nhận thành công...), biến thể theo mức độ trang trọng nếu cần.

**3. Cấu trúc**: danh mục phẳng theo mã template, phân loại theo "loại tình huống" (thành công/thất bại/đang chờ/escalate/xin thêm thông tin) cắt ngang qua mọi domain nghiệp vụ.

**4. Quan hệ với domain khác**: mọi mục "Response Template" liệt kê trong domain 01–14 ở trên là **các bản mô tả nghiệp vụ cho một template cụ thể** cần được đăng ký chính thức tại đây, kèm biến số lấy từ dữ liệu domain đó hoặc từ kết quả gọi công cụ ở `15_tool`.

**5. Intent**: không áp dụng.

**6. Entity**: không áp dụng — thay vào đó là "biến số template" (giá trị được điền vào từ dữ liệu domain/API, ví dụ `{ma_don_hang}`, `{trang_thai}`, `{so_tien}`).

**7. Keyword**: không áp dụng.

**8. Synonym**: không áp dụng.

**9. Business Flow**: được Business Flow của domain nghiệp vụ gọi ở bước cuối cùng để render câu trả lời — không có luồng hội thoại riêng.

**10. Response Template**: chính bản thân domain này là kho chứa toàn bộ template — không có template mô tả cho chính nó.

**11. API cần gọi**: không cần — nội dung tĩnh, chỉ cần biến số truyền vào từ domain gọi.

**12. Điều kiện gọi API**: N/A.

**13. Validation**: mỗi template phải khai báo rõ tập biến số bắt buộc; kiểm tra không thiếu biến số khi domain nghiệp vụ gọi render (tránh hiển thị placeholder trống cho khách).

**14. Exception**: template thiếu biến số do domain gọi cung cấp sai/thiếu dữ liệu → phải có template "dự phòng" (generic) để không bao giờ hiển thị lỗi render thô cho người dùng.

**15. Escalation CSKH**: không áp dụng trực tiếp.

**16. Logging**: log template nào được dùng nhiều nhất/ít nhất (dọn dẹp template không còn dùng).

**17. Analytics**: đo lường phản hồi người dùng sau từng loại template (nếu có cơ chế đánh giá hài lòng) để tinh chỉnh giọng văn.

---

## 18_business_flow — Danh mục và cấu hình các luồng hội thoại

**1. Mục đích**: là "mục lục trung tâm" của mọi luồng hội thoại (business flow) đã mô tả rải rác ở mục 9 của từng domain 01–14 — giúp nhìn toàn cảnh luồng nào tồn tại, luồng nào phụ thuộc luồng nào, và luồng nào đang escalate nhiều bất thường.

**2. Dữ liệu cần lưu**: tên luồng, domain sở hữu, các bước tuần tự (thu thập entity → gọi công cụ → render template), các điều kiện rẽ nhánh, điều kiện escalate của riêng luồng đó, phiên bản luồng (khi nghiệp vụ thay đổi).

**3. Cấu trúc**: mỗi luồng là một chuỗi bước có điều kiện rẽ nhánh, tham chiếu tới entity (từ Intent Detection), công cụ (`15_tool`) và template (`17_response_template`) — bản thân domain này không định nghĩa lại nội dung mà chỉ **kết nối** ba phần đó thành một kịch bản hoàn chỉnh cho từng domain nghiệp vụ.

**4. Quan hệ với domain khác**: là lớp "nhạc trưởng" kết nối toàn bộ 01–17 — mọi business flow đã mô tả trong mục 9 của các domain nghiệp vụ đều là một bản ghi trong danh mục này.

**5. Intent**: không áp dụng trực tiếp — nhưng mỗi luồng khai báo rõ **danh sách intent nào sẽ kích hoạt nó** (tham chiếu tới mục 5 của domain nghiệp vụ tương ứng).

**6. Entity**: không áp dụng trực tiếp — mỗi luồng khai báo entity bắt buộc/tuỳ chọn cần có trước khi có thể thực thi từng bước (tham chiếu mục 6 của domain nghiệp vụ tương ứng).

**7. Keyword**: không áp dụng.

**8. Synonym**: không áp dụng.

**9. Business Flow**: chính bản thân domain này chứa toàn bộ danh mục luồng — là điểm duy nhất cần rà soát khi muốn biết "chatbot hiện xử lý được những kịch bản gì".

**10. Response Template**: không áp dụng trực tiếp — mỗi bước trong luồng tham chiếu template tương ứng ở `17_response_template`.

**11. API cần gọi**: không áp dụng trực tiếp — mỗi bước gọi công cụ tham chiếu tới `15_tool`.

**12. Điều kiện gọi API**: không áp dụng trực tiếp — điều kiện gọi nằm ở cấp từng bước trong luồng, kế thừa từ điều kiện đã khai báo ở `15_tool` và domain nghiệp vụ sở hữu luồng.

**13. Validation**: kiểm tra mọi luồng đều có ít nhất một điều kiện escalate rõ ràng (không được để một luồng "đi vào ngõ cụt" mà không có lối thoát sang CSKH); kiểm tra không có luồng mồ côi (được một intent trỏ tới nhưng không tồn tại định nghĩa).

**14. Exception**: luồng bị thay đổi nghiệp vụ (ví dụ chính sách huỷ đơn đổi) nhưng chưa cập nhật phiên bản luồng tương ứng → cần quy trình đồng bộ giữa `10_policy` và các luồng phụ thuộc.

**15. Escalation CSKH**: mỗi luồng phải tự khai báo rõ điều kiện escalate riêng (đã mô tả cụ thể ở mục 15 của từng domain nghiệp vụ) — domain này chỉ tổng hợp lại để giám sát toàn cảnh.

**16. Logging**: log ở cấp luồng — luồng nào được kích hoạt bao nhiêu lần, dừng ở bước nào nhiều nhất trước khi hoàn tất hoặc escalate (giúp định vị chính xác bước gây tắc nghẽn trong một luồng dài như đổi trả).

**17. Analytics**: tỷ lệ hoàn tất luồng không cần escalate theo từng luồng (chỉ số hiệu quả tự động hoá quan trọng nhất của toàn hệ thống); luồng có tỷ lệ bỏ dở giữa chừng cao (chỉ báo UX hội thoại của luồng đó cần thiết kế lại các bước hỏi entity).

---

## Tổng kết: khoảng trống cần backend bổ sung để mode `help` hoạt động đầy đủ

Dựa trên khảo sát hiện trạng, để bộ dữ liệu ở trên vận hành được với mức tự động hoá cao thay vì escalate hàng loạt, các API sau cần được ưu tiên bổ sung ở backend chính (không phải microservice AI riêng đang phục vụ mode `chat`):

1. API tạo/tra cứu **yêu cầu đổi trả** phía server (hiện chỉ có lưu cục bộ) — mức ưu tiên cao nhất, vì đổi trả/hoàn tiền là nhóm câu hỏi CSKH phổ biến bậc nhất.
2. API tra cứu **trạng thái hoàn tiền** riêng biệt (hiện không có model refund).
3. Trường trạng thái/tracking **chi tiết hơn** 5 trạng thái kỹ thuật hiện có ở đơn hàng, để phân biệt các giai đoạn trải nghiệm trong bảng vòng đời `05_shipping` (đóng gói/đã bàn giao/đang giao/giao thất bại).
4. API tra cứu **trạng thái tài khoản** (khoá/mở) và **quản lý phiên đăng nhập/thiết bị** phục vụ domain `02_account`/`11_security`.
5. API **tạo ticket CSKH có cấu trúc** kèm ngữ cảnh hội thoại đầy đủ, để mọi hành vi escalate mô tả xuyên suốt tài liệu này thực sự chuyển giao được đầy đủ thông tin cho nhân viên xử lý, thay vì khách phải lặp lại từ đầu.
6. **Đính kèm ngữ cảnh người dùng vào request gửi mode `help`.** Khảo sát cho thấy `chatbot_remote_data_source.dart` hiện chỉ gửi `message` + `session_id` lên microservice AI, **không kèm `user_id`/`order_id`/token** — chatbot không tự biết đang nói chuyện với ai hay về đơn nào. Đây là khoảng trống quan trọng hơn cả việc thiếu API: cho tới khi được vá, **mọi business flow chạm tới dữ liệu cá nhân (đơn hàng, tài khoản, thanh toán) đều bắt buộc phải chủ động hỏi lại định danh** (mã đơn/SĐT đã đặt hàng) ngay từ bước đầu, không được giả định đã biết người dùng là ai — nguyên tắc này áp dụng xuyên suốt các domain `02/03/04/05/06/08/11`.

Cho tới khi các API này sẵn sàng, các domain liên quan (đặc biệt `06_return_refund`) nên được cấu hình để **escalate sớm hơn** thay vì cố tự động hoá bằng dữ liệu chưa đủ tin cậy.
