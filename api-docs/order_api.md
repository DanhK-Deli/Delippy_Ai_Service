# mobile-order-flow

# Order Flow – Mobile Implementation Guide

> **Yêu cầu Bearer token** cho hầu hết endpoint.
> 
> 
> Header: `Authorization: Bearer {access_token}`
> 
> Base đơn hàng: `/api/v1/orders` | Base tham khảo: `/api/v1/shipping-methods`, `/api/v1/payment-methods`
> 

---

## Tổng quan luồng đặt hàng

```
Màn hình checkout (khởi tạo — public, không cần auth)
├── GET /shipping-methods  →  load danh sách phương thức vận chuyển
└── GET /payment-methods   →  load danh sách phương thức thanh toán

Giỏ hàng đã có item (Cart screen)
└── User nhấn "Mua hàng"
    └── POST /orders/preview  →  breakdown đầy đủ (đã bao gồm shipping_fee) → navigate Checkout screen

Màn hình checkout (yêu cầu Bearer token)
├── User chọn địa chỉ giao hàng (GET /addresses)
├── User chọn shipping_type từ danh sách /shipping-methods
├── User chọn payment_method từ danh sách /payment-methods
├── (Tuỳ chọn) User nhập coupon_code / vendor coupon / điểm DP
└── POST /orders  →  đặt hàng → nhận order_number

  Nếu payment_method = cod
  └── navigate màn hình "Đặt hàng thành công"

  Nếu payment_method = sepay
  └── navigate màn hình QR thanh toán
      ├── Hiển thị QR từ data.payment.qr_code_url
      ├── Polling GET /orders/{orderNumber}/payment-status mỗi 4–5 giây
      │   ├── payment_status = "paid"     → navigate "Thanh toán thành công"
      │   ├── payment_status = "expired"  → hiện thông báo hết hạn
      │   └── payment_status = "pending"  → tiếp tục polling
      └── User nhấn "Huỷ" → POST /orders/{orderNumber}/cancel

Màn hình đơn hàng
├── GET /orders                                  →  danh sách đơn, lọc theo status
├── GET /orders/{orderNumber}                    →  chi tiết + tracking
├── GET /orders/{orderNumber}/payment-status     →  kiểm tra trạng thái thanh toán SePay
└── POST /orders/{orderNumber}/cancel            →  huỷ đơn (chỉ được khi pending/processing)
```

---

## Trạng thái đơn hàng

| `status` | `status_label` | Có thể huỷ? |
| --- | --- | --- |
| `pending` | Chờ xác nhận | ✅ |
| `processing` | Đang xử lý | ✅ |
| `on delivery` | Đang giao hàng | ❌ |
| `completed` | Hoàn thành | ❌ |
| `declined` | Đã huỷ | ❌ |

> Dùng `status_label` để **hiển thị trên UI**. Dùng `status` để **lọc danh sách** và **logic điều kiện**.
> 

---

## Phương thức vận chuyển

> Lấy động từ `GET /api/v1/shipping-methods` — dùng `key` làm giá trị `shipping_type` khi đặt hàng.
> 

| `key` (`shipping_type`) | `label` | Mô tả |
| --- | --- | --- |
| `deligo` | Giao hàng Deligo | Giao hàng qua Deligo |
| `viettelpost` | Viettel Post | Giao hàng qua Viettel Post |
| `flat_rate` | Phí cố định | Phí ship cố định theo cấu hình |
| `free` | Miễn phí | Miễn phí vận chuyển |

## Phương thức thanh toán

> Lấy động từ `GET /api/v1/payment-methods` — dùng `key` làm giá trị `payment_method` khi đặt hàng.
> 

| `key` (`payment_method`) | `label` | Mô tả |
| --- | --- | --- |
| `cod` | COD | Thanh toán khi nhận hàng (Cash on Delivery) |
| `sepay` | SePay | Thanh toán online qua QR chuyển khoản ngân hàng |

> Khi dùng `sepay`, response trả thêm block `payment` chứa QR code URL và nội dung chuyển khoản.
> 

### Trạng thái thanh toán (`payment_status`)

| Giá trị | Ý nghĩa |
| --- | --- |
| `Pending` | Chờ thanh toán (COD: chờ nhận hàng, SePay: chờ chuyển khoản) |
| `paid` | Đã thanh toán (SePay xác nhận) |
| `expired` | QR hết hạn — user cần đặt lại đơn |
| `failed` | Thanh toán thất bại |
| `cancelled` | Đã huỷ |

> **Lưu ý:** `payment_status` ở trường gốc của order trả về dạng capitalize (`"Pending"`), còn trong block `payment` và endpoint polling trả về lowercase (`"pending"`, `"paid"`, …). Xem chi tiết bên dưới.
> 

---

## 0.1. Danh sách phương thức vận chuyển – `GET /api/v1/shipping-methods`

