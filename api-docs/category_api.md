# mobile-category-flow

# Category Flow – Mobile Implementation Guide

> **Public** — không cần authentication.
> 
> 
> Base: `/api/v1/`
> 

---

## Cấu trúc cây 3 cấp

```
Category (cấp 1)  →  slug dùng trong URL
└── Subcategory (cấp 2)  →  id dùng trong query param
    └── Child Category (cấp 3)  →  id dùng trong query param
```

---

## 1. Danh sách tất cả category – `GET /api/v1/categories`

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": [
    {
      "id": 1,
      "name": "Thực phẩm",
      "slug": "thuc-pham",
      "icon_url": "https://...",
      "is_featured": true,
      "subcategories": [
        {
          "id": 10,
          "name": "Sữa & Sản phẩm từ sữa",
          "slug": "sua-san-pham-tu-sua",
          "children": [
            { "id": 100, "name": "Sữa tươi", "slug": "sua-tuoi" },
            { "id": 101, "name": "Sữa chua", "slug": "sua-chua" }
          ]
        }
      ]
    }
  ]
}
```

> `is_featured: true` → ưu tiên hiển thị ở menu chính / trang chủ.
> 

---

## 2. Chi tiết một category – `GET /api/v1/categories/{slug}`

Trả về một category kèm cây subcategory đầy đủ — cấu trúc giống mỗi phần tử trong mảng mục 1.

### ❌ Không tìm thấy (HTTP 404)

```json
{ "success": false, "code": 3003, "message": "Category not found." }
```

---

## 3. Sản phẩm theo category – `GET /api/v1/categories/{slug}/products`

Sử dụng **cursor pagination** — phù hợp với infinite scroll trên mobile.

### Query params

| Param | Type | Bắt buộc | Mặc định | Ghi chú |
| --- | --- | --- | --- | --- |
| `subcategory_id` | integer | Không |  | Lọc theo cấp 2 — lấy từ `subcategories[].id` |
| `childcategory_id` | integer | Không |  | Lọc theo cấp 3 — lấy từ `subcategories[].children[].id` |
| `sort` | string | Không | `newest` | `newest` `price_asc` `price_desc` `popular` `rating` |
| `price_min` | integer | Không |  | Giá tối thiểu (VND) |
| `price_max` | integer | Không |  | Giá tối đa (VND) |
| `cursor` | string | Không |  | Giá trị `meta.next_cursor` từ response trước. Bỏ trống = trang đầu |

> **Lưu ý:** `cursor` được gắn với `sort` hiện tại. Nếu đổi `sort`, bỏ `cursor` để reset về trang đầu.
> 

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": [ /* mảng ProductCard — xem mobile-product-flow.md */ ],
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

### ❌ Category không tồn tại (HTTP 404)

```json
{ "success": false, "code": 3003, "message": "Category not found." }
```

---

## Sơ đồ điều hướng

```
GET /categories
└── Render menu sidebar / bottom nav

User chọn category "Thực phẩm" (slug: thuc-pham)
├── GET /categories/thuc-pham
│   └── Dùng subcategories để render filter tab (cấp 2 + cấp 3)
└── GET /categories/thuc-pham/products
    └── Render danh sách sản phẩm (trang đầu)

User lọc theo subcategory (cấp 2, id=10)
└── GET /categories/thuc-pham/products?subcategory_id=10

User lọc theo child category (cấp 3, id=100)
└── GET /categories/thuc-pham/products?subcategory_id=10&childcategory_id=100

User đổi sort → reset cursor
└── GET /categories/thuc-pham/products?sort=price_asc

User lọc giá
└── GET /categories/thuc-pham/products?price_min=10000&price_max=100000

User scroll tới cuối (load more)
└── GET /categories/thuc-pham/products?sort=newest&cursor={meta.next_cursor}
    └── Append vào danh sách, không replace
```

---

## Lưu ý

| # | Ghi chú |
| --- | --- |
| 1 | `GET /categories` trả về cây đầy đủ — dùng để build toàn bộ menu, chỉ gọi 1 lần khi khởi động |
| 2 | `GET /home` trả về flat list category (không có cây con) — chỉ dùng để render icon trang chủ |
| 3 | `subcategory_id` và `childcategory_id` lấy từ response `GET /categories/{slug}` |
| 4 | Có thể truyền cả hai `subcategory_id` + `childcategory_id` cùng lúc |
| 5 | Khi thay đổi bất kỳ filter nào (sort, price, subcategory) → bỏ `cursor`, reset list |

---

## Changelog

| Ngày | Phiên bản | Thay đổi |
| --- | --- | --- |
| — | v1.0 | Khởi tạo: list (cây phân cấp), show, products-by-category |
| 2026-06-21 | v1.1 | `/categories/{slug}/products` chuyển sang cursor pagination (20 SP/trang). Bỏ `page`/`per_page`, thêm `cursor`. |