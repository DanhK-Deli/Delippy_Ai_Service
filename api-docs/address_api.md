# mobile-address-flow

# Address Flow – Mobile Implementation Guide

> **Yêu cầu Bearer token** cho tất cả endpoint.
> 
> 
> Header: `Authorization: Bearer {access_token}`
> 
> Base: `/api/v1/addresses`
> 

---

## Cấu trúc một Address object

```json
{
  "id": 5,
  "recipient_name": "Nguyễn Văn A",
  "phone": "0912345678",
  "province": {
    "id": 1,
    "name": "Hà Nội",
    "code": "HN"
  },
  "district": {
    "id": 10,
    "name": "Quận Ba Đình",
    "code": "003",
    "province_id": 1
  },
  "ward": {
    "id": 100,
    "name": "Phường Phúc Xá",
    "code": "00001",
    "district_id": 10
  },
  "address_detail": "Số 5, Ngõ 12, Đường Trần Phú",
  "label": "Nhà riêng",
  "full_address": "Số 5, Ngõ 12, Đường Trần Phú, Phường Phúc Xá, Quận Ba Đình, Hà Nội",
  "is_default": true,
  "created_at": "2025-01-15T08:30:00.000000Z"
}
```

| Field | Mô tả |
| --- | --- |
| `id` | Dùng trong path `/addresses/{id}` |
| `label` | Nhãn tự đặt cho địa chỉ (vd: “Nhà riêng”, “Văn phòng”) — có thể `null` |
| `full_address` | Chuỗi ghép sẵn `address_detail + ward + district + province` — dùng để hiển thị trong cart / checkout |
| `is_default` | `true` nếu là địa chỉ mặc định; chỉ có **duy nhất 1** địa chỉ mặc định |

---

## 1. Danh sách địa chỉ – `GET /api/v1/addresses`

