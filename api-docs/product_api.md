# mobile-product-flow

# Product Flow – Mobile Implementation Guide

> **Public** — không cần authentication.
> 
> 
> Base: `/api/v1/`
> 

---

## Cấu trúc dùng chung

### ProductCard (dùng ở list / search)

```json
{
  "id": 10,
  "name": "Sữa Tươi Vinamilk 1L",
  "slug": "sua-tuoi-vinamilk-1l",
  "thumbnail": "https://...",
  "price": 35000,
  "original_price": 40000,
  "discount_percent": 13,
  "badges": ["sale"],
  "rating": 4.5,
  "ratings_count": 120,
  "sold_count": 320,
  "point": 500
}
```

### Cursor pagination meta (dùng cho `GET /products`)

```json
{
  "next_cursor": "eyJzb3J0IjoibmV3ZXN0IiwidmFsIjoiMjAyNi0wNi0yMSAxMDowMDowMCIsImlkIjo0MH0=",
  "has_more": true
}
```

> Tải thêm: truyền `meta.next_cursor` vào param `cursor`. Dừng khi `meta.has_more = false`.
> 

### Offset pagination meta (dùng cho `GET /products/search`)

```json
{
  "current_page": 1,
  "per_page": 15,
  "total": 120,
  "last_page": 8
}
```

> Tải thêm: tăng `page`. Dừng khi `current_page >= last_page`.
> 

---

## 1. Danh sách sản phẩm – `GET /api/v1/products`

Sử dụng **cursor pagination** — phù hợp với infinite scroll trên mobile.

### Query params

| Param | Type | Bắt buộc | Mặc định | Ghi chú |
| --- | --- | --- | --- | --- |
| `category_id` | integer | Không |  | Lọc theo category (cấp 1) |
| `subcategory_id` | integer | Không |  | Lọc theo subcategory (cấp 2) |
| `childcategory_id` | integer | Không |  | Lọc theo child category (cấp 3) |
| `sort` | string | Không | `newest` | Xem bảng sort bên dưới |
| `price_min` | integer | Không |  | Giá tối thiểu (VND) |
| `price_max` | integer | Không |  | Giá tối đa (VND) |
| `cursor` | string | Không |  | Giá trị `meta.next_cursor` từ response trước. Bỏ trống = trang đầu |

> Khi đổi `sort` hoặc bất kỳ filter nào → bỏ `cursor`, reset list về đầu.
> 

### Các giá trị `sort`

| Giá trị | Ý nghĩa |
| --- | --- |
| `newest` | Mới nhất (mặc định) |
| `price_asc` | Giá tăng dần |
| `price_desc` | Giá giảm dần |
| `popular` | Phổ biến nhất |
| `rating` | Đánh giá cao nhất |

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": [ /* mảng ProductCard */ ],
  "meta": {
    "next_cursor": "eyJzb3J0IjoibmV3ZXN0IiwidmFsIjoiMjAyNi0wNi0yMSAxMDowMDowMCIsImlkIjo0MH0=",
    "has_more": true
  }
}
```

> Khi hết data: `meta.has_more = false`, `meta.next_cursor = null`.
> 
> 
> Mỗi trang tối đa **20 sản phẩm**.
> 

---

## 2. Sản phẩm nổi bật – `GET /api/v1/products/featured`

Trả về danh sách sản phẩm được admin đánh dấu **nổi bật**. Chỉ bao gồm sản phẩm **còn hàng** (`stock > 0` hoặc không giới hạn). Dùng **cursor pagination**.

### Query params

| Param | Type | Bắt buộc | Mặc định | Ghi chú |
| --- | --- | --- | --- | --- |
| `cursor` | string | Không |  | Giá trị `meta.next_cursor` từ response trước. Bỏ trống = trang đầu |
| `per_page` | integer | Không | `20` | Số item mỗi trang (1–50) |

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": [ /* mảng ProductCard */ ],
  "meta": {
    "next_cursor": "eyJzb3J0IjoibmV3ZXN0IiwidmFsIjoiMjAyNi0wNi0yMSAxMDowMDowMCIsImlkIjo0MH0=",
    "has_more": true
  }
}
```

> Sort theo **mới nhất** (newest first). Khi hết data: `meta.has_more = false`, `meta.next_cursor = null`.
> 

---

## 3. Sản phẩm bán chạy – `GET /api/v1/products/bestselling`

Trả về danh sách sản phẩm được admin đánh dấu **bán chạy**. Chỉ bao gồm sản phẩm **còn hàng**. Dùng **cursor pagination**.

### Query params

