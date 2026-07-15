# mobile-cart-flow

# Cart Flow – Mobile Implementation Guide

> **Base:** `/api/v1`
> 

---

## Hai chế độ giỏ hàng

| Chế độ | Khi nào dùng | Auth | Header bắt buộc |
| --- | --- | --- | --- |
| **User Cart** | Đã đăng nhập | Bearer token | `Authorization: Bearer {access_token}` |
| **Guest Cart** | Chưa đăng nhập | Không cần | `X-Guest-Token: {uuid_v4}` |

### Guest Token là gì?

- Là một **UUID v4** do **client tự generate** và lưu trong local storage.
- Không cần đăng ký hay xác nhận với server.
- Dùng như “định danh” của giỏ hàng ẩn danh.
- Khi user đăng nhập → gọi **Merge** để gộp giỏ hàng guest vào tài khoản.

```
Chưa login                         Sau khi login
──────────────────────             ──────────────────────────────
client generate UUID               POST /cart/merge { guest_token }
lưu vào local storage     ──────►  guest items gộp vào user cart
gọi /guest-cart/*                  xóa UUID khỏi local storage
X-Guest-Token: <uuid>              dùng Bearer token từ đây
```

---

## Cấu trúc response giỏ hàng

Mọi thao tác write (thêm / sửa / xóa item) đều trả về **toàn bộ giỏ hàng sau khi cập nhật** — không cần gọi thêm `GET`.

Items được **nhóm theo seller** — mỗi phần tử trong `sellers[]` là một shop, chứa các sản phẩm của shop đó.

```json
{
  "success": true,
  "code": 1000,
  "data": {
    "sellers": [
      {
        "seller_id": 5,
        "seller_name": "Shop ABC",
        "seller_image": "https://...",
        "seller_subtotal": 150000.0,
        "items": [
          {
            "id": 1,
            "product": {
              "id": 10,
              "name": "Sữa Tươi Vinamilk 1L",
              "slug": "sua-tuoi-vinamilk-1l",
              "thumbnail": "https://...",
              "is_tax_inclusive": true,
              "tax_rate": 0.0
            },
            "size": "M",
            "color": "Đỏ",
            "custom_options": [
              { "key": "Hương vị", "value": "Dâu" }
            ],
            "qty": 2,
            "unit_price": 45000.0,
            "unit_price_sp": 500.0,
            "price_shopping_point": 1000.0,
            "line_total": 90000.0
          }
        ]
      }
    ],
    "summary": {
      "item_count": 2,
      "subtotal": 150000.0,
      "shipping_fee": null,
      "total": 150000.0,
      "total_sp_required": 1000.0,
      "sp_vnd_exchange_rate": 1.0
    }
  }
}
```

### Fields của item

| Field | Type | Ghi chú |
| --- | --- | --- |
| `id` | integer | `cart_item_id` — dùng để update/remove và truyền vào `shopping_points`, `vendor_coupon_codes` |
| `product` | object | Thông tin sản phẩm (id, name, slug, thumbnail, is_tax_inclusive, tax_rate) |
| `product.is_tax_inclusive` | boolean | `true` = giá đã bao gồm VAT; `false` = giá chưa bao gồm VAT (thuế tính thêm) |
| `product.tax_rate` | float | Tỷ lệ VAT của sản phẩm (%). `0.0` = không áp dụng thuế |
| `size` | string|null | Kích cỡ đã chọn |
| `color` | string|null | Màu đã chọn (kèm `#`) |
| `custom_options` | array|null | Danh sách tuỳ chọn thêm (key-value); `null` nếu không có |
| `qty` | integer | Số lượng |
| `unit_price` | float | Đơn giá tiền mặt (đã tính thêm size/option) |
| `unit_price_sp` | float | Đơn giá điểm DP per đơn vị — số điểm cần để “mua” 1 sản phẩm này bằng DP |
| `price_shopping_point` | float | Tổng điểm DP tối đa cho item này = `unit_price_sp × qty` |
| `line_total` | float | Tổng tiền mặt của item = `unit_price × qty` (không tính phần DP) |

