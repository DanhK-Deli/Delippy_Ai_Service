# mobile-coupon-flow

# Coupon Flow – Mobile Implementation Guide

> **Yêu cầu Bearer token** cho tất cả endpoint.
> 
> 
> Header: `Authorization: Bearer {access_token}`
> 
> Base: `/api/v1/coupons`
> 

---

## Tổng quan — 2 loại coupon

| Loại | Model | Ai tạo | Phạm vi | API key |
| --- | --- | --- | --- | --- |
| **Platform coupon** | `Coupon` | Admin | Toàn đơn hàng | `coupon_code` (string) |
| **Vendor coupon** | `CouponVendor` | Vendor / Admin | Từng shop — **1 mã per shop**, áp dụng cho tất cả items của shop đó | `vendor_coupon_codes` (object map `vendor_id → code`) |

---

## Flow tổng quát

```
╔═══════════════════════════════════════════════════╗
║   VENDOR COUPON (per shop — vendor_id → code)     ║
╚═══════════════════════════════════════════════════╝

Mở màn hình checkout
└── (lazy) GET /coupons/available
    └── Danh sách coupon nhóm theo vendor đang có hàng trong giỏ
        └── Mỗi shop chọn 1 mã chung (áp dụng cho toàn bộ items của shop đó)
            └── POST /coupons/validate { coupon_code, order_amount, vendor_id }  ← optional preview
                └── POST /orders { vendor_coupon_codes: { "5": "SHOP10", "8": "VND20" } }

╔══════════════════════════════════════╗
║   PLATFORM COUPON (toàn đơn)         ║
╚══════════════════════════════════════╝

User nhập mã tay ở ô "Mã giảm giá"
└── POST /coupons/validate { coupon_code, order_amount }  ← optional preview
    └── POST /orders { coupon_code: "SALE10" }
```

> **Quan trọng:** Validate chỉ là **preview** — không giữ chỗ, không trừ lượt dùng.
> 
> 
> Lượt dùng chỉ bị trừ khi đặt hàng thành công (`POST /orders`).
> 

---

## 1. Danh sách vendor coupon – `GET /api/v1/coupons/available`

> Trả về vendor coupon hợp lệ, **chỉ của những vendor đang có sản phẩm trong giỏ** của user.
> 
> 
> Dùng để populate coupon picker per vendor trước checkout.
> 
> Platform coupon không trả ở đây — user nhập tay và validate riêng.
> 

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": [
    {
      "vendor_id": 5,
      "vendor_name": "Shop Thời Trang ABC",
      "coupons": [
        {
          "code": "SHOP10",
          "discount_type": "percentage",
          "discount_value": 10,
          "end_date": "2026-12-31",
          "times_remaining": 20
        },
        {
          "code": "GIAM50K",
          "discount_type": "fixed",
          "discount_value": 50000,
          "end_date": "2026-07-01",
          "times_remaining": null
        }
      ]
    },
    {
      "vendor_id": 8,
      "vendor_name": "Shop Đồ Gia Dụng XYZ",
      "coupons": [
        {
          "code": "VND20",
          "discount_type": "fixed",
          "discount_value": 20000,
          "end_date": "2026-08-31",
          "times_remaining": 5
        }
      ]
    }
  ]
}
```

> `data: []` — giỏ trống hoặc không vendor nào có coupon đang active.
> 

### Fields

| Field | Type | Ghi chú |
| --- | --- | --- |
| `vendor_id` | integer | ID của vendor |
| `vendor_name` | string | Tên shop hiển thị |
| `coupons[].code` | string | Mã coupon |
| `coupons[].discount_type` | string | `percentage` = giảm %, `fixed` = giảm số tiền cố định |
| `coupons[].discount_value` | number | Nếu `percentage`: giá trị % (VD: `10` = giảm 10%). Nếu `fixed`: số tiền VND |
| `coupons[].end_date` | string | Ngày hết hạn `yyyy-MM-dd` |
| `coupons[].times_remaining` | integer|null | Lượt còn lại. `null` = không giới hạn |

### Hiển thị trên UI

```
discount_type = "percentage"  →  "Giảm 10%"
discount_type = "fixed"       →  "Giảm 50.000đ"
end_date != null              →  "HSD: 31/12/2026"
times_remaining != null && <= 10  →  "Còn X lượt" (highlight urgency)
```

### Khi nào gọi

```
User mở coupon picker của vendor X
└── Kiểm tra cache (< 5 phút)
    ├── Cache hợp lệ  →  render từ cache, không gọi API
    └── Hết hạn       →  gọi GET /coupons/available → cache lại
