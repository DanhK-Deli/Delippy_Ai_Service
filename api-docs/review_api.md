# mobile-review-flow

# Review & Rating Flow – Mobile Implementation Guide

> **Public:** GET reviews, GET summary — không cần authentication.
> 
> 
> **Protected:** POST review, GET my-reviews — yêu cầu Bearer token.
> 
> Header: `Authorization: Bearer {access_token}`
> 
> Base: `/api/v1`
> 

---

## Tổng quan luồng đánh giá

```
Màn hình chi tiết sản phẩm
├── GET /products/{id}/reviews/summary  →  hiển thị điểm trung bình + phân bố sao
└── GET /products/{id}/reviews          →  danh sách đánh giá (phân trang)

Màn hình viết đánh giá (yêu cầu login)
└── POST /products/{id}/reviews         →  gửi đánh giá mới

Màn hình đánh giá của tôi (yêu cầu login)
└── GET /my-reviews                     →  danh sách đánh giá của user, kèm thông tin sản phẩm
```

---

## Cấu trúc dùng chung

### ReviewItem (dùng trong list và my-reviews)

```json
{
  "id": 42,
  "rating": 5,
  "review": "Sản phẩm rất tốt, đóng gói cẩn thận.",
  "photo": "https://domain.com/assets/images/reviews/1717200000_abc123.jpg",
  "review_date": "2026-06-01",
  "user": {
    "id": 7,
    "name": "Nguyễn Văn A",
    "photo": "https://domain.com/assets/images/users/avatar.jpg"
  },
  "product": null
}
```

> `photo` là ảnh kèm đánh giá — `null` nếu user không upload.
> 
> 
> `user.photo` là avatar user — `null` nếu chưa có avatar.
> 
> `product` chỉ xuất hiện ở `GET /my-reviews`, `null` ở list đánh giá sản phẩm.
> 

---

## 1. Danh sách đánh giá sản phẩm – `GET /api/v1/products/{productId}/reviews`

> Không cần đăng nhập.
> 

### Query params

| Param | Type | Bắt buộc | Mặc định | Ghi chú |
| --- | --- | --- | --- | --- |
| `page` | integer | Không | `1` | Trang hiện tại |
| `per_page` | integer | Không | `10` | Số item mỗi trang |

### Request

```
GET /api/v1/products/10/reviews?per_page=10&page=1
```

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "message": "Danh sách đánh giá.",
  "data": [
    {
      "id": 42,
      "rating": 5,
      "review": "Sản phẩm rất tốt, đóng gói cẩn thận.",
      "photo": "https://domain.com/assets/images/reviews/1717200000_abc123.jpg",
      "review_date": "2026-06-01",
      "user": {
        "id": 7,
        "name": "Nguyễn Văn A",
        "photo": null
      },
      "product": null
    }
  ],
  "meta": {
    "current_page": 1,
    "last_page": 3,
    "per_page": 10,
    "total": 28,
    "from": 1,
    "to": 10
  }
}
```

> Sắp xếp theo `review_date` mới nhất trước.
> 
> 
> Tải thêm trang: tăng `page` — dừng khi `current_page >= last_page`.
> 

### ❌ Lỗi

| HTTP | Ý nghĩa |
| --- | --- |
| `404` | Sản phẩm không tồn tại |

---

## 2. Tóm tắt rating sản phẩm – `GET /api/v1/products/{productId}/reviews/summary`

> Không cần đăng nhập. Dùng để hiển thị điểm trung bình và thanh phân bố sao.
> 
> 
> Kết quả được **cache 5 phút** — cập nhật sau khi có đánh giá mới.
> 

### Request

```
GET /api/v1/products/10/reviews/summary
```

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "message": "Tóm tắt đánh giá.",
  "data": {
    "average_rating": 4.3,
    "total_reviews": 28,
    "rating_distribution": {
      "5": 14,
      "4": 8,
      "3": 3,
      "2": 2,
      "1": 1
    }
  }
}
```

