# mobile-wishlist-flow

# Wishlist Flow – Mobile Implementation Guide

> **Yêu cầu Bearer token** cho tất cả endpoint.
> 
> 
> Header: `Authorization: Bearer {access_token}`
> 
> Base: `/api/v1/wishlist`
> 

---

## 1. Danh sách wishlist – `GET /api/v1/wishlist`

Trả về toàn bộ sản phẩm trong wishlist của user.

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": [
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
  ]
}
```

> Trả về mảng **ProductCard** — cùng cấu trúc với danh sách sản phẩm (xem `mobile-product-flow.md`).
> 
> 
> Wishlist rỗng → `data: []`.
> 
> Sản phẩm đã bị ngừng bán / xóa sẽ **không xuất hiện** trong danh sách này.
> 
> **Không có pagination** — trả về toàn bộ trong 1 lần.
> 

---

## 2. Toggle wishlist – `POST /api/v1/wishlist/toggle`

Thêm vào wishlist nếu chưa có, xóa khỏi wishlist nếu đã có — **một endpoint duy nhất cho cả 2 hành động**.

### Request

```json
{
  "product_id": 10
}
```

### Response thành công (HTTP 200)

**Khi thêm vào:**

```json
{
  "success": true,
  "code": 1000,
  "data": {
    "in_wishlist": true
  }
}
```

**Khi xóa khỏi:**

```json
{
  "success": true,
  "code": 1000,
  "data": {
    "in_wishlist": false
  }
}
```

> Dùng `data.in_wishlist` để **cập nhật ngay trạng thái icon tim** trên UI — không cần gọi lại `GET /wishlist`.
> 

### ❌ Sản phẩm không tồn tại (HTTP 422)

```json
{
  "success": false,
  "errors": {
    "product_id": ["The selected product id is invalid."]
  }
}
```

---

## Cách lấy trạng thái wishlist cho từng sản phẩm

API **không có endpoint riêng** để check một sản phẩm có trong wishlist không. Mobile xử lý theo cách sau:

```
Khi mở màn hình danh sách / search / category
└── GET /wishlist → lưu danh sách product_id vào local state (Set/Map)
    └── Dùng set này để render trạng thái icon tim cho từng sản phẩm

Khi mở màn hình chi tiết sản phẩm
└── Kiểm tra local state xem product.id có trong wishlist set không
    └── Hiển thị icon tim đầy / rỗng tương ứng

Khi user nhấn icon tim
└── POST /wishlist/toggle { product_id }
    └── 200 → cập nhật local state và icon theo data.in_wishlist
```

---

## Sơ đồ flow

```
Mở màn hình Wishlist
└── GET /wishlist → render danh sách

User nhấn icon tim trên màn hình chi tiết / danh sách sản phẩm
└── POST /wishlist/toggle { product_id: 10 }
    ├── in_wishlist: true  → icon tim đầy ❤️
    └── in_wishlist: false → icon tim rỗng 🤍

User nhấn tim lần nữa
└── POST /wishlist/toggle { product_id: 10 }  (gọi cùng endpoint)
    └── in_wishlist: false → icon tim rỗng 🤍
```

---

## Lưu ý

| # | Ghi chú |
| --- | --- |
| 1 | Chỉ 1 endpoint toggle cho cả add lẫn remove — không có `POST /add` hay `DELETE /remove` riêng |
| 2 | Dùng `in_wishlist` từ response toggle để cập nhật UI ngay, không cần refetch `GET /wishlist` |
| 3 | Lấy `GET /wishlist` 1 lần khi khởi động app, lưu `product_id` vào local state để hiển thị icon tim trên các màn hình khác |
| 4 | Sản phẩm ngừng bán sẽ tự động biến mất khỏi `GET /wishlist` nhưng toggle vẫn thành công — xử lý gracefully |
| 5 | Chưa login → nhấn tim → redirect màn hình login, lưu lại `product_id` để toggle sau khi login xong |

---

## Changelog

| Ngày | Phiên bản | Thay đổi |
| --- | --- | --- |
| — | v1.0 | Khởi tạo: list, toggle (add/remove) |