### Fields của summary

| Field | Type | Ghi chú |
| --- | --- | --- |
| `item_count` | integer | Tổng số lượng (sum qty), dùng cho badge icon giỏ hàng |
| `subtotal` | float | Tổng tiền mặt toàn giỏ (chưa bao gồm phần DP) |
| `shipping_fee` | null | Luôn `null` — phí ship chưa được tính tại đây |
| `total` | float | Bằng `subtotal` — chưa trừ giảm giá, phí ship |
| `total_sp_required` | float | Tổng điểm DP tối đa nếu dùng 100% DP cho toàn giỏ |
| `sp_vnd_exchange_rate` | float | Tỷ giá: 1 điểm DP = X VNĐ (do admin cấu hình) |

> `sellers` là mảng rỗng `[]` khi giỏ hàng trống.
> 
> 
> `seller_subtotal` là tổng `line_total` của tất cả items trong shop đó.
> 
> `unit_price_sp = 0` nghĩa là sản phẩm không hỗ trợ thanh toán bằng DP.
> 
> `product.is_tax_inclusive = false` → sản phẩm áp dụng VAT thêm vào giá. Hiển thị badge “+VAT” hoặc dòng ghi chú thuế trên UI cart.
> 

### Hiển thị thuế trên cart (per-item)

Mỗi sản phẩm có cấu hình thuế riêng. Mobile có thể tính và hiển thị tiền thuế ước tính ngay trên màn hình giỏ hàng mà không cần gọi thêm API:

```
// Với từng item:
is_tax_inclusive = true   →  giá hiển thị đã gồm VAT, không hiện thêm gì
is_tax_inclusive = false  →  tính và hiện tiền thuế thêm:
  tax_estimate = item.unit_price × item.qty × item.product.tax_rate / 100
```

> Tiền thuế chính xác sẽ được tính lại server-side khi gọi `POST /orders/preview` — dùng giá trị từ `amounts.tax_amount` trong response preview để hiển thị trên màn hình checkout.
> 

---

### Tính toán DP trên client (không cần gọi thêm API)

Với `sp_vnd_exchange_rate` trong summary và `price_shopping_point` của từng item, mobile có thể tính ngay:

```
// Giá trị VNĐ của item khi dùng X điểm:
vnd_saved = X × sp_vnd_exchange_rate

// Phần tiền mặt phải trả thêm cho phần DP còn lại:
dp_cash = (price_shopping_point - X) × sp_vnd_exchange_rate

// Kiểm tra user đủ điểm không:
can_use = user.shopping_point >= total_chosen_points

// Số dư sau khi dùng:
remaining = user.shopping_point - total_chosen_points
```

---

# PHẦN A — User Cart (đã đăng nhập)

> Header: `Authorization: Bearer {access_token}`
> 
> 
> Base: `/api/v1/cart`
> 

---

## A1. Xem giỏ hàng – `GET /api/v1/cart`

Trả về giỏ hàng hiện tại.

### Response (HTTP 200)

Cấu trúc giống phần trên. Giỏ rỗng thì `sellers: []`, `summary.item_count: 0`.

---

## A2. Thêm sản phẩm – `POST /api/v1/cart/items`

> Cùng variant (product + size + color + custom_options) đã có → **cộng dồn số lượng**, không tạo item mới.
> 

### Request

```json
{
  "product_id": 10,
  "qty": 2,
  "size": "M",
  "color": "Đỏ",
  "custom_option_key": ["Hương vị"],
  "custom_option_value": ["Dâu"]
}
```