| Param | Type | Bắt buộc | Mặc định | Ghi chú |
| --- | --- | --- | --- | --- |
| `cursor` | string | Không |  | Giá trị `meta.next_cursor` từ response trước. Bỏ trống = trang đầu |
| `per_page` | integer | Không | `20` | Số item mỗi trang (1–50) |

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": [ /* mảng ProductCard */ ],
  "meta": {
    "next_cursor": "eyJzb3J0IjoibmV3ZXN0IiwidmFsIjoiMjAyNi0wNi0yMSAxMDowMDowMCIsImlkIjo0MH0=",
    "has_more": true
  }
}
```

> Sort theo **mới nhất**. Khi hết data: `meta.has_more = false`, `meta.next_cursor = null`.
> 

---

## 4. Tìm kiếm sản phẩm – `GET /api/v1/products/search`

### Query params

| Param | Type | Bắt buộc | Ghi chú |
| --- | --- | --- | --- |
| `q` | string | **Có** | Từ khoá, tối thiểu 2 ký tự, tối đa 100 |
| `category_id` | integer | Không | Thu hẹp trong category |
| `sort` | string | Không | Giống endpoint list |
| `price_min` | integer | Không |  |
| `price_max` | integer | Không |  |
| `page` | integer | Không | Mặc định 1 |
| `per_page` | integer | Không | Mặc định 15, tối đa 50 |

### Response thành công (HTTP 200)

Giống danh sách — mảng ProductCard + pagination meta.

### ❌ Validation lỗi (HTTP 422)

```json
{
  "success": false,
  "errors": {
    "q": ["The q field must be at least 2 characters."]
  }
}
```

---

## 5. Chi tiết sản phẩm – `GET /api/v1/products/{slug}`

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": {
    "id": 10,
    "name": "Sữa Tươi Vinamilk 1L",
    "slug": "sua-tuoi-vinamilk-1l",
    "sku": "VNM-001",
    "photo": "https://...",
    "thumbnail": "https://...",
    "price": 35000,
    "original_price": 40000,
    "discount_percent": 13,
    "stock": 100,
    "weight": "1kg",
    "details": "<p>Mô tả HTML...</p>",
    "badges": ["sale"],
    "variant_colors": ["Đỏ", "Xanh"],
    "sizes": [
      { "name": "S", "price": 35000 },
      { "name": "M", "price": 40000 },
      { "name": "L", "price": 45000 }
    ],
    "tags": ["dairy", "vinamilk"],
    "rating": 4.5,
    "ratings_count": 120,
    "sold_count": 320,
    "point": 500,
    "is_tax_inclusive": true,
    "tax_rate": 0.0,
    "category": {
      "id": 1,
      "name": "Thực phẩm",
      "slug": "thuc-pham"
    },
    "seller": {
      "id": 5,
      "shop_name": "Shop ABC",
      "photo": "https://.../images/users/avatar.jpg",
      "shop_image": "https://.../images/vendorbanner/banner.jpg",
      "total_products": 42
    },
    "custom_options": [
      {
        "key": "Hương vị",
        "values": [
          { "label": "Vani", "price_extra": 0 },
          { "label": "Dâu",  "price_extra": 5000 }
        ]
      }
    ],
    "galleries": [
      "https://...",
      "https://..."
    ]
  }
}
```

### ❌ Không tìm thấy (HTTP 404)

```json
{ "success": false, "code": 3003, "message": "Product not found." }
```

---

## 6. Sản phẩm liên quan – `GET /api/v1/products/{slug}/related`

Trả về sản phẩm liên quan theo **cursor pagination** — dùng để render section “Có thể bạn thích” / “Sản phẩm tương tự” bên dưới màn hình chi tiết, hỗ trợ infinite scroll.

> Gọi **sau** khi render xong màn hình chính để không làm chậm thời gian hiển thị.
> 

### Query params

| Param | Type | Bắt buộc | Mặc định | Ghi chú |
| --- | --- | --- | --- | --- |
| `cursor` | string | Không |  | Giá trị `meta.next_cursor` từ response trước. Bỏ trống = trang đầu |
| `per_page` | integer | Không | `10` | Số item mỗi trang (1–50) |

### Logic chọn sản phẩm