```

> Gọi 1 lần duy nhất cho toàn bộ giỏ (tất cả vendor). Không gọi per vendor.
> 

---

## 2. Validate mã giảm giá – `POST /api/v1/coupons/validate`

> Dùng để xem trước số tiền giảm. Áp dụng cho cả vendor coupon lẫn platform coupon.
> 
> 
> Không bắt buộc — nhưng khuyến nghị để hiển thị preview discount trước khi đặt.
> 

### Request

```json
{
  "coupon_code": "SHOP10",
  "order_amount": 250000,
  "vendor_id": 5
}
```

| Field | Type | Bắt buộc | Ghi chú |
| --- | --- | --- | --- |
| `coupon_code` | string | **Có** | Mã giảm giá |
| `order_amount` | number | **Có** | Tổng tiền hàng của vendor đó (vendor coupon) hoặc toàn đơn (platform coupon) |
| `vendor_id` | integer | Không | Truyền khi validate vendor coupon. Bỏ trống khi validate platform coupon |

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "message": "Mã giảm giá hợp lệ",
  "data": {
    "valid": true,
    "coupon_code": "SHOP10",
    "discount_type": "percentage",
    "discount_value": 10.0,
    "discount_amount": 25000.0,
    "final_amount": 225000.0
  }
}
```

### ❌ Lỗi (HTTP 422)

```json
{
  "success": false,
  "code": 3001,
  "message": "Mã giảm giá đã hết hạn"
}
```

| `message` | Nguyên nhân |
| --- | --- |
| Không tìm thấy mã giảm giá | Code không tồn tại hoặc vendor không khớp |
| Mã giảm giá chưa được kích hoạt | Vendor chưa bật coupon |
| Mã giảm giá chưa có hiệu lực | Chưa đến `start_date` |
| Mã giảm giá đã hết hạn | Quá `end_date` |
| Mã giảm giá đã hết lượt sử dụng | `times_remaining = 0` |
| Giá trị đơn hàng chưa đạt yêu cầu tối thiểu | Dưới `minimum_amount` (platform coupon) |

---

## 3. Áp dụng tại checkout – `POST /api/v1/orders`

### Vendor coupon — `vendor_coupon_codes`

Format: **object** với key là `vendor_id` (string), value là mã coupon. **Một mã cho toàn bộ sản phẩm của shop đó.**

```json
{
  "vendor_coupon_codes": {
    "5": "SHOP10",
    "8": "VND20"
  }
}
```

> Shop 5 dùng mã `SHOP10` — áp dụng cho **tất cả items** của shop 5 trong giỏ.
> 
> 
> Shop 8 dùng mã `VND20` — áp dụng cho **tất cả items** của shop 8.
> 
> Shops không có coupon → không truyền key.
> 
> `vendor_id` lấy từ `GET /cart` → `sellers[].seller_id`.
> 

**Logic tính discount:**

```
vendor_id 5 → mã SHOP10 (giảm 10%)
  - Item 123 (shop 5): 90.000đ
  - Item 456 (shop 5): 60.000đ
  → Tổng shop 5: 150.000đ → giảm 15.000đ
  → Item 123 chịu: 15.000 × (90/150) = 9.000đ
  → Item 456 chịu: 15.000 × (60/150) = 6.000đ
  → used của SHOP10: +1
```

> Discount chia tỉ lệ theo amount từng item để ghi vào VendorOrder.
> 
> 
> Nếu mã là fixed (giảm 50k) → giảm đúng 50k cho toàn shop, không nhân theo số item.
> 

### Platform coupon — `coupon_code`

```json
{
  "coupon_code": "SALE10"
}
```

> Áp dụng cho toàn đơn hàng, không phân biệt vendor.
> 

### Dùng cả 2 cùng lúc

```json
{
  "coupon_code": "SALE10",
  "vendor_coupon_codes": {
    "5": "SHOP10",
    "8": "VND20"
  }
}
```