| Field | Type | Bắt buộc | Ghi chú |
| --- | --- | --- | --- |
| `product_id` | integer | **Có** | `id` từ response chi tiết sản phẩm |
| `qty` | integer (1–99) | **Có** |  |
| `size` | string | Không | Lấy từ `sizes[].name` của product detail |
| `color` | string | Không | Lấy từ `variant_colors[]` của product detail |
| `custom_option_key` | array<string> | Không | Lấy từ `custom_options[].key` |
| `custom_option_value` | array<string> | Không | Giá trị theo **cùng index** với key |

### Response (HTTP 200)

Giỏ hàng đầy đủ sau khi thêm.

### ❌ Lỗi

| HTTP | Ý nghĩa |
| --- | --- |
| `400` | Hết hàng — `"Sản phẩm không đủ số lượng trong kho."` |
| `404` | Sản phẩm không tồn tại hoặc ngừng bán |
| `422` | Validation lỗi field |

---

## A3. Cập nhật số lượng – `PUT /api/v1/cart/items/{id}`

> `{id}` là `items[].id` trong response giỏ hàng — **không phải** `product_id`.
> 

### Request

```json
{ "qty": 5 }
```

> `qty` phải từ **1–99**. Muốn xóa item thì dùng `DELETE`, không dùng `qty=0`.
> 

### Response (HTTP 200)

Giỏ hàng đầy đủ sau khi cập nhật.

---

## A4. Xóa một item – `DELETE /api/v1/cart/items/{id}`

### Response (HTTP 200)

Giỏ hàng đầy đủ sau khi xóa.

---

## A5. Xóa nhiều item – `DELETE /api/v1/cart/items`

> Dùng khi user chọn nhiều sản phẩm rồi nhấn “Xóa đã chọn”.
> 

### Request

```json
{ "ids": [1, 2, 3] }
```

| Field | Type | Bắt buộc | Ghi chú |
| --- | --- | --- | --- |
| `ids` | array<integer> | **Có** | Mảng `items[].id` từ response giỏ hàng, ít nhất 1 phần tử |

> ID không thuộc giỏ hàng của user sẽ bị **bỏ qua silently** — không báo lỗi.
> 

### Response (HTTP 200)

Giỏ hàng đầy đủ sau khi xóa.

### ❌ Lỗi

| HTTP | Ý nghĩa |
| --- | --- |
| `422` | `ids` thiếu hoặc không phải array |

---

## A6. Xóa toàn bộ giỏ hàng – `DELETE /api/v1/cart`

### Response (HTTP 200)

```json
{ "success": true, "code": 1000, "data": null }
```

---

## A7. Merge giỏ hàng guest – `POST /api/v1/cart/merge`

> Gọi ngay sau khi đăng nhập / đăng ký thành công nếu client có lưu `guest_token`.
> 

### Request

```json
{ "guest_token": "550e8400-e29b-41d4-a716-446655440000" }
```

### Merge logic

| Trường hợp | Kết quả |
| --- | --- |
| Guest có item A, user cart **không** có item A | Item A chuyển sang user cart |
| Guest có item A (qty 2), user cart **đã có** item A (qty 3) | qty = 5, capped tại stock tối đa |
| Guest cart **không có item** (token hợp lệ nhưng rỗng / đã merge trước đó) | 200, user cart không đổi |
| Sản phẩm trong guest cart đã **ngừng bán / bị xóa** | Item đó bị bỏ qua silently — không báo lỗi |
| `guest_token` thiếu hoặc không đúng format UUID | **422** validation error |

### Response (HTTP 200)

Giỏ hàng user đầy đủ sau merge.

---

# PHẦN B — Guest Cart (chưa đăng nhập)

> Header: `X-Guest-Token: {uuid_v4}` ← **bắt buộc cho mọi request**
> 
> 
> Base: `/api/v1/guest-cart`
> 
> Không cần Bearer token.
> 

### Cách tạo guest token phía client

