# mobile-account-flow

# Account Flow – Mobile Implementation Guide

> **Yêu cầu Bearer token** cho tất cả endpoint trong nhóm này.
> 
> 
> Header: `Authorization: Bearer {access_token}`
> 
> Base: `/api/v1/auth/`
> 

---

## 1. Lấy thông tin profile – `GET /api/v1/auth/profile`

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": {
    "id": 42,
    "name": "Nguyen Van A",
    "email": "user@example.com",
    "phone": "0912345678",
    "photo": "https://...",
    "address": "123 Nguyen Trai, Q1",
    "ranking": "Đồng",
    "reward_point": 100,
    "shopping_point": 50,
    "bank_account_number": null,
    "bank_account_name": null,
    "bank_name": null,
    "bank_address": null,
    "is_vendor": 2,
    "shop_name": "Cửa hàng ABC",
    "shop_image": "https://..."
  }
}
```

> `photo` là `null` nếu chưa upload ảnh.
> 
> 
> `ranking` là tên hạng thành viên dạng string.
> 
> `is_vendor`: `0` = buyer thường, `1` = đang chờ duyệt / bị tắt, `2` = seller đang hoạt động.
> 
> `shop_name` và `shop_image` là `null` nếu user chưa thiết lập shop.
> 

---

## 2. Cập nhật profile – `POST /api/v1/auth/profile`

> **Content-Type:** `multipart/form-data` (bắt buộc khi có upload ảnh).
> 
> 
> Tất cả field đều **optional** — chỉ gửi field cần thay đổi.
> 

### Request

| Field | Type | Ghi chú |
| --- | --- | --- |
| `name` | string |  |
| `email` | string | Phải là email hợp lệ |
| `phone` | string |  |
| `address` | string |  |
| `photo` | file (JPEG/PNG) | Khuyến nghị < 2MB |

### Response thành công (HTTP 200)

Trả về object profile đầy đủ — giống hệt `GET /profile`.

### ❌ Validation lỗi (HTTP 422)

```json
{
  "success": false,
  "errors": {
    "email": ["The email field must be a valid email address."]
  }
}
```

---

## 3. Đổi mật khẩu – `POST /api/v1/auth/change-password`

### Request

```json
{
  "current_password": "oldpassword123",
  "new_password": "newpassword456"
}
```

### Responses

**✅ Thành công (HTTP 200)**

```json
{
  "success": true,
  "code": 1000,
  "data": null
}
```

**❌ Mật khẩu hiện tại sai (HTTP 400, code 2000)**

```json
{ "success": false, "code": 2000, "message": "..." }
```

**❌ Mật khẩu mới trùng mật khẩu cũ (HTTP 400, code 2000)**

```json
{ "success": false, "code": 2000, "message": "..." }
```

---

## 4. Refresh token – `POST /api/v1/auth/refresh`

> Token cũ bị **vô hiệu hóa ngay lập tức** sau khi refresh. Không dùng lại token cũ.
> 

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": {
    "access_token": "eyJ...",
    "token_type": "bearer",
    "expires_in": 3600
  }
}
```

### ❌ Token hết hạn / không hợp lệ (HTTP 401)

```json
{ "success": false, "code": 2001, "message": "..." }
```

> Xóa token cũ và redirect về màn hình login.
> 

---

## 5. Đăng xuất – `POST /api/v1/auth/logout`

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": null
}
```

> Xóa `access_token` khỏi local storage ngay sau khi nhận response.
> 

---

## Sơ đồ xử lý token hết hạn

```
Bất kỳ request protected nào nhận 401
├── Gọi POST /auth/refresh
│   ├── 200 → lưu access_token mới → retry request gốc (tối đa 1 lần)
│   └── 401 → xóa token, redirect login
└── (nếu không auto-refresh) → redirect login
```

---

## Lưu ý

| # | Ghi chú |
| --- | --- |
| 1 | Cập nhật profile phải dùng `multipart/form-data` — kể cả khi không upload ảnh |
| 2 | Không gửi field `photo` nếu không muốn thay đổi ảnh |
| 3 | `expires_in` tính bằng **giây** (3600s = 1 giờ) |
| 4 | Sau `logout`, token cũ không còn dùng được — xóa ngay khỏi storage |
| 5 | Chỉ retry request gốc **1 lần** sau khi refresh — tránh vòng lặp vô tận |

---

## Changelog

| Ngày | Phiên bản | Thay đổi |
| --- | --- | --- |
| — | v1.0 | Khởi tạo: profile, update-profile, change-password, refresh, logout |
| 2026-06-11 | v1.1 | Thêm fields `is_vendor`, `shop_name`, `shop_image` vào profile response |