### Lỗi coupon tại bước đặt hàng (HTTP 400)

```json
{
  "success": false,
  "code": 3001,
  "message": "Mã coupon không hợp lệ / hết hạn / đã dùng hết"
}
```

> → Hiển thị lỗi tại section coupon, cho phép user xoá mã và đặt lại.
> 
> 
> Race condition: validate OK nhưng đặt hàng báo lỗi (coupon hết lượt giữa chừng) — xử lý giống trường hợp này.
> 

---

## 4. Điểm DP (Shopping Points) – `shopping_points`

> Thay cho `use_shopping_point: boolean` — giờ hỗ trợ per-item, khớp với luồng web.
> 

Format: **object** với key là `cart_item_id` (string), value là số điểm dùng cho item đó.

```json
{
  "shopping_points": {
    "123": 500,
    "456": 50
  }
}
```

> Item 123 dùng 500 điểm (có thể ít hơn max — partial OK), item 456 dùng 50 điểm.
> 
> 
> Items không truyền key → không dùng điểm.
> 
> Để trống hoặc không truyền `shopping_points` → toàn bộ phần DP trả bằng tiền mặt.
> 

**Điều kiện validate (server kiểm tra):**
- Điểm dùng cho từng item ≤ `price_shopping_point` của item đó (= `unit_price_sp × qty`)
- Tổng điểm dùng ≤ số dư ví DP của user (`shopping_point` từ `GET /profile`)

**Partial DP được hỗ trợ:** Nếu item cần 1000 DP mà user chỉ dùng 500 DP, phần 500 DP còn lại được quy đổi thành tiền mặt (`500 × sp_vnd_exchange_rate` VNĐ) và cộng vào `total`.

### Dữ liệu cần để build UI DP

| Dữ liệu | Lấy từ | Field |
| --- | --- | --- |
| Max điểm per item | `GET /cart` → items | `price_shopping_point` |
| Đơn giá điểm per unit | `GET /cart` → items | `unit_price_sp` |
| Tỷ giá (1 DP = X VNĐ) | `GET /cart` → summary | `sp_vnd_exchange_rate` |
| Tổng DP nếu dùng 100% | `GET /cart` → summary | `total_sp_required` |
| Số dư DP của user | `GET /profile` | `shopping_point` |
| Preview tổng khi chọn DP | `POST /orders/preview` | `data.amounts.sp_amount`, `data.amounts.total` |

**Tính toán trên client (không cần API):**

```
// Giá trị VNĐ tiết kiệm khi user chọn X điểm cho item:
vnd_saved = X × sp_vnd_exchange_rate

// Tiền mặt trả thêm cho phần DP còn lại:
dp_cash = (price_shopping_point - X) × sp_vnd_exchange_rate

// Kiểm tra đủ điểm:
enough = user.shopping_point >= sum(all chosen points)
```

---

## Flow khuyến nghị – Tối ưu UX

> Flow gồm **2 màn hình riêng** (giống Shopee):
- **Cart screen** — chọn coupon, điều chỉnh DP, xem tổng ước tính (tính local, chưa có shipping)
- **Checkout screen** — xác nhận địa chỉ, shipping, payment → nhấn “Đặt hàng”
> 
> 
> `POST /orders/preview` đã bao gồm tính shipping fee bên trong — **không cần gọi thêm `POST /orders/shipping-fee`**.
> 
> Gọi preview **1 lần khi chuyển màn hình**, debounce 500ms nếu user thay đổi địa chỉ/shipping trên checkout.
> 

### Chiến lược: tính local vs gọi API

| Màn hình | Thay đổi | Cách xử lý | Lý do |
| --- | --- | --- | --- |
| Cart | User chọn vendor coupon | `POST /coupons/validate` 1 lần | Lấy `discount_amount` → cache vào state |
| Cart | User nhập platform coupon | `POST /coupons/validate` 1 lần khi nhấn “Áp dụng” | Validate + lấy `discount_amount` |
| Cart | User kéo DP slider | **Tính local** ngay | `sp_amount = points × sp_vnd_exchange_rate` |
| Cart | Hiển thị tổng ước tính | **Tính local** | `products - platformDiscount - vendorDiscount - spAmount` (chưa có shipping) |
| Cart → Checkout | User nhấn “Mua hàng” | `POST /orders/preview` **1 lần** | Trả về `shipping_fee` + full breakdown — không cần gọi thêm shipping-fee |
| Checkout | User thay đổi địa chỉ / shipping | `POST /orders/preview` lại (debounce 500ms) | Recalculate toàn bộ bao gồm phí ship mới |
| Checkout | User nhấn “Đặt hàng” | `POST /orders` | Server validate — handle 400 inline |