- Chỉ lấy sản phẩm **active** (`status = 1`) và **publicly visible**
- Nếu sản phẩm có `subcategory_id`: lấy từ cùng **subcategory** hoặc cùng **category**, sort theo `views` giảm dần
- Nếu không có subcategory: lấy từ cùng **category**, sort theo `views` giảm dần
- Loại trừ chính sản phẩm đang xem

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": [ /* mảng ProductCard — cùng cấu trúc mục 1 */ ],
  "meta": {
    "next_cursor": "eyJzb3J0IjoicG9wdWxhciIsInZhbCI6MTIzNCwiaWQiOjd9",
    "has_more": false
  }
}
```

> `data: []` và `meta.has_more = false` nếu không có sản phẩm nào liên quan.
> 
> 
> Khi hết data: `meta.has_more = false`, `meta.next_cursor = null`.
> 

### ❌ Không tìm thấy (HTTP 404)

```json
{ "success": false, "code": 3003, "message": "Product not found." }
```

---

## 7. Trang shop công khai

> Xem tài liệu đầy đủ tại [`mobile-shop-flow.md`](./mobile-shop-flow.md).
> 
> 
> Endpoint: `GET /api/v1/shops/{store_name}/dashboard` — cursor pagination, 20 SP/trang.
> 

---

## Lưu ý

| # | Ghi chú |
| --- | --- |
| 1 | Điều hướng sang chi tiết dùng `slug`, không dùng `id` |
| 2 | `sizes: []` → không có tuỳ chọn size |
| 3 | `variant_colors: []` → không có tuỳ chọn màu |
| 4 | `custom_options: []` → không có tuỳ chọn thêm |
| 5 | `price_extra` trong `custom_options` là **phụ phí thêm vào giá gốc** |
| 6 | `sizes[].price` là giá **sau khi đã tính size** — dùng giá này, không cộng thêm |
| 7 | `stock = 0` → hết hàng, ẩn nút “Thêm vào giỏ” |
| 8 | Khi add vào cart: truyền `size`, `color`, `custom_option_key/value` lấy từ response này |
| 9 | `seller.photo` = avatar người bán (ảnh cá nhân), `seller.shop_image` = banner shop — **có thể null** nếu chưa upload banner |
| 10 | `seller.total_products` = tổng sản phẩm **đang active** của shop — dùng để hiển thị “42 sản phẩm” trên trang shop |
| 11 | `seller` là `null` nếu sản phẩm thuộc về platform (không phải vendor) — kiểm tra trước khi render |
| 12 | Chi tiết sản phẩm được **cache 30 phút** — `total_products` phản ánh thời điểm cache được tạo, không realtime |
| 13 | `sold_count` = tổng số lượng đã bán từ các đơn hàng có trạng thái `completed` — trả `0` nếu chưa có đơn nào hoàn thành |
| 14 | `point` = số điểm DP nhận được khi mua sản phẩm — trả `0` nếu sản phẩm không có điểm thưởng |
| 15 | `is_tax_inclusive = true` → giá sản phẩm đã bao gồm VAT (không cộng thêm). `false` → giá chưa bao gồm VAT, cần cộng thêm `price × tax_rate / 100` khi hiển thị tổng thanh toán |
| 16 | `tax_rate` = % VAT của sản phẩm. `0.0` = không áp thuế. Dùng để hiển thị thông tin thuế trên trang chi tiết và cart |

---

## Changelog

| Ngày | Phiên bản | Thay đổi |
| --- | --- | --- |
| — | v1.0 | Khởi tạo: list, search, detail |
| 2026-06-14 | v1.1 | Thêm `seller.photo`, `seller.shop_image` (nullable), `seller.total_products` vào response chi tiết sản phẩm; bổ sung lưu ý #9–12 về seller block |
| 2026-06-15 | v1.2 | Thêm mục 4 `GET /seller/{store_name}` — sản phẩm của shop, hỗ trợ lọc theo category slug và các query param sort/price |
| 2026-06-18 | v1.3 | Thêm field `point` (điểm DP) vào ProductCard và ProductDetail; `sold_count` giờ lấy thực từ DB (tổng qty đơn `completed`) thay vì hardcode `0` |
| 2026-06-21 | v1.4 | `GET /products` chuyển sang cursor pagination (20 SP/trang). Bỏ `page`/`per_page`, thêm `cursor`, `subcategory_id`, `childcategory_id`. Mục 4 redirect sang `mobile-shop-flow.md` (URL đổi thành `/shops/{store_name}/dashboard`). |
| 2026-06-22 | v1.5 | Thêm mục 4: `GET /products/{slug}/related` — sản phẩm liên quan với cursor pagination; hỗ trợ `cursor` và `per_page` (default 10, max 50); logic gộp subcategory + category trong 1 query, sort theo views giảm dần. |
| 2026-06-24 | v1.6 | Thêm mục 2: `GET /products/featured` và mục 3: `GET /products/bestselling` — danh sách sản phẩm nổi bật / bán chạy (admin-flag), cursor pagination, chỉ hiển thị sản phẩm còn hàng, default 20/trang. Đánh lại số thứ tự các mục từ 3 trở đi. |
| 2026-06-24 | v1.7 | Fix bug mục 6: controller method bị đặt tên sai (`product` thay vì `related`) khiến `GET /products/{slug}/related` trả về lỗi. Đã đổi tên đúng. Bổ sung điều kiện lọc: chỉ trả sản phẩm active + publicly visible. |
| 2026-06-26 | v1.8 | Thêm `is_tax_inclusive` (bool) và `tax_rate` (float, %) vào response chi tiết sản phẩm; bổ sung lưu ý #15–16 về cách sử dụng thuế per-product |