| Field | Type | Ghi chú |
| --- | --- | --- |
| `average_rating` | float | Điểm trung bình, làm tròn 1 chữ số thập phân. `0` nếu chưa có đánh giá nào |
| `total_reviews` | integer | Tổng số đánh giá |
| `rating_distribution` | object | Số lượng đánh giá theo từng mức sao (1–5) |

> **Tip:** Dùng `rating_distribution` để render thanh progress bar theo tỷ lệ:
> 
> 
> `width = (count / total_reviews) * 100%`
> 

---

## 3. Tạo đánh giá – `POST /api/v1/products/{productId}/reviews`

> **Yêu cầu đăng nhập.**
> 
> 
> **Content-Type: `multipart/form-data`** (do có upload ảnh).
> 
> User chỉ được đánh giá sản phẩm đã **mua và hoàn thành đơn hàng** (`status = completed`).
> 
> Mỗi user chỉ được đánh giá **1 lần** cho mỗi sản phẩm.
> 

### Request fields

| Field | Type | Bắt buộc | Ghi chú |
| --- | --- | --- | --- |
| `rating` | integer | **Có** | Từ `1` đến `5` |
| `review` | string | Không | Nhận xét bằng văn bản, tối đa 1000 ký tự |
| `photo` | file | Không | Ảnh kèm đánh giá. Định dạng: `jpeg`, `jpg`, `png`, `gif`. Tối đa **5 MB** |

### Request (multipart/form-data)

```
POST /api/v1/products/10/reviews
Content-Type: multipart/form-data

rating=5
review=Sản phẩm rất tốt, đóng gói cẩn thận.
photo=<file>
```

### Response thành công (HTTP 201)

```json
{
  "success": true,
  "code": 1001,
  "message": "Đánh giá của bạn đã được ghi nhận.",
  "data": {
    "id": 42,
    "rating": 5,
    "review": "Sản phẩm rất tốt, đóng gói cẩn thận.",
    "photo": "https://domain.com/assets/images/reviews/1717200000_abc123.jpg",
    "review_date": "2026-06-01",
    "user": {
      "id": 7,
      "name": "Nguyễn Văn A",
      "photo": null
    },
    "product": null
  }
}
```

### ❌ Lỗi

| HTTP | Code | Ý nghĩa |
| --- | --- | --- |
| `401` | — | Chưa đăng nhập |
| `404` | — | Sản phẩm không tồn tại |
| `422` | — | Validation lỗi field (thiếu `rating`, sai định dạng ảnh, ảnh vượt 5 MB…) |
| `422` | — | User chưa mua sản phẩm này (chưa có đơn `completed`) |
| `422` | — | User đã đánh giá sản phẩm này rồi |

> Khi HTTP 422 không phải do validation field, `message` trả về mô tả lỗi cụ thể.
> 
> 
> Phân biệt hai trường hợp bằng cách kiểm tra `errors` object: có field errors → validation; không có → lỗi nghiệp vụ.
> 

---

## 4. Đánh giá của tôi – `GET /api/v1/my-reviews`

> **Yêu cầu đăng nhập.** Trả về tất cả đánh giá của user đang đăng nhập, kèm thông tin sản phẩm.
> 

### Query params

| Param | Type | Bắt buộc | Mặc định | Ghi chú |
| --- | --- | --- | --- | --- |
| `page` | integer | Không | `1` |  |
| `per_page` | integer | Không | `10` |  |

### Request