> **Public — không cần auth.** Gọi khi mở màn hình checkout để hiển thị danh sách phương thức vận chuyển cho user chọn.
> 

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": [
    {
      "key": "deligo",
      "label": "Giao hàng Deligo",
      "description": "Giao hàng nhanh qua Deligo",
      "estimated_days": 2,
      "is_active": true
    },
    {
      "key": "viettelpost",
      "label": "Viettel Post",
      "description": null,
      "estimated_days": null,
      "is_active": true
    }
  ]
}
```

| Field | Type | Ghi chú |
| --- | --- | --- |
| `key` | string | Dùng làm giá trị `shipping_type` khi gọi `POST /orders` hoặc `POST /orders/shipping-fee` |
| `label` | string | Tên hiển thị trên UI |
| `description` | string|null | Mô tả ngắn — có thể null |
| `estimated_days` | integer|null | Số ngày giao hàng ước tính — có thể null |
| `is_active` | boolean | `true` = đang hoạt động — chỉ hiện các phương thức `is_active: true` |

---

## 0.2. Danh sách phương thức thanh toán – `GET /api/v1/payment-methods`

> **Public — không cần auth.** Gọi khi mở màn hình checkout để hiển thị danh sách phương thức thanh toán cho user chọn.
> 

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": [
    {
      "key": "cod",
      "label": "COD",
      "description": "Thanh toán khi nhận hàng",
      "is_active": true
    },
    {
      "key": "sepay",
      "label": "SePay",
      "description": "Thanh toán qua QR chuyển khoản ngân hàng",
      "is_active": true
    }
  ]
}
```

| Field | Type | Ghi chú |
| --- | --- | --- |
| `key` | string | Dùng làm giá trị `payment_method` khi gọi `POST /orders` |
| `label` | string | Tên hiển thị trên UI |
| `description` | string | Mô tả ngắn |
| `is_active` | boolean | `true` = đang hoạt động — chỉ hiện các phương thức `is_active: true` |

> API này thay thế endpoint cũ `/api/v1/user/paymentgateway` (deprecated).
> 

---

## 1. Ước tính phí ship – `POST /api/v1/orders/shipping-fee`

> Gọi trước khi đặt hàng để hiển thị phí ship cho user. Giỏ hàng phải có item.
> 

### Request

```json
{
  "shipping_type": "deligo",
  "province_id": 1,
  "district_id": 10
}
```

| Field | Type | Bắt buộc | Ghi chú |
| --- | --- | --- | --- |
| `shipping_type` | string | **Có** | `deligo` / `viettelpost` / `flat_rate` / `free` |
| `province_id` | integer | **Có** | ID tỉnh của địa chỉ giao hàng |
| `district_id` | integer | **Có** | ID quận của địa chỉ giao hàng |

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": {
    "shipping_fee": 30000.0
  }
}
```

> Trả về `0.0` nếu giỏ hàng rỗng — không báo lỗi.
> 
> 
> Phí này là **ước tính**, phí thực tế sẽ được xác nhận khi đặt hàng.
> 

### ❌ Lỗi

| HTTP | Ý nghĩa |
| --- | --- |
| `422` | Thiếu field hoặc `province_id` / `district_id` không tồn tại |

---

## 2. Preview tổng đơn hàng – `POST /api/v1/orders/preview`

> **Không tạo đơn, không thay đổi dữ liệu.**
> 
> 
> Gọi **1 lần khi user nhấn “Mua hàng” từ cart screen** để lấy breakdown chính xác trước khi hiển thị checkout screen.
> 
> Flow 2 màn hình (giống Shopee):
> - **Cart screen** — chọn coupon + DP, xem tổng ước tính (tính local, chưa có shipping)
> - **User nhấn “Mua hàng”** → gọi `POST /orders/preview` **1 lần** → navigate checkout
> - **Checkout screen** — hiển thị breakdown từ preview (đã bao gồm `shipping_fee`), xác nhận địa chỉ/shipping/payment → đặt hàng
> 
> ⚠️ **Không gọi `POST /orders/shipping-fee` riêng** — preview đã tính shipping bên trong, gọi thêm là thừa (2 lần hit external API).
> 
> Nếu user thay đổi địa chỉ hoặc `shipping_type` trên checkout → gọi lại `POST /orders/preview` (debounce 500ms).
> 
> Xem chi tiết tại [mobile-coupon-flow.md § Flow khuyến nghị](mobile-coupon-flow.md#flow-khuyến-nghị--tối-ưu-ux).
> 

### Request

```json
{
  "shipping_type": "deligo",
  "province_id": 1,
  "district_id": 10,
  "payment_method": "cod",
  "coupon_code": "SALE10",
  "vendor_coupon_codes": {
    "5": "SHOP10",
    "8": "VND20"
  },
  "shopping_points": {
    "123": 100,
    "456": 50
  }
}
```

| Field | Type | Bắt buộc | Ghi chú |
| --- | --- | --- | --- |
| `shipping_type` | string | **Có** | `deligo` / `viettelpost` / `flat_rate` / `free` |
| `province_id` | integer | **Có** | ID tỉnh của địa chỉ giao hàng |
| `district_id` | integer | **Có** | ID quận của địa chỉ giao hàng |
| `payment_method` | string | Không | `cod` / `sepay` — ảnh hưởng phí COD của một số nhà vận chuyển |
| `coupon_code` | string | Không | Mã giảm giá platform |
| `vendor_coupon_codes` | object | Không | Map `vendor_id → coupon_code` — **1 mã per shop**, key là `seller_id` từ `GET /cart` |
| `shopping_points` | object | Không | Map `cart_item_id → số điểm DP` muốn dùng |

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": {
    "amounts": {
      "products": 450000.0,
      "shipping_fee": 30000.0,
      "coupon_discount": 45000.0,
      "vendor_discount": 20000.0,
      "sp_amount": 10000.0,
      "tax_amount": 0.0,
      "total": 405000.0
    }
  }
}
```