Trả về tất cả địa chỉ của user, **địa chỉ mặc định luôn đứng đầu**.

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "data": [
    {
      "id": 5,
      "recipient_name": "Nguyễn Văn A",
      "phone": "0912345678",
      "province": { "id": 1, "name": "Hà Nội", "code": "HN" },
      "district": { "id": 10, "name": "Quận Ba Đình", "code": "003", "province_id": 1 },
      "ward": { "id": 100, "name": "Phường Phúc Xá", "code": "00001", "district_id": 10 },
      "address_detail": "Số 5, Ngõ 12, Đường Trần Phú",
      "label": "Nhà riêng",
      "full_address": "Số 5, Ngõ 12, Đường Trần Phú, Phường Phúc Xá, Quận Ba Đình, Hà Nội",
      "is_default": true,
      "created_at": "2025-01-15T08:30:00.000000Z"
    }
  ]
}
```

> Chưa có địa chỉ nào → `data: []`.
> 
> 
> Thứ tự: mặc định trước, sau đó theo `created_at` mới nhất.
> 

---

## 2. Chi tiết địa chỉ – `GET /api/v1/addresses/{id}`

### Response thành công (HTTP 200)

Trả về 1 Address object như cấu trúc trên.

### ❌ Lỗi

| HTTP | Ý nghĩa |
| --- | --- |
| `404` | Địa chỉ không tồn tại hoặc không thuộc về user hiện tại |

---

## 3. Tạo địa chỉ mới – `POST /api/v1/addresses`

### Request

```json
{
  "recipient_name": "Nguyễn Văn A",
  "phone": "0912345678",
  "province_id": 1,
  "district_id": 10,
  "ward_id": 100,
  "address_detail": "Số 5, Ngõ 12, Đường Trần Phú",
  "is_default": true
}
```

| Field | Type | Bắt buộc | Ghi chú |
| --- | --- | --- | --- |
| `recipient_name` | string (max 255) | **Có** | Tên người nhận hàng |
| `phone` | string | **Có** | Format `0xxxxxxxxx` hoặc `+84xxxxxxxxx` |
| `province_id` | integer | **Có** | `id` từ `GET /locations/provinces` |
| `district_id` | integer | **Có** | `id` từ `GET /locations/districts` — phải thuộc `province_id` |
| `ward_id` | integer | **Có** | `id` từ `GET /locations/wards` — phải thuộc `district_id` |
| `address_detail` | string (max 500) | **Có** | Số nhà, tên đường, ngõ/hẻm |
| `label` | string (max 255) | Không | Nhãn tự đặt, vd: “Nhà riêng”, “Văn phòng” |
| `is_default` | boolean | Không | Mặc định `false` |

> **Địa chỉ đầu tiên** của user sẽ tự động được set `is_default = true` bất kể có truyền `is_default` hay không.
> 
> 
> Nếu `is_default: true` → các địa chỉ khác bị unset default.
> 

### Validation quan trọng

- `district_id` phải thuộc `province_id` đã truyền — server kiểm tra quan hệ này.
- `ward_id` phải thuộc `district_id` đã truyền — server kiểm tra quan hệ này.

### Response thành công (HTTP 200)

Trả về Address object vừa tạo.

### ❌ Lỗi

| HTTP | Ý nghĩa |
| --- | --- |
| `422` | Validation lỗi — field sai hoặc district/ward không thuộc province/district tương ứng |

---

## 4. Cập nhật địa chỉ – `PUT /api/v1/addresses/{id}`

Chỉ cần truyền các field muốn thay đổi (partial update).

### Request

```json
{
  "recipient_name": "Trần Thị B",
  "phone": "0987654321"
}
```

Có thể cập nhật bất kỳ field nào trong `CreateAddressRequest` (tất cả đều là `sometimes`).

> **Lưu ý `is_default`:**
> 
> 
> - Set `is_default: true` → unset tất cả địa chỉ khác, địa chỉ này thành default.
> 
> - Set `is_default: false` trên địa chỉ **đang là default** → server **giữ nguyên** `is_default: true`, không cho phép unset địa chỉ default duy nhất. Dùng endpoint Set Default hoặc xóa rồi tạo lại nếu cần.
> 

### Response thành công (HTTP 200)

Trả về Address object sau khi cập nhật.

### ❌ Lỗi

| HTTP | Ý nghĩa |
| --- | --- |
| `404` | Địa chỉ không tồn tại hoặc không thuộc về user |
| `422` | Validation lỗi |

---

## 5. Xóa địa chỉ – `DELETE /api/v1/addresses/{id}`

### Business rules

| Tình huống | Kết quả |
| --- | --- |
| User chỉ có **1 địa chỉ** | **422** — không cho phép xóa |
| Xóa địa chỉ **không phải default** | Xóa bình thường |
| Xóa địa chỉ **là default** | Xóa thành công + địa chỉ còn lại đầu tiên (theo `created_at`) tự động được set default |

### Response thành công (HTTP 200)

```json
{
  "success": true,
  "code": 1000,
  "message": "..."
}
```

> `data: null` — sau khi xóa cần gọi lại `GET /addresses` để refresh danh sách.
> 

### ❌ Lỗi

| HTTP | Ý nghĩa |
| --- | --- |
| `404` | Địa chỉ không tồn tại hoặc không thuộc về user |
| `422` | Đây là địa chỉ duy nhất, không thể xóa |

---

## 6. Đặt địa chỉ mặc định – `POST /api/v1/addresses/{id}/set-default`

Không cần request body.

### Response thành công (HTTP 200)

Trả về Address object đã được set default (với `is_default: true`).

> Tất cả địa chỉ khác của user sẽ tự động bị set `is_default: false`.
> 

### ❌ Lỗi

| HTTP | Ý nghĩa |
| --- | --- |
| `404` | Địa chỉ không tồn tại hoặc không thuộc về user |

---

## Sơ đồ flow tổng quát

```
╔══════════════════════════════════════════════════════════════╗
║                 MÀIN HÌNH DANH SÁCH ĐỊA CHỈ                 ║
╚══════════════════════════════════════════════════════════════╝

Mở màn hình
└── GET /addresses  →  render danh sách, địa chỉ default ở đầu

User nhấn "Đặt mặc định" trên một địa chỉ
└── POST /addresses/{id}/set-default
    └── 200  →  cập nhật UI (đổi badge default), không cần GET lại