### Sơ đồ toàn bộ flow

```
[CART SCREEN]
├── GET /cart            → products, sp_vnd_exchange_rate, total_sp_required
├── GET /profile         → user.shopping_point (số dư DP)
├── GET /coupons/available → cache 5 phút (vendor coupon picker)
│
├── [Per shop] User chọn mã coupon shop
│   └── POST /coupons/validate { coupon_code, vendor_id, order_amount }
│       ├── valid   → vendorDiscountMap[vendor_id] = discount_amount
│       └── invalid → hiện lỗi inline
│
├── [Platform coupon] User nhập + nhấn "Áp dụng"
│   └── POST /coupons/validate { coupon_code, order_amount }
│       ├── valid   → platformDiscountAmount = discount_amount
│       └── invalid → hiện lỗi inline
│
├── [DP] User kéo slider → tính LOCAL ngay:
│   └── spAmount = Σ(points × sp_vnd_exchange_rate)
│
├── [Tổng ước tính] Tính LOCAL (hiển thị "Chưa tính phí ship"):
│   subtotal ≈ products - platformDiscountAmount - Σ(vendorDiscountMap) - spAmount
│
└── User nhấn "Mua hàng"
    └── POST /orders/preview { shipping_type, province_id, district_id,
                               coupon_code, vendor_coupon_codes, shopping_points }
        └── Navigate sang Checkout screen với breakdown đầy đủ từ response

[CHECKOUT SCREEN]
├── Hiển thị breakdown từ preview:
│   products / shipping_fee / coupon_discount / vendor_discount / sp_amount / total
│
├── User thay đổi địa chỉ hoặc shipping_type
│   └── (debounce 500ms) POST /orders/preview lại → cập nhật breakdown
│
└── User nhấn "Đặt hàng"
    └── POST /orders { ...toàn bộ state... }
        ├── 201 → clear state → navigate success
        ├── 400 coupon → xoá coupon → hiện lỗi inline → cho đặt lại không dùng mã
        └── 400 SP     → reset shoppingPointMap → hiện lỗi inline
```

---

### State management đề xuất

```dart
class CouponCheckoutState {
  // Platform coupon
  String?  platformCouponCode;
  double?  platformDiscountAmount;
  String?  platformCouponError;

  // Vendor coupons: vendor_id → coupon code (1 code per shop)
  Map<String, String> vendorCouponMap = {};
  // Validated discount per vendor: vendor_id → discount amount
  Map<String, double> vendorDiscountMap = {};

  // Shopping points per item: cart_item_id → points
  Map<String, double> shoppingPointMap = {};

  // DP info (từ GET /cart summary)
  double spVndExchangeRate = 1.0;   // 1 điểm = X VNĐ
  double totalSpRequired   = 0.0;   // tổng điểm nếu dùng 100% DP
  // Số dư user (từ GET /profile)
  double userSpBalance     = 0.0;

  // Shipping (từ POST /orders/shipping-fee — gọi 1 lần, cache lại)
  double? cachedShippingFee;
  String? cachedShippingType;
  int?    cachedProvinceId;
  int?    cachedDistrictId;

  // Helpers tính real-time trên client (không cần API)
  double get spAmount =>
      shoppingPointMap.values.fold(0.0, (a, b) => a + b) * spVndExchangeRate;

  double get vendorDiscount =>
      vendorDiscountMap.values.fold(0.0, (a, b) => a + b);

  double localTotal(double products) =>
      products
      + (cachedShippingFee ?? 0)
      - (platformDiscountAmount ?? 0)
      - vendorDiscount
      - spAmount;

  bool get hasEnoughSp =>
      userSpBalance >= shoppingPointMap.values.fold(0.0, (a, b) => a + b);

  // Preview tổng chính xác từ server (gọi 1 lần ở màn hình xác nhận)
  double? previewTotal;
  double? previewSpAmount;
  double? previewCouponDiscount;
  double? previewVendorDiscount;

  // Cache coupon picker (lazy, 5 phút)
  List<VendorCouponGroup>? cachedCoupons;
  DateTime?                couponCachedAt;
  bool get isCouponCacheValid =>
      couponCachedAt != null &&
      DateTime.now().difference(couponCachedAt!).inMinutes < 5;
}
```