| Field | Type | Ghi chú |
| --- | --- | --- |
| `products` | float | Tổng tiền hàng (trước giảm giá) |
| `shipping_fee` | float | Phí vận chuyển ước tính |
| `coupon_discount` | float | Giảm từ coupon platform |
| `vendor_discount` | float | Giảm từ vendor coupon (tổng tất cả shop) |
| `sp_amount` | float | Giá trị VND của điểm DP được dùng |
| `tax_amount` | float | Tổng tiền thuế VAT = tổng `(item_price × qty + price_sp) × tax_rate / 100` của các sản phẩm có `is_tax_inclusive = false` |
| `total` | float | Số tiền user cần thanh toán |

### ❌ Lỗi

| HTTP | Ý nghĩa |
| --- | --- |
| `400` | Giỏ hàng rỗng / mã coupon không hợp lệ / không đủ điểm DP / shipping không khả dụng |
| `422` | Thiếu field bắt buộc |

---

## 3. Đặt hàng – `POST /api/v1/orders`

> Giỏ hàng bị **xóa hoàn toàn** sau khi đặt hàng thành công.
> 

### Request — Trường hợp thông thường (giao đến địa chỉ của người đặt)

```json
{
  "customer_name": "Nguyễn Văn A",
  "customer_phone": "0912345678",
  "customer_email": "user@example.com",
  "customer_address": "Số 5, Ngõ 12, Đường Trần Phú",
  "customer_province_id": 1,
  "customer_district_id": 10,
  "customer_ward_id": 100,
  "is_shipdiff": false,
  "shipping_type": "deligo",
  "payment_method": "cod",
  "coupon_code": null,
  "vendor_coupon_codes": null,
  "shopping_points": null,
  "order_note": "Giao giờ hành chính"
}
```

### Request — Đầy đủ (coupon + vendor coupon + điểm DP)

```json
{
  "customer_name": "Nguyễn Văn A",
  "customer_phone": "0912345678",
  "customer_email": "user@example.com",
  "customer_address": "Số 5, Ngõ 12, Đường Trần Phú",
  "customer_province_id": 1,
  "customer_district_id": 10,
  "customer_ward_id": 100,
  "is_shipdiff": false,
  "shipping_type": "deligo",
  "payment_method": "cod",
  "coupon_code": "SALE10",
  "vendor_coupon_codes": {
    "5": "SHOP10",
    "8": "VND20"
  },
  "shopping_points": {
    "123": 100,
    "456": 50
  },
  "order_note": ""
}
```

### Request — Giao đến địa chỉ khác (`is_shipdiff: true`)

```json
{
  "customer_name": "Nguyễn Văn A",
  "customer_phone": "0912345678",
  "customer_email": "user@example.com",
  "customer_address": "Số 5, Ngõ 12, Đường Trần Phú",
  "customer_province_id": 1,
  "customer_district_id": 10,
  "customer_ward_id": 100,
  "is_shipdiff": true,
  "shipping_name": "Trần Thị B",
  "shipping_phone": "0987654321",
  "shipping_email": "b@example.com",
  "shipping_address": "456 Lê Lợi",
  "shipping_province_id": 2,
  "shipping_district_id": 20,
  "shipping_ward_id": 200,
  "shipping_type": "deligo",
  "payment_method": "cod",
  "coupon_code": null,
  "order_note": ""
}
```

### Bảng fields

