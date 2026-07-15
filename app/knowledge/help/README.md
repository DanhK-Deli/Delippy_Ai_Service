# CSKH (`/help`) Knowledge Base — JSON Schema Convention

Nguồn: `docs/chatbot-cskh-knowledge-base-design.md` (Business Document, dành cho người đọc).
Các file JSON trong thư mục này là **Knowledge Data** — dữ liệu duy nhất chatbot mode `help` được đọc trực tiếp. Không domain nào ở đây được tự thêm nghiệp vụ ngoài Business Document; chỗ nào Business Document không đủ chi tiết, giá trị được đánh dấu `"TODO"` hoặc `"MISSING_FROM_DOCUMENT"`.

## Một file = một domain

18 domain của Business Document → 18 file, đúng 1-1, không gộp:

| File | Domain gốc |
|---|---|
| `company.json` | 01_company |
| `account.json` | 02_account |
| `order.json` | 03_order |
| `payment.json` | 04_payment |
| `shipping.json` | 05_shipping |
| `return_refund.json` | 06_return_refund |
| `warranty.json` | 07_warranty |
| `profile.json` | 08_profile |
| `promotion.json` | 09_promotion |
| `policy.json` | 10_policy |
| `security.json` | 11_security |
| `contact.json` | 12_contact |
| `faq.json` | 13_faq |
| `error_message.json` | 14_error_message |
| `tool.json` | 15_tool |
| `dictionary.json` | 16_dictionary |
| `response_template.json` | 17_response_template |
| `business_flow.json` | 18_business_flow |

`return_refund.json` giữ nguyên là **một** file vì Business Document mô tả `ReturnRequest` là một thực thể duy nhất với hoàn tiền là trạng thái con của nó (mục 06, phần 3) — không tách `return.json`/`refund.json` vì điều đó sẽ tạo ra một ranh giới domain mà tài liệu gốc không có.

## Knowledge Object (domain nghiệp vụ 01–14)

Mỗi phần tử trong mảng `knowledge_objects` của các file domain 01–14 có đúng các field theo yêu cầu chuẩn hoá:

`id, domain, sub_domain, intent, description, keywords, synonyms, sample_questions, entities, required_entities, optional_entities, business_rules, conversation_flow, validation_rules, api_mapping, response_templates{success_response, failure_response}, follow_up_questions, escalation_rules, logging, analytics_tags, cache_policy, ttl, priority, confidence_threshold, related_intents`

Quy tắc chống lặp dữ liệu:

- **`api_mapping[].tool_id`** trỏ tới bản ghi trong `tool.json` (id dạng `TOOL_*`) thay vì mô tả lại chi tiết kỹ thuật API. Field `status` trên từng tool (`AVAILABLE` / `NEEDS_CONFIRMATION` / `MISSING_NEEDS_BUILD`) phản ánh nhãn `[ĐÃ CÓ]` / `[CẦN XÁC NHẬN]` / `[CẦN BỔ SUNG]` trong Business Document.
- **`response_templates.success_response` / `failure_response`** là **id template** (dạng `RT_*`), nội dung thật + placeholder (`{{order_id}}`...) nằm trong `response_template.json`.
- **`synonyms`** ở từng knowledge object chỉ là tập con liên quan tới intent đó; nguồn chuẩn hoá đầy đủ (viết tắt, không dấu, tiếng lóng) nằm ở `dictionary.json`.
- **`business_flow.json`** là mục lục tham chiếu ngược lại `intent` (theo `id`) của từng domain 01–14 — không định nghĩa lại nội dung bước, chỉ liệt kê thứ tự bước + entity/tool/template đã tham chiếu.

## Domain hạ tầng (15–18)

`tool.json`, `dictionary.json`, `response_template.json`, `business_flow.json` không có "intent" (Business Document nói rõ `Intent: không áp dụng` ở cả 4 domain này) nên không dùng khuôn Knowledge Object ở trên. Mỗi file có cấu trúc riêng phù hợp vai trò registry của nó, mô tả trong chính file đó qua field `"_domain_role"`.

## Confidence & escalation dùng chung

`confidence_threshold` là ngưỡng intent tối thiểu để tự trả lời (mục 0.3 Business Document): dưới ngưỡng → hỏi lại làm rõ; dưới ngưỡng thấp hơn hoặc lặp lại 2 lần không rõ → escalate. Vì Business Document không cho số cụ thể, mọi `confidence_threshold` trong các file này để `"TODO"` — cần đội phát triển tự đo và điền theo dữ liệu thật, tài liệu chỉ quy định *cơ chế*, không quy định *con số*.

`escalation_rules[].priority` dùng 3 mức xuất hiện xuyên suốt tài liệu: `normal` (theo SLA kênh CSKH thường), `high` (nhạy cảm/tiền/nghiệp vụ chưa có API), `critical` (nghi chiếm tài khoản, lừa đảo mạo danh — mục 11_security, luôn escalate mức khẩn nhất hệ thống).