---

### Khi nào gọi từng API

| Tình huống | API | Tần suất | Ghi chú |
| --- | --- | --- | --- |
| Vào màn hình checkout | `GET /cart` | 1 lần | Lấy `sp_vnd_exchange_rate`, `total_sp_required`, `price_shopping_point` per item |
| Lấy số dư DP | `GET /profile` | 1 lần | Field `shopping_point` |
| User chọn địa chỉ / shipping type | `POST /orders/shipping-fee` | Khi thay đổi | Lưu vào `cachedShippingFee`, tái dùng cho tính local |
| User mở coupon picker | `GET /coupons/available` | Khi cache hết hạn | Cache 5 phút — render từ cache nếu còn hiệu lực |
| User chọn vendor coupon | `POST /coupons/validate` | 1 lần per lựa chọn | Lưu `discount_amount` vào `vendorDiscountMap[vendor_id]` |
| User nhập platform coupon + nhấn “Áp dụng” | `POST /coupons/validate` | 1 lần per code | Validate và lưu `platformDiscountAmount` |
| Hiển thị tổng trên cart | **Tính local** (không gọi API) | Mỗi thay đổi state | `products - platformDiscount - vendorDiscount - spAmount` (shipping hiện “chưa tính”) |
| User điều chỉnh DP | **Tính local** (không gọi API) | Mỗi lần kéo slider | `spAmount = Σ(points) × sp_vnd_exchange_rate` |
| User thay đổi cart (thêm/xoá item) | Clear cache + clear coupon state | Khi cart thay đổi | Vendor list có thể thay đổi |
| **User nhấn “Mua hàng”** | `POST /orders/preview` **1 lần** | Khi chuyển màn hình | Preview đã tính shipping bên trong — không cần gọi thêm shipping-fee |
| User thay đổi địa chỉ/shipping trên checkout | `POST /orders/preview` lại (debounce 500ms) | Khi thay đổi | Recalculate toàn bộ kể cả phí ship |
| User nhấn “Đặt hàng” | `POST /orders` | 1 lần | Server validate — handle 400 inline |

---

### Trường hợp đặc biệt

**User thay đổi giỏ sau khi đã chọn coupon:**

```
User xoá item của shop 5 khỏi giỏ
→ vendorCouponMap["5"] vẫn còn trong state
→ Server bỏ qua coupon của vendor không còn item trong giỏ — an toàn
→ Nên clear vendorCouponMap[vendor_id] khi xoá hết items của shop đó
```

**User nhập mã vendor coupon tay thay vì chọn từ danh sách:**

```
→ Dùng POST /coupons/validate { coupon_code, order_amount, vendor_id } để preview
→ Lưu code vào vendorCouponMap[vendor_id]
```

**Race condition (validate OK nhưng đặt hàng lỗi):**

```
→ Server trả 400 "Mã coupon không hợp lệ"
→ Xoá coupon state → hiển thị lỗi
→ Cho phép user đặt lại không dùng mã (không block)
```

---

## Sự khác biệt giữa validate API và order API

| Điểm khác | `POST /coupons/validate` | `POST /orders` |
| --- | --- | --- |
| Cơ sở tính discount | `order_amount` client truyền vào | Tính từ cart items thực tế trên server |
| Vendor coupon không truyền `vendor_id` | Trả lỗi | Server tự mapping theo `vendor_id` của cart item |
| Kết quả discount | Preview — có thể lệch nhỏ | Chính xác — dùng `amounts.coupon_discount` từ response |

> Luôn dùng `amounts.coupon_discount` và `amounts.vendor_discount` từ response `POST /orders` để hiển thị số tiền giảm chính xác, không dùng kết quả từ validate.
> 

---

## Lưu ý quan trọng