| Field | Type | Bắt buộc | Ghi chú |
| --- | --- | --- | --- |
| `customer_name` | string (max 255) | **Có** | Tên người đặt |
| `customer_phone` | string (max 20) | **Có** | SĐT người đặt |
| `customer_email` | string email | **Có** | Email người đặt |
| `customer_address` | string (max 500) | **Có** | Số nhà + tên đường |
| `customer_province_id` | integer | **Có** | ID tỉnh |
| `customer_district_id` | integer | **Có** | ID quận |
| `customer_ward_id` | integer | **Có** | ID phường |
| `is_shipdiff` | boolean | Không | `false` = giao đến địa chỉ khách. `true` = giao đến địa chỉ riêng |
| `shipping_name` | string | Bắt buộc nếu `is_shipdiff: true` |  |
| `shipping_phone` | string | Bắt buộc nếu `is_shipdiff: true` |  |
| `shipping_email` | string email | Không | Nếu bỏ trống dùng `customer_email` |
| `shipping_address` | string | Bắt buộc nếu `is_shipdiff: true` |  |
| `shipping_province_id` | integer | Bắt buộc nếu `is_shipdiff: true` |  |
| `shipping_district_id` | integer | Bắt buộc nếu `is_shipdiff: true` |  |
| `shipping_ward_id` | integer | Bắt buộc nếu `is_shipdiff: true` |  |
| `shipping_type` | string | **Có** | `deligo` / `viettelpost` / `flat_rate` / `free` |
| `payment_method` | string | **Có** | `cod` hoặc `sepay` |
| `coupon_code` | string|null | Không | Platform coupon (toàn đơn). Xem [mobile-coupon-flow.md](mobile-coupon-flow.md) |
| `vendor_coupon_codes` | object|null | Không | **Map** `{"vendor_id": "CODE"}`. Key là `seller_id` (từ `GET /cart` → `sellers[].seller_id`). **1 mã per shop** — áp dụng cho toàn bộ items của shop đó. Xem [mobile-coupon-flow.md](mobile-coupon-flow.md) |
| `shopping_points` | object|null | Không | **Map** `{"cart_item_id": points}`. Key là ID cart item (string), value là số điểm DP dùng cho item đó. Không truyền = không dùng DP |
| `order_note` | string (max 1000) | Không | Ghi chú giao hàng |

> **Tip:** Lấy `customer_*` fields từ địa chỉ mặc định của user (`GET /addresses`) → prefill vào form checkout để giảm thao tác nhập.
> 

### Response thành công (HTTP 201) — COD

```json
{
  "success": true,
  "code": 1001,
  "data": {
    "order_number": "O2025011508301234AB",
    "status": "pending",
    "status_label": "Chờ xác nhận",
    "payment_status": "Pending",
    "payment_method": "cod",
    "payment": null,
    "shipping_type": "deligo",
    "amounts": {
      "products": 180000.0,
      "shipping_fee": 30000.0,
      "coupon_discount": 18000.0,
      "tax_amount": 0.0,
      "total": 192000.0
    },
    "customer": {
      "name": "Nguyễn Văn A",
      "phone": "0912345678",
      "email": "user@example.com",
      "address": "Số 5, Ngõ 12, Đường Trần Phú",
      "province_id": 1,
      "district_id": 10,
      "ward_id": 100
    },
    "shipping_address": null,
    "order_note": "Giao giờ hành chính",
    "coupon_code": null,
    "items": [
      {
        "product_id": 10,
        "product_name": "Sữa Tươi Vinamilk 1L",
        "thumbnail": "https://...",
        "qty": 2,
        "unit_price": 45000.0,
        "line_total": 90000.0
      }
    ],
    "tracks": [
      {
        "title": "Pending",
        "text": "Bạn đã đặt hàng thành công.",
        "created_at": "2025-01-15T08:30:00.000000Z"
      }
    ],
    "created_at": "2025-01-15T08:30:00.000000Z"
  }
}
```

#### Fields trong `amounts`

| Field | Type | Ghi chú |
| --- | --- | --- |
| `products` | float | Tổng giá trị hàng hoá (cash + SP quy đổi) |
| `shipping_fee` | float | Phí vận chuyển |
| `coupon_discount` | float | Giảm giá từ platform coupon + vendor coupon |
| `tax_amount` | float | Tổng tiền thuế VAT = tổng `(item_price × qty + price_sp) × tax_rate / 100` của các sản phẩm có `is_tax_inclusive = false` |
| `total` | float | Số tiền khách phải thanh toán (sau tất cả giảm giá và SP) |

### Response thành công (HTTP 201) — SePay

Khi `payment_method = "sepay"`, response trả thêm block `payment` chứa thông tin QR:

```json
{
  "success": true,
  "code": 1001,
  "data": {
    "order_number": "O2026060112345ABC",
    "status": "pending",
    "status_label": "Chờ xác nhận",
    "payment_status": "Pending",
    "payment_method": "sepay",
    "payment": {
      "method": "bank_transfer",
      "provider": "sepay",
      "status": "pending",
      "qr_code_url": "https://qr.sepay.vn/img?bank=MBBank&acc=0123456789&amount=192000&des=DELIPPY+O2026060112345ABC&template=compact",
      "qr_content": "DELIPPY O2026060112345ABC",
      "amount": 192000,
      "expired_at": "2026-06-01T11:00:00.000000Z"
    },
    "amounts": { ... },
    "items": [ ... ],
    "tracks": [ ... ],
    "created_at": "2026-06-01T10:00:00.000000Z"
  }
}
```

