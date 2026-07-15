# Giải thích toàn bộ JSON Knowledge Base của chatbot CSKH (`/help`)

> Tài liệu này giải thích **từng file JSON thật** đang nằm ở `app/knowledge/help/` — khác với `docs/chatbot-cskh-knowledge-base-design.md` (tài liệu nghiệp vụ gốc, dành cho người đọc) và `app/knowledge/help/README.md` (quy ước schema ngắn gọn cho dev). Ở đây đi sâu vào **từng file cụ thể đang có gì**, để bất kỳ ai (kể cả không đọc code) cũng hiểu được toàn bộ "bộ não dữ liệu" của chatbot CSKH.

Số liệu trong tài liệu này được trích xuất trực tiếp từ file JSON hiện tại (không phải ước lượng) — nếu file thay đổi, số liệu cụ thể (đếm, danh sách id...) có thể lệch, nhưng **cấu trúc và vai trò từng file thì không đổi**.

> **Chỉ cần biết cách thêm/sửa dữ liệu, không cần đọc hết lý thuyết?** Nhảy thẳng xuống [Mục 7 — Hướng dẫn thực hành](#7-hướng-dẫn-thực-hành-thêmsửa-dữ-liệu--dành-cho-người-không-rành-code).

---

## 1. Tổng quan

`app/knowledge/help/` chứa **20 file**: 18 file domain (theo đúng 18 domain của tài liệu nghiệp vụ gốc) + `manifest.json` + `README.md`. Chia làm 2 nhóm:

- **13 file domain nghiệp vụ** (01–13): mỗi file là danh sách **Knowledge Object** — mỗi Knowledge Object = 1 intent người dùng có thể hỏi, chứa đủ mọi thứ chatbot cần để trả lời (từ khoá nhận diện, entity cần hỏi, bước xử lý, template trả lời, quy tắc escalate...).
- **5 file hạ tầng** (14–18): không có "intent" — là các **registry/kho dùng chung** mà 13 file domain tham chiếu tới, để không phải lặp dữ liệu.

```
Knowledge Object (vd: ORDER_CANCEL trong order.json)
   │
   ├─ api_mapping[].tool_id ──────────────► tool.json      (mô tả API/hành động thật)
   ├─ response_templates.success_response ► response_template.json  (nội dung câu trả lời thật)
   ├─ synonyms/keywords ───────────────────► dictionary.json (nguồn chuẩn hoá dùng chung — tham khảo)
   ├─ escalation_rules ─────────────────────► error_message.json / 12_contact (khi lỗi kỹ thuật / cần người thật)
   └─ chính bản thân nó ────────────────────► business_flow.json (mục lục tổng hợp toàn bộ luồng)
```

Nguyên tắc xuyên suốt: **không lặp dữ liệu**. Một Knowledge Object không tự chứa nội dung câu trả lời hay chi tiết kỹ thuật API — nó chỉ **trỏ tới id** trong file hạ tầng tương ứng. Muốn đổi câu trả lời của 5 intent cùng dùng chung 1 template, chỉ cần sửa **1 chỗ** trong `response_template.json`.

---

## 2. Cấu trúc chuẩn của một Knowledge Object (áp dụng cho 13 file domain)

Mỗi phần tử trong mảng `knowledge_objects` có đúng 24 field:

| Field | Ý nghĩa | Ví dụ (từ `ORDER_CANCEL`) |
|---|---|---|
| `id` | Định danh duy nhất, dùng để tham chiếu chéo (từ `business_flow.json`, log...) | `"ORDER_CANCEL"` |
| `domain` | Domain gốc theo đánh số 01–18 | `"03_order"` |
| `sub_domain` | Nhóm nhỏ hơn trong domain, để dễ tra cứu | `"hanh_dong"` |
| `intent` | Tên intent — cái mà tầng Rule Engine/LLM thực sự nhận diện | `"huy_don_hang"` |
| `description` | Mô tả ngắn cho dev/BA đọc | "Huỷ một đơn hàng đang ở trạng thái cho phép huỷ." |
| `keywords` | Từ khoá đặc trưng để Rule Engine so khớp trực tiếp | `["huỷ đơn"]` |
| `synonyms` | Nhóm từ đồng nghĩa `{canonical, variants}` — mở rộng phạm vi khớp từ | `{"canonical":"huỷ đơn","variants":["cancel","không mua nữa","đổi ý"]}` |
| `sample_questions` | Câu hỏi mẫu thực tế, dùng để test/để LLM tham khảo khi cần phân biệt | "Tôi muốn huỷ đơn DEL123456" |
| `entities` | Toàn bộ biến số intent này CÓ THỂ dùng | `["ma_don_hang","ly_do_huy"]` |
| `required_entities` | Biến bắt buộc phải có trước khi xử lý — thiếu thì hỏi lại, không gọi API | `["ma_don_hang"]` |
| `optional_entities` | Biến có thì tốt, không có vẫn xử lý được | `["ly_do_huy"]` |
| `business_rules` | Quy tắc nghiệp vụ dạng câu văn (nguồn: tài liệu gốc, không tự bịa) | "Chỉ cho phép huỷ ở trạng thái pending/processing..." |
| `conversation_flow` | Các bước xử lý tuần tự (để BA/dev đọc hiểu luồng, không phải code) | 6 bước từ "xác định đơn" tới "gọi TOOL_ORDER_CANCEL" |
| `validation_rules` | Điều kiện phải đúng trước khi cho phép hành động | "Validate trạng thái hiện tại nằm trong tập được phép huỷ" |
| `api_mapping` | Danh sách `{tool_id}` — tham chiếu sang `tool.json`, không mô tả lại API | `[{"tool_id":"TOOL_ORDER_DETAIL"},{"tool_id":"TOOL_ORDER_CANCEL"}]` |
| `response_templates` | `{success_response, failure_response}` — **id template**, tham chiếu sang `response_template.json` | `{"success_response":"RT_ORDER_CANCEL_SUCCESS","failure_response":"RT_ORDER_CANCEL_REJECTED"}` |
| `follow_up_questions` | Câu hỏi lại khi thiếu entity | "Bạn cho mình biết lý do huỷ đơn được không?" |
| `escalation_rules` | Điều kiện + mức ưu tiên chuyển người thật | `{"trigger":"...","priority":"high","action":"escalate"}` |
| `logging` | Sự kiện cần ghi log + mức độ nhạy cảm | `{"events":["cancel_attempted",...],"sensitivity":"normal"}` |
| `analytics_tags` | Chỉ số muốn theo dõi theo thời gian | `["order_cancel_rate_via_chatbot_vs_cskh"]` |
| `cache_policy` | Có nên cache câu trả lời không, vì sao | `{"cacheable":false,"reason":"hành động ghi, không cache"}` |
| `ttl` | Thời gian cache hợp lệ (giây) — **hiện hầu hết còn `"TODO"`** | `"TODO"` |
| `priority` | `normal` / `high` / `critical` — quyết định mức escalate | `"normal"` |
| `confidence_threshold` | Ngưỡng độ tin cậy intent tối thiểu — **hiện toàn bộ còn `"TODO"`**, code đang dùng mặc định `0.6` | `"TODO"` |
| `related_intents` | Intent liên quan, để gợi ý luồng tiếp theo | `["kiem_tra_trang_thai_don","yeu_cau_doi_tra"]` |

**Quy ước đánh dấu thiếu dữ liệu**: bất cứ chỗ nào tài liệu nghiệp vụ gốc không có thông tin cụ thể (số tiền, ngưỡng thời gian, nội dung câu trả lời thật...), giá trị được ghi rõ `"TODO"` hoặc `"MISSING_FROM_DOCUMENT"` thay vì suy đoán — xem [[feedback_cskh_no_fabricate_mark_gaps]].

---

## 3. Chi tiết từng file domain nghiệp vụ (01–13)

### 01 — `company.json` (4 Knowledge Object)
Trả lời câu hỏi tĩnh về Delippy: giới thiệu (`hoi_gioi_thieu_cong_ty`), pháp lý (`hoi_phap_ly_cong_ty`), mô hình hoạt động (`hoi_mo_hinh_hoat_dong`), xác minh kênh chính thức khi nghi lừa đảo (`xac_minh_kenh_chinh_thuc`). Không intent nào cần gọi API (`api_mapping` rỗng) — toàn bộ trả lời từ template tĩnh.

### 02 — `account.json` (8 Knowledge Object)
Xử lý *truy cập* tài khoản (khác `08_profile` là *nội dung* hồ sơ): `dang_ky_tai_khoan`, `dang_nhap_loi` (intent phân luồng, tự rẽ sang 3 intent con), `quen_mat_khau`, `khong_nhan_duoc_otp`, `tai_khoan_bi_khoa` (`priority: high`), `yeu_cau_xoa_tai_khoan` (`priority: high`), `lien_ket_mang_xa_hoi`, `kiem_tra_trang_thai_tai_khoan`. Phát hiện và sửa 1 lỗi thật trong lúc build: `ACCOUNT_LOGIN_ERROR`/`ACCOUNT_FORGOT_PASSWORD` từng khai `required_entities: ["so_dien_thoai_hoac_email"]` nhưng field này chưa có trong `entities` — đã bổ sung.

### 03 — `order.json` (7 Knowledge Object)
Domain trọng tâm. `tra_cuu_don_hang`, `kiem_tra_trang_thai_don`, `xem_lich_su_don`, `huy_don_hang` (3 điều kiện escalate — race condition, khiếu nại huỷ nhầm, tranh chấp giá), `sao_don_chua_duoc_xac_nhan`, `don_hang_bi_sai_sot` (dẫn hướng sang `06_return_refund`), `khong_thay_don_hang`. Là domain có nhiều **API thật nhất** (`TOOL_ORDER_LIST/DETAIL/CANCEL/PAYMENT_STATUS` đều `AVAILABLE`).

### 04 — `payment.json` (6 Knowledge Object)
`hoi_phuong_thuc_thanh_toan`, `kiem_tra_trang_thai_thanh_toan`, `da_thanh_toan_nhung_don_chua_len` (`priority: high`), `thanh_toan_that_bai`, `hoi_hoa_don_vat`, `bi_tru_tien_hai_lan` (**`priority: critical`** — duy nhất trong domain thanh toán, luôn escalate ngay, không tự kết luận đúng/sai).

### 05 — `shipping.json` (6 Knowledge Object + bảng `lifecycle_stages`)
File duy nhất có thêm khối `lifecycle_stages` (9 giai đoạn: Đặt hàng → Đã xác nhận → Đóng gói → Đã bàn giao → Đang giao → Giao thất bại → Đã giao → Đổi trả → Hoàn tiền), mỗi giai đoạn ghi rõ trạng thái kỹ thuật tương ứng, khách được làm gì, chatbot phải nói gì/hỏi gì, API nào, khi nào escalate. Đây là bảng ánh xạ "trạng thái trải nghiệm ↔ 5 trạng thái kỹ thuật thô" mà tài liệu gốc yêu cầu. Intent: `tra_cuu_van_don`, `hang_dang_o_dau`, `giao_thieu_du_kien_bao_lau`, `giao_that_bai` (`priority: high`), `doi_dia_chi_giao` (`priority: high`), `chua_nhan_duoc_hang_du_he_thong_bao_da_giao` (**`priority: critical`**).

### 06 — `return_refund.json` (7 Knowledge Object)
Ghi chú `_backend_gap_warning` ngay đầu file: module này **chưa có API server thật**, chỉ lưu cục bộ (`TOOL_RETURN_REQUEST_CREATE_LOCAL`, status `AVAILABLE_LOCAL_ONLY`) — mọi yêu cầu đổi trả hiện tại đều phải tạo ticket cho người xử lý thủ công. Intent: `yeu_cau_doi_tra`, `yeu_cau_hoan_tien`, `kiem_tra_trang_thai_doi_tra`, `san_pham_bi_loi`, `giao_sai_san_pham`, `khong_dung_mo_ta`, `huy_yeu_cau_doi_tra`.

### 07 — `warranty.json` (4 Knowledge Object)
`hoi_thoi_han_bao_hanh`, `yeu_cau_bao_hanh`, `bao_hanh_o_dau`, `san_pham_het_bao_hanh`. Toàn bộ API cần (`TOOL_WARRANTY_POLICY_LOOKUP`, `TOOL_WARRANTY_PURCHASE_DATE_LOOKUP`) đều `MISSING_NEEDS_BUILD` — domain này hiện 100% dựa vào escalate/hướng dẫn tĩnh.

### 08 — `profile.json` (4 Knowledge Object)
Khác `02_account` ở chỗ đây là *nội dung* hồ sơ (tên, avatar, sổ địa chỉ). Chủ trương: **chỉ đọc** (`TOOL_PROFILE_GET`), khuyến khích khách tự sửa trong app thay vì chatbot ghi hộ (giảm rủi ro sai dữ liệu cá nhân qua chat) dù `TOOL_PROFILE_UPDATE` đã `AVAILABLE`.

### 09 — `promotion.json` (4 Knowledge Object)
`hoi_dieu_kien_voucher`, `sao_khong_ap_dung_duoc_voucher`, `voucher_het_han`, `lam_sao_nhan_voucher`. Có quy tắc đặc biệt: điểm thưởng **DP đã dùng không được hoàn khi huỷ đơn** — quy tắc này nằm ở `response_template.json`'s `RT_DP_POINTS_NOT_REFUNDABLE` và được `03_order`'s `ORDER_CANCEL` tham chiếu chéo sang.

### 10 — `policy.json` (4 Knowledge Object)
`hoi_chinh_sach_doi_tra`, `hoi_chinh_sach_van_chuyen`, `hoi_chinh_sach_bao_mat`, `hoi_dieu_khoan_su_dung` — cả 4 dùng chung **1 template duy nhất** (`RT_POLICY_SUMMARY`, tham số hoá theo `loai_chinh_sach`) thay vì 4 template riêng, đúng tinh thần "policy là nguồn sự thật, các domain khác trích dẫn bằng mã".

### 11 — `security.json` (5 Knowledge Object)
`doi_mat_khau`, `nghi_ngo_bi_chiem_tai_khoan` (**`priority: critical`** — ưu tiên khẩn cao nhất toàn hệ thống), `phat_hien_dang_nhap_la` (**`priority: critical`**), `bao_cao_lua_dao_mao_danh` (`priority: high`), `hoi_bao_mat_thong_tin_ca_nhan`.

### 12 — `contact.json` (3 Knowledge Object)
`hoi_kenh_lien_he`, `muon_gap_nguoi_that`, `hoi_gio_lam_viec_tong_dai`. Là "đích đến" của mọi hành vi escalate toàn hệ thống — bản thân domain này không có escalation riêng, chỉ định tuyến đúng hàng đợi.

### 13 — `faq.json` (1 Knowledge Object + `faq_entries`)
Chỉ có 1 Knowledge Object bao trùm (`FAQ_GENERAL`/`hoi_faq_chung`), phân biệt bằng entity `chu_de_faq`. Có thêm mảng `faq_entries` riêng (3 cặp hỏi–đáp mẫu, câu trả lời hiện còn `MISSING_FROM_DOCUMENT`) — là "lưới an toàn" cuối cùng trước khi rơi vào escalate.

---

## 4. Chi tiết từng file hạ tầng (14–18)

### 14 — `error_message.json`
Không có intent (được kích hoạt bởi **lỗi kỹ thuật từ API**, không phải câu hỏi người dùng). Bảng `error_mappings` hiện có **7 nhóm lỗi**: `timeout`, `not_found`, `auth_error_sensitive` (nghi ngờ xâm nhập — escalate ngay), `critical_system_error` (escalate ngay), `unauthenticated` (401 nhưng chưa có token — chỉ hỏi lại định danh, KHÔNG escalate), `rate_limited` (429), `unknown_or_new` (lưới an toàn cuối). Hai nhóm cuối (`unauthenticated`, `rate_limited`) được bổ sung khi build engine thật — bản gốc chỉ có 5 nhóm.

### 15 — `tool.json` (29 tool)
Danh mục toàn bộ API/hành động mà mọi domain có thể gọi tới, mỗi tool có `status`:

| Status | Số lượng | Ý nghĩa |
|---|---|---|
| `AVAILABLE` | 7 | API đã có thật ở backend, engine gọi trực tiếp |
| `AVAILABLE_LOCAL_ONLY` | 1 | Chỉ lưu trên thiết bị, chưa đồng bộ server (`TOOL_RETURN_REQUEST_CREATE_LOCAL`) |
| `NEEDS_CONFIRMATION` | 7 | Có thể đã tồn tại trong code nhưng cần backend xác nhận endpoint cho CSKH |
| `MISSING_NEEDS_BUILD` | 14 | Chưa tồn tại, backend cần xây mới |

7 tool `AVAILABLE`: `TOOL_ORDER_LIST`, `TOOL_ORDER_DETAIL`, `TOOL_ORDER_PAYMENT_STATUS`, `TOOL_ORDER_CANCEL`, `TOOL_PAYMENT_METHODS_LIST`, `TOOL_PROFILE_GET`, `TOOL_PROFILE_UPDATE` — đều đã có method thật trong `app/client/delippy_client.py` và được đăng ký callable trong `app/help/tools.py`. Ghi chú: `TOOL_SHIPPING_TRACKING_DETAIL` tuy JSON để `NEEDS_CONFIRMATION` (chưa xác nhận có API tracking riêng) nhưng engine vẫn tận dụng được bằng cách đọc field `tracks` từ chính `TOOL_ORDER_DETAIL` — `tool.json`'s `status` phản ánh **độ chắc chắn về API backend**, còn `app/help/tools.py`'s `TOOL_REGISTRY` mới là nguồn sự thật cho "có gọi được thật hay không" ở tầng engine.

File cũng có mục `_critical_context_gap` ghi rõ: request `/help` hiện chưa chắc chắn luôn có `token` xác thực — mọi domain đụng dữ liệu cá nhân phải chủ động hỏi lại định danh.

### 16 — `dictionary.json` (28 mục từ vựng)
Từ điển chuẩn hoá dùng chung: mỗi mục có `canonical` (từ chuẩn) + `variants` (biến thể/đồng nghĩa) + `related_domains`. Ví dụ: `"huỷ đơn"` ~ `"cancel"` ~ `"không mua nữa"` ~ `"đổi ý"`. Là nguồn cấp cho field `synonyms` của 13 file domain — domain khác chỉ giữ tập con liên quan, không định nghĩa lại. Có thêm mục `slang_ecommerce_social_vn` (danh sách tiếng lóng ví dụ: "ship", "inbox", "chốt đơn"...) hiện **chưa có định nghĩa chuẩn hoá đầy đủ**, chỉ là danh sách cần bổ sung.

### 17 — `response_template.json` (64 template)
Kho tập trung mọi câu trả lời — 13 file domain chỉ giữ **id template**, nội dung thật nằm ở đây. Mỗi template có `situation_type` (1 trong 7 loại: `success`, `pending`, `failure`, `rejected`, `escalate`, `ask_more_info`, `generic_fallback`), `required_variables` (danh sách `{{placeholder}}` bắt buộc), `content` (nội dung thật hoặc `MISSING_FROM_DOCUMENT`).

**Trạng thái nội dung hiện tại: 30/64 đã có câu trả lời thật, 34/64 còn thiếu.** 30 template đã điền là những nội dung **thuần tuý trình bày/mô tả sự việc đã lấy được** (trạng thái đơn, tracking, phương thức thanh toán, câu chào/xin lỗi/escalate chung...) — **không** đụng tới bất kỳ template nào cần một con số/chính sách thật (hạn đổi trả, thời hạn bảo hành, số hotline, mã số thuế...), theo đúng nguyên tắc không tự bịa nội dung nghiệp vụ.

### 18 — `business_flow.json` (63 flow)
Mục lục trung tâm — mỗi flow (đúng 1-1 với 1 Knowledge Object) liệt kê `domain`, `source_file`, `triggering_intents`, `tools_used`, `templates_used`. Không định nghĩa lại nội dung, chỉ **kết nối**. Có mục `_escalation_path_audit` tự động liệt kê **19 flow chưa có `escalation_rules` riêng** (dựa theo quy tắc chính tài liệu gốc đặt ra: "mọi luồng phải có ít nhất một lối thoát sang CSKH") — đây là checklist cụ thể cho việc rà soát nội dung sau này, không phải lỗi kỹ thuật.

---

## 5. `manifest.json`

File version/mục lục, KHÔNG chứa nội dung nghiệp vụ:
- `kb_version` (hiện `"0.1.0"`) — bump thủ công mỗi khi nội dung thay đổi ý nghĩa, chỉ để người/log biết đang chạy phiên bản nào (không dùng để quyết định reload — việc đó dựa vào mtime file, xem mục 6).
- `domain_files` / `infra_files`: liệt kê 18 file + domain gốc + số Knowledge Object mỗi file (dùng để đối chiếu nhanh, không phải nguồn thật).
- `disabled_intents`: danh sách id được phép "soft-launch" — loại trừ khỏi kiểm tra fail-fast production mà không cần xoá dữ liệu. Hiện đang rỗng.

---

## 6. Các file này được đọc như thế nào (tóm tắt — chi tiết xem `app/help/`)

- `app/knowledge/help/loader.py`'s `HelpKnowledge` (singleton) load cả 20 file vào RAM lúc khởi động, **hot-reload từng file riêng lẻ** khi phát hiện mtime đổi (không cần restart service).
- Hai lớp kiểm tra chạy mỗi lần load: (1) quét `TODO`/`MISSING_FROM_DOCUMENT` còn sót trong Knowledge Object đang bật, (2) kiểm tra toàn vẹn tham chiếu (`tool_id`/template id có tồn tại không, `business_flow.json` có phủ đủ không, mọi Knowledge Object có lối thoát escalate không). Ở `APP_ENV=production`, có lỗi là **từ chối khởi động**; ở dev/staging chỉ log cảnh báo.
- `app/help/rule_engine.py` đọc `keywords`/`synonyms` của cả 63 Knowledge Object để chấm điểm nhận diện intent (0 token LLM cho phần lớn trường hợp); chỉ khi thực sự mơ hồ mới gọi LLM với danh sách rút gọn.
- `app/help/flow_executor.py` đọc trực tiếp `required_entities`/`api_mapping`/`response_templates`/`escalation_rules` của Knowledge Object để quyết định: hỏi thêm gì, gọi tool nào, render template nào, có escalate hay không — **không có nhánh code riêng cho từng domain**, toàn bộ hành vi khác nhau chỉ vì dữ liệu JSON khác nhau.

**Điều quan trọng nhất cần nhớ**: sửa nội dung ở bất kỳ file nào trong 18 file trên → save → chatbot đổi hành vi ngay ở lượt hỏi tiếp theo, không cần sửa code, không cần train lại, không cần restart service.

---

## 7. Hướng dẫn thực hành: thêm/sửa dữ liệu — dành cho người KHÔNG rành code

Mục này dành cho người chỉ cần mở file `.json` bằng một trình soạn thảo text (VS Code, Notepad++...) và gõ tay, không cần biết lập trình. JSON chỉ có vài quy tắc cố định — nắm 5 quy tắc dưới đây là gõ được:

### 7.1 Luật gõ JSON tối thiểu (bắt buộc nhớ)

1. Mọi chữ (text) phải nằm trong dấu ngoặc kép `"..."` — kể cả khi chỉ có 1 từ. Số thì không cần ngoặc kép.
2. Cặp `"key": value` cách nhau bằng dấu hai chấm `:`.
3. Giữa 2 phần tử (2 dòng, 2 mục trong danh sách) phải có dấu phẩy `,` — **trừ phần tử CUỐI CÙNG trong khối `{...}` hoặc `[...]` thì KHÔNG có dấu phẩy sau nó.** Đây là lỗi gõ tay hay gặp nhất.
4. `[...]` = một **danh sách** (có thể rỗng `[]`, có thể nhiều phần tử `["a", "b"]`).
5. `{...}` = một **object** (một nhóm field có tên), y hệt mỗi Knowledge Object hay mỗi template là một `{...}`.

Mẹo kiểm tra không cần biết code: dán toàn bộ nội dung file vào https://jsonlint.com (hoặc bất kỳ "JSON validator" online nào) — nếu báo lỗi, nó sẽ chỉ đúng dòng bị sai (thường là thiếu/thừa dấu phẩy hoặc thiếu dấu ngoặc kép).

### 7.2 Việc hay làm nhất: điền nội dung câu trả lời còn thiếu (`response_template.json`)

Đây là việc business cần làm nhiều nhất hiện tại (34/64 template còn thiếu — xem mục 4, phần 17). Các bước:

1. Mở `app/knowledge/help/response_template.json`.
2. Tìm đúng khối theo `"id"` cần điền — ví dụ muốn điền `RT_WARRANTY_ACTIVE` (mẫu "còn hạn bảo hành"), tìm dòng có `"id": "RT_WARRANTY_ACTIVE"`.
3. Xem field `"required_variables"` của khối đó — đây là danh sách các `{{...}}` BẮT BUỘC phải xuất hiện trong câu trả lời (không được thiếu, không được tự đặt tên khác). Với `RT_WARRANTY_ACTIVE`: `["{{thoi_han_con_lai}}", "{{kenh_nop_yeu_cau}}"]`.
4. Viết câu trả lời thật vào field `"content"`, thay cho dòng `"MISSING_FROM_DOCUMENT — ..."`, nhớ chèn đúng các `{{...}}` bắt buộc ở bước 3 vào đúng chỗ trong câu.

**Trước khi sửa:**
```json
{
  "id": "RT_WARRANTY_ACTIVE",
  ...
  "required_variables": ["{{thoi_han_con_lai}}", "{{kenh_nop_yeu_cau}}"],
  "content": "MISSING_FROM_DOCUMENT — mẫu thông báo còn hạn bảo hành kèm hướng dẫn liên hệ.",
  "notes": "N/A"
}
```

**Sau khi sửa** (chỉ đổi dòng `"content"`, mọi field khác giữ nguyên):
```json
{
  "id": "RT_WARRANTY_ACTIVE",
  ...
  "required_variables": ["{{thoi_han_con_lai}}", "{{kenh_nop_yeu_cau}}"],
  "content": "Sản phẩm của bạn còn {{thoi_han_con_lai}} bảo hành. Bạn liên hệ {{kenh_nop_yeu_cau}} để được hỗ trợ nhé!",
  "notes": "N/A"
}
```

Lưu ý: **không được xoá bớt `{{...}}`** trong `required_variables` khỏi câu trả lời — nếu thiếu, hệ thống sẽ coi template này "render lỗi" và tự động chuyển sang câu trả lời dự phòng chung chung thay vì câu bạn vừa viết (đây là cơ chế an toàn có chủ đích, không phải bug).

### 7.3 Dạy chatbot nhận thêm cách hỏi mới cho 1 intent có sẵn (`keywords`/`synonyms`)

Ví dụ: chatbot chưa nhận ra "sao chưa ai duyệt đơn vậy" cũng có nghĩa là hỏi `ORDER_NOT_CONFIRMED_TOO_LONG` (đơn chưa được xác nhận). Vào đúng file domain (`order.json`), tìm khối có `"id": "ORDER_NOT_CONFIRMED_TOO_LONG"`, thêm câu vào `"keywords"`:

```json
"keywords": ["sao chưa xác nhận", "sao chưa ai duyệt đơn"],
```

Hoặc thêm một nhóm từ đồng nghĩa mới vào `"synonyms"`:
```json
"synonyms": [
  {"canonical": "xác nhận đơn", "variants": ["duyệt đơn", "seller nhận đơn", "ai duyệt đơn"]},
  {"canonical": "chậm trễ", "variants": ["lâu", "trễ"]}
]
```

Quy tắc khi thêm keyword/synonym mới (để không làm rối hệ thống nhận diện):
- **Cụm càng cụ thể càng an toàn.** Một từ chung chung 1 âm tiết (như "đơn", "thanh toán") dùng ở nhiều intent cùng lúc sẽ khiến hệ thống khó phân biệt — nên ưu tiên cụm 2-3 từ đặc trưng riêng cho đúng tình huống đó.
- Không cần thêm biến thể không dấu/gõ tắt thủ công (ví dụ "khong" thay cho "không") — hệ thống tự động bỏ dấu để so khớp, không cần lo phần này.
- Sau khi thêm, nên thử hỏi đúng câu vừa thêm để xem chatbot có nhận đúng intent không (xem mục 7.6).

### 7.4 Thêm hẳn 1 intent (Knowledge Object) hoàn toàn mới

Việc này cần nhiều field hơn nên rủi ro gõ thiếu cao hơn — khuyến nghị: **copy nguyên một Knowledge Object gần giống nhất trong cùng file, rồi sửa lại từng field**, thay vì gõ từ đầu. Checklist các field bắt buộc phải đổi (xem lại ý nghĩa từng field ở mục 2):

1. `id` — đặt tên mới, viết hoa, không trùng với bất kỳ `id` nào khác trong toàn bộ 13 file domain.
2. `intent` — tên intent mới, chữ thường, dùng gạch dưới `_`, không trùng intent khác trong cùng file.
3. `description`, `keywords`, `synonyms`, `sample_questions` — theo tình huống thực tế.
4. `entities`/`required_entities`/`optional_entities` — nhớ mọi giá trị trong `required_entities` phải xuất hiện lại trong `entities` (đây là lỗi hay gặp — xem mục 3, phần `02_account`).
5. `response_templates` — trỏ tới một template **đã tồn tại** trong `response_template.json`, hoặc tạo template mới trước (xem 7.2 nhưng thêm hẳn cả khối `{...}` mới thay vì chỉ sửa `content`).
6. `api_mapping` — nếu chưa biết cần gọi API nào, để `[]` (rỗng), chatbot sẽ tự hiểu là "không có API, không có thì phải hỏi lại/escalate".
7. `escalation_rules` — **không được để trống nếu có thể tránh** (quy tắc bắt buộc của toàn hệ thống — xem mục 4, phần `business_flow.json`).
8. `priority` — `"normal"` cho hầu hết trường hợp; chỉ dùng `"critical"` nếu tình huống thực sự khẩn cấp (an ninh tài khoản, tiền bạc nhạy cảm).
9. Các field còn TODO như `ttl`, `confidence_threshold` — cứ để `"TODO"`, không bắt buộc điền ngay.

**Đừng quên**: sau khi thêm 1 Knowledge Object mới, phải thêm 1 dòng tương ứng vào `business_flow.json`'s mảng `flows` (copy 1 dòng gần giống, sửa `id`/`domain`/`source_file`/`triggering_intents`/`tools_used`/`templates_used`) — nếu quên, hệ thống sẽ tự báo "orphan knowledge object" (xem mục 6, lớp kiểm tra toàn vẹn).

### 7.5 Thêm 1 API/hành động mới mà backend đã xây xong (`tool.json`)

Khi đội backend báo "API X đã xong", vào `app/knowledge/help/tool.json`, tìm đúng `tool_id` đang `"status": "MISSING_NEEDS_BUILD"` hoặc `"NEEDS_CONFIRMATION"`, đổi thành `"AVAILABLE"`, điền lại `service`/`method`/`required_parameters` cho khớp API thật. **Lưu ý quan trọng**: đổi status trong `tool.json` thôi CHƯA đủ để chatbot gọi được API thật — cần báo thêm cho lập trình viên đăng ký "callable" (đoạn code gọi API đó) trong `app/help/tools.py`, đây là bước duy nhất trong toàn bộ quy trình cần chạm code, vì cần biết cách gọi API thật (địa chỉ, tham số) mà JSON không diễn tả được.

### 7.6 Sau khi sửa xong, kiểm tra thế nào (không cần biết code)

- Nếu server đang chạy sẵn (dev), sửa file xong bấm lưu là chatbot dùng nội dung mới ở tin nhắn tiếp theo — không cần ai bấm nút gì thêm (cơ chế hot-reload, xem mục 6).
- Muốn chắc chắn JSON không lỗi cú pháp trước khi nhờ deploy: dán file vào https://jsonlint.com, hoặc nhờ lập trình viên/Claude chạy lệnh kiểm tra tham chiếu chéo (đã có sẵn sẵn trong quy trình build, chạy trong vài giây, tự báo chính xác dòng/id nào sai).
- Nếu gõ sai cú pháp JSON (thiếu dấu phẩy, thiếu ngoặc), **toàn bộ file đó sẽ không đọc được** — không phải chỉ riêng phần bạn sửa. Vì vậy luôn kiểm tra lại (7.6) trước khi báo "xong" cho ai deploy lên môi trường thật.