| # | Ghi chú |
| --- | --- |
| 1 | Validate chỉ là preview — không ảnh hưởng `times_remaining` |
| 2 | `vendor_coupon_codes` là object (map) keyed by **vendor_id** — `{"5": "SHOP10", "8": "VND20"}`. **Một mã per shop** — áp dụng cho toàn bộ sản phẩm của shop đó trong giỏ |
| 3 | `shopping_points` là object (map) keyed by **cart_item_id** — `{"123": points}` |
| 4 | `cart_item_id` lấy từ `GET /cart`, field `id` của mỗi item |
| 5 | Một shop chỉ dùng được 1 mã — server áp dụng code đó cho toàn bộ items của shop, tính discount 1 lần trên tổng, chia proportional per item |
| 6 | `times_remaining` trong danh sách có thể stale do cache — không dùng để block nhập mã |
| 7 | Khi cart thay đổi (thêm/xoá item) → clear cache `GET /coupons/available` |
| 8 | Ô nhập mã nên `trim()` và `toUpperCase()` trước khi gọi API |
| 9 | Platform coupon: truyền `coupon_code`. Vendor coupon: truyền `vendor_coupon_codes`. Có thể dùng cả 2 cùng lúc |
| 10 | Điểm DP per item: không được vượt quá `price_shopping_point` của item đó (lấy từ `GET /cart`) |
| 11 | `unit_price_sp = 0` → item không hỗ trợ DP — ẩn UI điểm, không truyền key đó vào `shopping_points` |
| 12 | Partial DP được hỗ trợ — item cần 1000 DP, user chỉ dùng 500 DP → 500 DP còn lại = 500 VNĐ tiền mặt |
| 13 | `sp_vnd_exchange_rate` từ `GET /cart` summary — dùng để convert điểm ↔︎ VNĐ trên UI, không cần gọi thêm API |
| 14 | `POST /orders/preview` trả về `amounts.sp_amount` (VNĐ tiết kiệm từ DP), `amounts.total` — dùng để hiển thị tổng chính xác trước khi đặt |
| 15 | Luôn dùng `amounts` từ response `POST /orders` / `POST /orders/preview` cho giá trị chính xác — không tính thủ công khi đã có response |

---

## Changelog

| Ngày | Phiên bản | Thay đổi |
| --- | --- | --- |
| 2026-06-13 | v1.0 | Khởi tạo |
| 2026-06-13 | v1.1 | Thêm bảng so sánh validate vs order API |
| 2026-06-19 | v2.0 | **Viết lại hoàn toàn.** Phân tách rõ 2 loại coupon (vendor vs platform). Thêm `GET /coupons/available`. Đổi sang object map. Đổi `use_shopping_point` sang `shopping_points` per-item. Thêm flow diagram, state management, edge cases |
| 2026-06-19 | v2.1 | Fix logic tính discount theo pair `(vendor_id, code)`. Dedup coupon increment theo coupon ID |
| 2026-06-19 | v2.2 | Thêm mục DP — bảng nguồn dữ liệu, partial DP, tính client-side. Thêm `sp_vnd_exchange_rate` + `total_sp_required` vào state. Lưu ý 11-15 về DP |
| 2026-06-20 | v2.3 | Fix inconsistency về per item vs per vendor trong docs |
| 2026-06-20 | v2.4 | **Breaking change:** `vendor_coupon_codes` đổi key từ `cart_item_id` → `vendor_id` (1 mã per shop). Fix `computeVendorCouponsDiscount`. Cập nhật toàn bộ examples, flow diagram, state management |
| 2026-06-20 | v2.5 | **Cập nhật checkout flow:** Thêm bảng “tính local vs gọi API”. Sơ đồ flow mới với `cachedShippingFee`. Thêm `localTotal()` helper. Cập nhật bảng “khi nào gọi từng API” |
| 2026-06-20 | v2.6 | Làm rõ flow 2 màn hình giống Shopee: cart screen tính local → nhấn “Mua hàng” gọi `POST /orders/preview` **1 lần** (đã bao gồm shipping) → checkout screen. Bỏ `POST /orders/shipping-fee` khỏi flow — gọi riêng là thừa. Debounce 500ms khi thay đổi địa chỉ/shipping |