| Field trong `payment` | Type | Ghi chú |
| --- | --- | --- |
| `method` | string | Phương thức: `bank_transfer` |
| `provider` | string | Cổng thanh toán: `sepay` |
| `status` | string | `pending` / `paid` / `expired` / `failed` / `cancelled` |
| `qr_code_url` | string | URL ảnh QR — render trực tiếp vào `<Image>` |
| `qr_content` | string | Nội dung chuyển khoản — hiển thị cho user copy nếu cần |
| `amount` | integer | Số tiền cần chuyển (VND) |
| `expired_at` | datetime | Thời hạn QR (ISO 8601 UTC) — tính countdown cho user |

> **Lưu `order_number`** vào local state — cần để xem chi tiết, tracking và polling.
> 
> 
> `shipping_address` là `null` khi `is_shipdiff: false`.
> 
> `tracks` trả về ngay sau đặt hàng với bước đầu tiên “Pending”.
> 
> Khi `payment_method = "cod"`, `payment` luôn là `null`.
> 

### ❌ Lỗi

| HTTP | Code | Ý nghĩa |
| --- | --- | --- |
| `400` | `3001` | Giỏ hàng rỗng |
| `400` | `3001` | Mã coupon không hợp lệ / hết hạn / đã dùng hết |
| `400` | `3001` | Không đủ điểm DP — per item vượt giới hạn hoặc tổng vượt số dư ví |
| `400` | `3001` | Đơn vị vận chuyển không hỗ trợ địa chỉ này |
| `400` | `3001` | Sản phẩm trong giỏ hết hàng — thông báo chung “không đủ số lượng”, không nêu cụ thể tồn kho |
| `422` | — | Validation lỗi field |

---

## 4. Danh sách đơn hàng – `GET /api/v1/orders`

### Query params

| Param | Bắt buộc | Mô tả |
| --- | --- | --- |
| `status` | Không | Lọc theo trạng thái: `pending` / `processing` / `on delivery` / `completed` / `declined` |
| `per_page` | Không | Số item mỗi trang (mặc định `15`) |
| `page` | Không | Trang hiện tại (mặc định `1`) |

### Request

```
GET /api/v1/orders?status=pending&per_page=10&page=1
```

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": [
    {
      "order_number": "O2025011508301234AB",
      "status": "pending",
      "status_label": "Chờ xác nhận",
      "payment_status": "Pending",
      "total": 192000.0,
      "item_count": 3,
      "thumbnail": "https://...",
      "created_at": "2025-01-15T08:30:00.000000Z"
    }
  ],
  "meta": {
    "current_page": 1,
    "last_page": 3,
    "per_page": 15,
    "total": 42
  }
}
```

> `thumbnail` là ảnh của **sản phẩm đầu tiên** trong đơn — dùng để hiển thị đại diện đơn hàng trong list.
> 
> 
> `item_count` là số lượng **vendor orders** (số loại sản phẩm), không phải tổng qty.
> 
> Không lọc `status` → trả về tất cả đơn, sắp xếp mới nhất trước.
> 

### Pagination

Dùng `meta.current_page` và `meta.last_page` để render pagination hoặc infinite scroll.

```
meta.current_page < meta.last_page  →  còn trang tiếp theo
```

---

## 5. Chi tiết đơn hàng – `GET /api/v1/orders/{orderNumber}`

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": {
    "order_number": "O2025011508301234AB",
    "status": "processing",
    "status_label": "Đang xử lý",
    "payment_status": "Pending",
    "shipping_type": "deligo",
    "amounts": {
      "products": 180000.0,
      "shipping_fee": 30000.0,
      "coupon_discount": 18000.0,
      "tax_amount": 0.0,
      "total": 192000.0
    },
    "customer": {
      "name": "Nguyễn Văn A",
      "phone": "0912345678",
      "email": "user@example.com",
      "address": "Số 5, Ngõ 12, Đường Trần Phú",
      "province_id": 1,
      "district_id": 10,
      "ward_id": 100
    },
    "shipping_address": null,
    "order_note": "Giao giờ hành chính",
    "coupon_code": "GIAM10",
    "items": [
      {
        "product_id": 10,
        "product_name": "Sữa Tươi Vinamilk 1L",
        "thumbnail": "https://...",
        "qty": 2,
        "unit_price": 45000.0,
        "line_total": 90000.0,
        "size": null,
        "color": null,
        "custom_option_key": null,
        "custom_option_value": null,
        "has_reviewed": false
      }
    ],
    "tracks": [
      {
        "title": "Processing",
        "text": "Đơn hàng đang được xử lý.",
        "created_at": "2025-01-15T09:00:00.000000Z"
      },
      {
        "title": "Pending",
        "text": "Bạn đã đặt hàng thành công.",
        "created_at": "2025-01-15T08:30:00.000000Z"
      }
    ],
    "created_at": "2025-01-15T08:30:00.000000Z"
  }
}
```