```dart
// Flutter
import 'package:uuid/uuid.dart';
final guestToken = const Uuid().v4(); // "550e8400-e29b-41d4-a716-446655440000"
// Lưu vào SharedPreferences để dùng lại
```

```swift
// iOS Swift
let guestToken = UUID().uuidString.lowercased()
// Lưu vào UserDefaults
```

```kotlin
// Android Kotlin
val guestToken = UUID.randomUUID().toString()
// Lưu vào SharedPreferences
```

### ❌ Lỗi token không hợp lệ (HTTP 400)

Trả về khi thiếu header hoặc token không đúng format UUID v4:

```json
{
  "success": false,
  "code": 3001,
  "message": "Header X-Guest-Token hợp lệ (UUID v4) là bắt buộc."
}
```

---

## B1. Xem giỏ hàng – `GET /api/v1/guest-cart`

### Response (HTTP 200)

Cấu trúc giống User Cart. Giỏ rỗng → `sellers: []`.

---

## B2. Thêm sản phẩm – `POST /api/v1/guest-cart/items`

Cùng body và logic cộng dồn như [A2](about:blank#a2-th%C3%AAm-s%E1%BA%A3n-ph%E1%BA%A9m--post-apiv1cartitems).

```json
{
  "product_id": 10,
  "qty": 1,
  "size": "L"
}
```

### Response (HTTP 200)

Giỏ hàng guest đầy đủ sau khi thêm.

---

## B3. Cập nhật số lượng – `PUT /api/v1/guest-cart/items/{id}`

```json
{ "qty": 3 }
```

### Response (HTTP 200)

Giỏ hàng guest đầy đủ.

---

## B4. Xóa một item – `DELETE /api/v1/guest-cart/items/{id}`

### Response (HTTP 200)

Giỏ hàng guest đầy đủ.

---

## B5. Xóa nhiều item – `DELETE /api/v1/guest-cart/items`

> Header: `X-Guest-Token: {uuid_v4}` bắt buộc.
> 

### Request

```json
{ "ids": [1, 2, 3] }
```

> ID không thuộc guest token sẽ bị **bỏ qua silently**.
> 

### Response (HTTP 200)

Giỏ hàng guest đầy đủ sau khi xóa.

---

## B6. Xóa toàn bộ – `DELETE /api/v1/guest-cart`

### Response (HTTP 200)

```json
{ "success": true, "code": 1000, "data": null }
```

---

# Sơ đồ flow tổng quát

```
╔══════════════════════════════════════════════════════════════╗
║                  USER CHƯA ĐĂNG NHẬP                        ║
╚══════════════════════════════════════════════════════════════╝

Lần đầu mở app
└── Không có guest_token → generate UUID v4 → lưu local storage

Browse sản phẩm → nhấn "Thêm vào giỏ"
└── POST /guest-cart/items  (X-Guest-Token: <uuid>)
    ├── 200 → update UI giỏ hàng
    └── 400 hết hàng → thông báo

Màn hình giỏ hàng
├── GET  /guest-cart              → render
├── PUT  /guest-cart/items/{id}   → đổi qty
├── DEL  /guest-cart/items/{id}   → xóa 1 item
├── DEL  /guest-cart/items        → xóa nhiều item { ids: [...] }
└── DEL  /guest-cart              → xóa tất cả

╔══════════════════════════════════════════════════════════════╗
║               USER ĐĂNG NHẬP / ĐĂNG KÝ                     ║
╚══════════════════════════════════════════════════════════════╝

Sau khi nhận access_token:
├── Có guest_token trong local storage?
│   ├── YES → POST /cart/merge { guest_token }
│   │         → xóa guest_token khỏi local storage
│   │         → dùng response để update state giỏ hàng
│   └── NO  → GET /cart để load giỏ hàng hiện tại
└── Từ đây dùng User Cart

╔══════════════════════════════════════════════════════════════╗
║                  USER ĐÃ ĐĂNG NHẬP                          ║
╚══════════════════════════════════════════════════════════════╝

Browse sản phẩm → nhấn "Thêm vào giỏ"
└── POST /cart/items  (Authorization: Bearer <token>)
    ├── 200 → update UI
    ├── 400 hết hàng → thông báo
    └── 401 token hết hạn → refresh token → retry

Màn hình giỏ hàng
├── GET  /cart              → render
├── PUT  /cart/items/{id}   → đổi qty
├── DEL  /cart/items/{id}   → xóa 1 item
├── DEL  /cart/items        → xóa nhiều item { ids: [...] }
└── DEL  /cart              → xóa tất cả

Badge icon giỏ hàng
└── summary.item_count (tổng qty tất cả items)
```

---

## Lưu ý quan trọng

| # | Ghi chú |
| --- | --- |
| 1 | Mọi thao tác write trả về giỏ hàng đầy đủ — **dùng luôn response** để update UI, không gọi GET lại |
| 2 | Khi add item có variants: **phải truyền đủ** `size`, `color`, `custom_option_key/value` — thiếu field nào server hiểu là `null` và tạo variant khác |
| 3 | `custom_option_key` và `custom_option_value` là 2 mảng song song — **index phải khớp nhau** |
| 4 | `item_count` trong summary dùng để hiển thị **badge số** trên icon giỏ hàng |
| 5 | `{id}` trong path là `sellers[].items[].id` — **không phải** `product_id` |
| 6 | Guest token phải là **UUID v4 hợp lệ** — server reject token sai format |
| 7 | **Merge chỉ cần gọi 1 lần** ngay sau login. Nếu không có guest_token thì bỏ qua bước merge |
| 8 | Sau merge, qty bị **cap tại stock** nếu tổng vượt quá — không throw lỗi, giá trị tối đa có thể thấp hơn tổng mong đợi |
| 9 | Khi logout: **không xóa** giỏ hàng user — cart vẫn giữ nguyên cho lần đăng nhập tiếp theo |
| 10 | Bulk delete (`DEL /cart/items`) nhận mảng `ids` — ID không thuộc giỏ hàng bị **bỏ qua silently**, không báo lỗi 404 |
| 11 | `sellers[].seller_subtotal` là tổng riêng của shop đó — dùng để hiển thị subtotal theo từng seller trong checkout |
| 12 | `unit_price_sp = 0` → sản phẩm không hỗ trợ DP — ẩn UI điểm cho item đó |
| 13 | `total_sp_required` là tổng điểm nếu dùng **100% DP** cho toàn giỏ — user có thể dùng ít hơn (partial) |
| 14 | `sp_vnd_exchange_rate` dùng để convert điểm ↔︎ VNĐ trên UI mà không cần thêm API call |
| 15 | Số dư DP của user lấy từ `GET /profile` → `shopping_point`; so sánh với `total_sp_required` để biết user đủ/thiếu điểm |

---

## Changelog

| Ngày | Phiên bản | Thay đổi |
| --- | --- | --- |
| — | v1.0 | Khởi tạo: user cart (get, add, update, remove, clear, merge), guest cart |
| 2026-06-08 | v1.1 | Thêm bulk delete: `DELETE /cart/items` và `DELETE /guest-cart/items` với body `{ ids: [...] }` |
| 2026-06-19 | v1.2 | Thêm `unit_price_sp`, `price_shopping_point` vào item response. Thêm `total_sp_required`, `sp_vnd_exchange_rate` vào summary. Thêm bảng fields và hướng dẫn tính DP trên client |
| 2026-06-10 | v1.2 | **Breaking change**: response đổi từ `data.items[]` sang `data.sellers[].items[]` — items nhóm theo seller |
| 2026-06-26 | v1.3 | Thêm `product.is_tax_inclusive` (bool) và `product.tax_rate` (float, %) vào mỗi cart item. Bổ sung hướng dẫn hiển thị thuế per-item trên cart screen |