```
GET /api/v1/my-reviews?per_page=10&page=1
Authorization: Bearer {access_token}
```

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "message": "Danh sách đánh giá.",
  "data": [
    {
      "id": 42,
      "rating": 5,
      "review": "Sản phẩm rất tốt, đóng gói cẩn thận.",
      "photo": null,
      "review_date": "2026-06-01",
      "user": {
        "id": 7,
        "name": "Nguyễn Văn A",
        "photo": null
      },
      "product": {
        "id": 10,
        "name": "Sữa Tươi Vinamilk 1L",
        "slug": "sua-tuoi-vinamilk-1l",
        "photo": "https://domain.com/assets/images/products/thumb.jpg"
      }
    }
  ],
  "meta": {
    "current_page": 1,
    "last_page": 2,
    "per_page": 10,
    "total": 14,
    "from": 1,
    "to": 10
  }
}
```

> `product` luôn có giá trị ở endpoint này — dùng để hiển thị ảnh và tên sản phẩm trong list.
> 

### ❌ Lỗi

| HTTP | Ý nghĩa |
| --- | --- |
| `401` | Chưa đăng nhập |

---

## Sơ đồ flow tổng quát

```
╔══════════════════════════════════════════════════════════════╗
║              MÀN HÌNH CHI TIẾT SẢN PHẨM                      ║
╚══════════════════════════════════════════════════════════════╝

Render trang sản phẩm (song song)
├── GET /products/{id}/reviews/summary  →  điểm TB + phân bố sao (widget rating)
└── GET /products/{id}/reviews          →  10 đánh giá đầu tiên

Load thêm đánh giá (infinite scroll)
└── GET /products/{id}/reviews?page=2

╔══════════════════════════════════════════════════════════════╗
║              NÚT "VIẾT ĐÁNH GIÁ"                             ║
╚══════════════════════════════════════════════════════════════╝

Hiện nút "Viết đánh giá" khi:
- User đã đăng nhập
- Đơn hàng có chứa sản phẩm này đã completed
- (Kiểm tra phía server khi gửi, không cần pre-check phía client)

User nhấn "Viết đánh giá"
└── Chưa đăng nhập → redirect màn hình login
    └── Đã đăng nhập → mở form đánh giá

User điền form (rating + review text + ảnh tuỳ chọn) → nhấn Gửi
└── POST /products/{id}/reviews (multipart/form-data)
    ├── 201 → hiển thị thành công → cập nhật summary (gọi lại GET summary)
    ├── 422 "must_purchase_first" → thông báo "Bạn cần mua sản phẩm này trước"
    ├── 422 "already_reviewed"   → thông báo "Bạn đã đánh giá sản phẩm này rồi"
    └── 422 validation           → hiển thị lỗi từng field

╔══════════════════════════════════════════════════════════════╗
║              MÀN HÌNH "ĐÁNH GIÁ CỦA TÔI"                    ║
╚══════════════════════════════════════════════════════════════╝

Mở màn hình
└── GET /my-reviews?per_page=10  →  render danh sách (kèm ảnh sản phẩm)

Load thêm
└── GET /my-reviews?per_page=10&page=2
```

---

## Lưu ý quan trọng

| # | Ghi chú |
| --- | --- |
| 1 | Upload ảnh phải dùng **`multipart/form-data`**, KHÔNG dùng `application/json` |
| 2 | Điều kiện viết đánh giá được kiểm tra **phía server** — không cần pre-check phía client |
| 3 | Mỗi user chỉ được đánh giá **1 lần** / 1 sản phẩm — disable nút sau khi gửi thành công |
| 4 | `rating_distribution` trả về key là string `"1"`…`"5"`, không phải integer |
| 5 | Summary được **cache 5 phút** — sau khi POST review thành công, gọi lại GET summary để refresh |
| 6 | `review_date` trả về dạng `"YYYY-MM-DD"` (date only, không có giờ) |
| 7 | `photo` trong review là URL đầy đủ — render trực tiếp, không cần ghép domain |

---

## Changelog

| Ngày | Phiên bản | Thay đổi |
| --- | --- | --- |
| 2026-06-05 | v1.0 | Khởi tạo: product-reviews, rating-summary, create-review (multipart), my-reviews |