### Fields trong `items[]`

| Field | Type | Ghi chú |
| --- | --- | --- |
| `product_id` | string | ID sản phẩm |
| `product_name` | string | Tên sản phẩm tại thời điểm đặt hàng |
| `thumbnail` | string|null | Ảnh đại diện |
| `qty` | integer | Số lượng |
| `unit_price` | float | Giá một đơn vị |
| `line_total` | float | `unit_price × qty` |
| `size` | string|null | Size đã chọn |
| `color` | string|null | Màu đã chọn |
| `custom_option_key` | array|null | Tên các tuỳ chọn thêm |
| `custom_option_value` | array|null | Giá trị tương ứng |
| `has_reviewed` | boolean | `true` = user đã đánh giá sản phẩm này. Dùng để hiện/ẩn nút “Đánh giá” |

> **Logic nút “Đánh giá”:** chỉ hiển thị khi `order.status = "completed"` **và** `item.has_reviewed = false`.
> 

> `tracks` là lịch sử trạng thái đơn hàng — render theo thứ tự **mới nhất trên đầu** (index 0 là mới nhất).
> 
> 
> Mỗi track có `title` (tên trạng thái) và `text` (mô tả chi tiết).
> 

### ❌ Lỗi

| HTTP | Ý nghĩa |
| --- | --- |
| `404` | Đơn hàng không tồn tại hoặc không thuộc về user |

---

## 6. Huỷ đơn hàng – `POST /api/v1/orders/{orderNumber}/cancel`

Không cần request body.

### Điều kiện huỷ

Chỉ huỷ được khi `status` là **`pending`** hoặc **`processing`**.

Sau khi `on delivery` → không thể huỷ.

### Response thành công (HTTP 200)

Trả về Order object đầy đủ với `status: "declined"` và track mới nhất “Cancelled”.

```json
{
  "success": true,
  "code": 1000,
  "data": {
    "order_number": "O2025011508301234AB",
    "status": "declined",
    "status_label": "Đã huỷ",
    "tracks": [
      {
        "title": "Cancelled",
        "text": "Đơn hàng đã được huỷ bởi người mua.",
        "created_at": "2025-01-15T09:15:00.000000Z"
      },
      {
        "title": "Pending",
        "text": "Bạn đã đặt hàng thành công.",
        "created_at": "2025-01-15T08:30:00.000000Z"
      }
    ],
    ...
  }
}
```

> Điểm Si đã dùng sẽ được **hoàn trả** vào tài khoản sau khi huỷ.
> 
> 
> Dùng response để cập nhật UI ngay — không cần gọi lại `GET /orders/{orderNumber}`.
> 

### ❌ Lỗi

| HTTP | Ý nghĩa |
| --- | --- |
| `400` | Đơn không thể huỷ vì đang ở trạng thái `on delivery` / `completed` / `declined` |
| `404` | Đơn hàng không tồn tại hoặc không thuộc về user |

---

## 7. Kiểm tra trạng thái thanh toán SePay – `GET /api/v1/orders/{orderNumber}/payment-status`

> Endpoint nhẹ dành riêng cho **polling SePay**. Gọi mỗi **4–5 giây** sau khi đặt đơn `sepay`.
> 
> 
> Dừng polling khi `payment_status` là `paid` hoặc `expired`.
> 

### Request

```
GET /api/v1/orders/O2026060112345ABC/payment-status
```

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": {
    "payment_status": "pending",
    "order_status": "pending",
    "amount": 192000,
    "expired_at": "2026-06-01T11:00:00.000000Z",
    "paid_at": null
  }
}
```

| Field | Type | Ghi chú |
| --- | --- | --- |
| `payment_status` | string | `pending` / `paid` / `expired` / `failed` / `cancelled` |
| `order_status` | string | Trạng thái đơn hàng hiện tại |
| `amount` | integer | Số tiền (VND) |
| `expired_at` | datetime|null | Thời hạn QR — null nếu không có |
| `paid_at` | datetime|null | Thời điểm thanh toán thành công — null nếu chưa thanh toán |

### Logic xử lý phía mobile

```
Vòng lặp polling (mỗi 4–5 giây):
├── payment_status = "pending"  → tiếp tục polling, cập nhật countdown
├── payment_status = "paid"     → dừng polling → navigate "Thanh toán thành công"
├── payment_status = "expired"  → dừng polling → hiện thông báo "QR hết hạn"
└── payment_status = "failed" / "cancelled" → dừng polling → hiện thông báo lỗi