User nhấn "Xóa"
├── Chỉ có 1 địa chỉ  →  disable nút / hiển thị thông báo không thể xóa
└── POST /addresses/{id}/delete
    ├── 200  →  xóa khỏi danh sách, tự refresh nếu đây là default
    └── 422  →  hiển thị lỗi (địa chỉ duy nhất)

╔══════════════════════════════════════════════════════════════╗
║               MÀIN HÌNH TẠO ĐỊA CHỈ MỚI                     ║
╚══════════════════════════════════════════════════════════════╝

Mở form
└── GET /locations/provinces  →  load dropdown Tỉnh/Thành

User chọn Tỉnh (province_id)
└── GET /locations/districts?province_id=X  →  load dropdown Quận/Huyện
    └── Reset district_id, ward_id về trống

User chọn Quận (district_id)
└── GET /locations/wards?district_id=X  →  load dropdown Phường/Xã
    └── Reset ward_id về trống

User chọn Phường, điền thông tin → nhấn "Lưu"
└── POST /addresses { recipient_name, phone, province_id, district_id, ward_id, address_detail, is_default? }
    ├── 200  →  quay lại danh sách, refresh GET /addresses
    └── 422  →  hiển thị lỗi từng field

╔══════════════════════════════════════════════════════════════╗
║               MÀIN HÌNH SỬA ĐỊA CHỈ                         ║
╚══════════════════════════════════════════════════════════════╝

Mở form (pre-fill từ GET /addresses/{id})
├── Tỉnh/Quận/Phường đã có sẵn từ address.province/district/ward
└── GET /locations/provinces (nếu chưa cache)

User thay đổi Tỉnh → reset dropdown Quận và Phường → GET /locations/districts
User thay đổi Quận → reset dropdown Phường → GET /locations/wards

User nhấn "Cập nhật"
└── PUT /addresses/{id} { ...changed_fields }
    ├── 200  →  quay lại danh sách, refresh
    └── 422 / 404  →  hiển thị lỗi

╔══════════════════════════════════════════════════════════════╗
║               MÀIN HÌNH CHECKOUT (chọn địa chỉ)             ║
╚══════════════════════════════════════════════════════════════╝

Mở màn hình chọn địa chỉ giao hàng
└── GET /addresses  →  hiển thị danh sách, pre-select địa chỉ default

User chọn địa chỉ khác (không nhấn "Đặt mặc định")
└── Lưu address.id vào checkout state, KHÔNG gọi set-default
    (set-default chỉ khi user muốn thay đổi default lâu dài)
```

---

## Lưu ý

| # | Ghi chú |
| --- | --- |
| 1 | `full_address` là chuỗi đầy đủ ghép sẵn — dùng luôn để hiển thị trong cart/checkout, không tự ghép lại |
| 2 | Địa chỉ **đầu tiên** tạo ra luôn là default — không cần hỏi user |
| 3 | Không cho phép user unset default bằng `PUT is_default: false` — chỉ đặt default mới qua `set-default` hoặc `PUT is_default: true` trên địa chỉ khác |
| 4 | Khi xóa địa chỉ đang là default → server tự chọn địa chỉ tiếp theo làm default; gọi `GET /addresses` để cập nhật UI |
| 5 | `province_id`, `district_id`, `ward_id` phải có **quan hệ hợp lệ** — district phải thuộc province, ward phải thuộc district |
| 6 | Trong checkout, lưu `address.id` vào state để truyền vào request đặt hàng — không cần truyền lại toàn bộ thông tin địa chỉ |
| 7 | `label` là tuỳ chọn, có thể `null` — dùng để hiển thị nhãn phân loại địa chỉ trên UI |
| 8 | Địa chỉ bị xóa là **soft delete** — không hiển thị lại cho user, mobile không cần xử lý thêm |

---

## Changelog

| Ngày | Phiên bản | Thay đổi |
| --- | --- | --- |
| — | v1.0 | Khởi tạo: list, detail, create, update, delete, set-default |
| 2026-06-09 | v1.1 | Thêm field `label` (optional); DELETE chuyển sang soft delete |