Ngoài ra: countdown đến expired_at = 0 → dừng polling → hiện thông báo hết hạn
```

> **Thay thế polling bằng Firestore realtime** — khi app ở foreground, lắng nghe document `order_payments/{order_number}` thay vì polling. Phản hồi tức thì và tiết kiệm request. Xem [mobile-notification-flow.md](mobile-notification-flow.md).
> 
> 
> Polling endpoint này vẫn hữu dụng làm fallback nếu Firestore không khả dụng.
> 

### ❌ Lỗi

| HTTP | Ý nghĩa |
| --- | --- |
| `401` | Chưa đăng nhập |
| `404` | Đơn hàng không tồn tại hoặc không thuộc về user |

---

## Sơ đồ flow tổng quát

```
╔══════════════════════════════════════════════════════════════╗
║                    MÀN HÌNH CHECKOUT                         ║
╚══════════════════════════════════════════════════════════════╝

User ở màn hình giỏ hàng, nhấn "Thanh toán"
├── GET /addresses  →  load danh sách địa chỉ, pre-select default
├── User chọn shipping_type
└── (Tuỳ chọn) POST /orders/shipping-fee { shipping_type, province_id, district_id }
    └── Hiển thị phí ship ước tính trong tóm tắt đơn hàng

User xác nhận đặt hàng
└── POST /orders { ...checkout_form }
    ├── 201 payment_method=cod   → lưu order_number → navigate "Đặt hàng thành công"
    │                               → giỏ hàng đã bị xóa → reset cart state
    ├── 201 payment_method=sepay → lưu order_number + data.payment
    │                               → navigate màn hình QR thanh toán
    │                               → hiện QR (qr_code_url), số tiền, countdown (expired_at)
    │                               → bắt đầu Firestore listener (order_payments/{orderNumber})
    │                                   ├── paid     → navigate "Thanh toán thành công"
    │                                   ├── failed   → hiện "Số tiền không khớp, liên hệ CSKH"
    │                                   ├── expired  → hiện "QR hết hạn, vui lòng đặt lại"
    │                                   └── (fallback) polling GET /payment-status nếu Firestore không khả dụng
    ├── 400 code giỏ rỗng  → không nên xảy ra (disable nút nếu cart rỗng)
    ├── 400 code coupon     → hiển thị lỗi tại field coupon
    ├── 400 code ship       → hiển thị lỗi chọn lại shipping method
    └── 422                 → hiển thị lỗi từng field

╔══════════════════════════════════════════════════════════════╗
║                   MÀN HÌNH DANH SÁCH ĐƠN                     ║
╚══════════════════════════════════════════════════════════════╝

Mở màn hình "Đơn hàng của tôi"
└── GET /orders?per_page=15  →  render danh sách

Tab lọc theo trạng thái (Tất cả / Chờ xác nhận / Đang xử lý / ...)
└── GET /orders?status=pending&per_page=15

Infinite scroll / Load more
└── GET /orders?status=...&per_page=15&page=2

User nhấn vào một đơn
└── GET /orders/{orderNumber}  →  navigate màn hình chi tiết

╔══════════════════════════════════════════════════════════════╗
║                  MÀN HÌNH CHI TIẾT ĐƠN                       ║
╚══════════════════════════════════════════════════════════════╝

Render Order detail
├── Hiển thị items, amounts, tracking timeline
├── status = pending/processing → hiện nút "Huỷ đơn"
└── status = on delivery/completed/declined → ẩn nút "Huỷ đơn"

User nhấn "Huỷ đơn"
└── Hiện dialog xác nhận
    └── User xác nhận → POST /orders/{orderNumber}/cancel
        ├── 200 → cập nhật UI từ response (status = declined, track mới)
        └── 400 → hiển thị thông báo "Đơn hàng không thể huỷ"
```

---

## Lưu ý quan trọng

| # | Ghi chú |
| --- | --- |
| 1 | **Giỏ hàng bị xóa** ngay khi đặt hàng thành công — reset `cart state` trong app |
| 2 | `order_number` là định danh chính (không phải `id`) — lưu vào state và dùng cho mọi thao tác tiếp theo |
| 3 | Nên **pre-fill** form checkout từ địa chỉ mặc định của user để giảm bước nhập tay |
| 4 | `POST /orders/shipping-fee` là optional — có thể bỏ qua nếu muốn đơn giản hoá checkout |
| 5 | Tab lọc trạng thái: dùng `status` value (không dùng `status_label`) làm query param |
| 6 | `tracks` trong detail hiển thị **mới nhất trước** (index 0 là track mới nhất) |
| 7 | Sau khi huỷ đơn, điểm DP đã dùng được **hoàn trả tự động** — không cần xử lý thêm |
| 8 | `shopping_points` là **object map** `{"cart_item_id": points}` — per item, không phải boolean. Điểm mỗi item không được vượt `price_shopping_point` của item đó (lấy từ `GET /cart`). Tổng không được vượt số dư ví DP |
| 9 | SePay: **polling mỗi 4–5 giây**, dừng khi `payment_status = paid` hoặc `expired` |
| 10 | SePay: QR có thời hạn (`expired_at`) — hiển thị countdown cho user biết còn bao lâu |
| 11 | SePay: `payment` block là `null` với COD — luôn kiểm tra trước khi đọc |
| 12 | SePay: `payment_status` trong order root là capitalize (`"Pending"`); trong block `payment` và endpoint polling là lowercase (`"pending"`) |
| 13 | SePay: dùng **Firestore realtime listener** (`order_payments/{order_number}`) thay cho polling khi app ở foreground — xem [mobile-notification-flow.md](mobile-notification-flow.md) |
| 14 | SePay: khi amount không khớp, backend gửi FCM `payment_status = "failed"` và cập nhật Firestore — mobile nhận được ngay, không phải chờ polling |
| 15 | `items[].has_reviewed` — hiện nút “Đánh giá” chỉ khi `status = "completed"` **và** `has_reviewed = false` |

---

## Changelog

| Ngày | Phiên bản | Thay đổi |
| --- | --- | --- |
| — | v1.0 | Khởi tạo: shipping-fee, place order (COD), list, detail, cancel |
| 2026-06-05 | v1.1 | Thêm `payment_method = sepay`: block `payment` trong response đặt hàng, endpoint polling `GET /orders/{orderNumber}/payment-status`, bảng `payment_status`, sơ đồ flow QR, lưu ý SePay (#9–12) |
| 2026-06-11 | v1.2 | Bổ sung Firestore realtime thay thế polling, case `payment_status = "failed"` (amount mismatch), lưu ý #13–14, link đến `mobile-notification-flow.md` |
| 2026-06-14 | v1.3 | Làm rõ `use_shopping_point` là boolean all-or-nothing (khác web); thêm lỗi out-of-stock (không lộ số lượng tồn kho cụ thể) vào bảng ❌ Lỗi |
| 2026-06-14 | v1.4 | Thêm mục 0.1 `GET /shipping-methods` và 0.2 `GET /payment-methods` (public, không cần auth); deprecated `/user/paymentgateway`; cập nhật bảng shipping/payment để dùng `key` động từ API |
| 2026-06-16 | v1.5 | Thêm `has_reviewed` vào `items[]` trong chi tiết đơn hàng; bổ sung bảng mô tả field `items[]`; thêm lưu ý #15 về logic nút đánh giá |
| 2026-06-19 | v1.6 | Đổi `use_shopping_point: boolean` → `shopping_points: object` (per-item map). Đổi `vendor_coupon_codes: string[]` → `vendor_coupon_codes: object` (cart_item_id → code map). Thêm request example đầy đủ. Cập nhật bảng fields và lưu ý #8 |
| 2026-06-19 | v1.7 | Giữ key `cart_item_id` cho `vendor_coupon_codes` — mỗi item có thể dùng code riêng, kể cả 2 item cùng vendor. Cập nhật bảng fields và request example |
| 2026-06-19 | v1.8 | Thêm `tax_rate` và `tax_amount` vào block `amounts` trong response đặt hàng và chi tiết đơn; thêm bảng fields `amounts`; cập nhật lỗi 400 điểm DP cho đúng format mới |
| 2026-06-20 | v2.0 | **Breaking change:** `vendor_coupon_codes` đổi key từ `cart_item_id` → `vendor_id` (1 code per shop). Cập nhật request examples, bảng fields, OpenAPI annotation |
| 2026-06-19 | v1.9 | Thêm mục 2 `POST /orders/preview` — preview tổng đơn hàng trước khi đặt (validate coupon, DP, tính shipping); response trả về `amounts` breakdown gồm `vendor_discount`, `sp_amount` riêng biệt; renumber mục 2→3, 3→4, 4→5, 5→6, 6→7 |
| 2026-06-20 | v2.1 | Làm rõ flow 2 màn hình giống Shopee: cart screen tính local → nhấn “Mua hàng” gọi `POST /orders/preview` **1 lần** (đã bao gồm shipping) → checkout screen. Không gọi `POST /orders/shipping-fee` riêng. Debounce 500ms khi thay đổi địa chỉ/shipping trên checkout |
| 2026-06-22 | v2.2 | `tax_rate` đổi type `float` → `integer` (API trả int thay vì `0.0`). Bổ sung formula `tax_amount = products × tax_rate / 100` vào bảng fields. |
| 2026-06-26 | v2.3 | Cập nhật mô tả `tax_amount` trong `amounts`: giờ là tổng thuế per-product (`unit_price × qty × tax_rate / 100` cho các sản phẩm có `is_tax_inclusive = false`). `tax_rate` tại order-level luôn `0` — không còn là global rate. Xem `is_tax_inclusive` và `tax_rate` trong cart item / product detail để biết thuế từng sản phẩm. |
| 2026-06-28 | v2.4 | **Xoá field `tax_rate`** khỏi `amounts` (không còn trong response). `tax_amount` giờ trả đúng tổng tiền thuế VND. Cập nhật tất cả response examples và bảng fields. |