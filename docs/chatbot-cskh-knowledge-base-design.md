# Quy trình nghiệp vụ Delippy (A–Z) — dùng để train Chatbot CSKH hướng dẫn thao tác

> Tài liệu mô tả **chuỗi thao tác thật trong app** (màn hình nào, bấm nút gì, theo thứ tự nào) cho từng tình huống người dùng hay hỏi. Mục tiêu: khi khách hỏi "làm sao đổi mật khẩu", "hàng tôi đâu rồi", "làm sao trả hàng"... chatbot tra đúng luồng tương ứng và trả lời bằng các bước thật — không tự bịa màn hình/nút không tồn tại.
>
> Toàn bộ tên màn hình, nút, label dưới đây lấy **nguyên văn từ code** (`lib/l10n/app_vi.arb` và các file trang/widget tương ứng), kèm key l10n và đường dẫn file để đối chiếu khi tính năng thay đổi. Mỗi luồng có thể tách thành 1 bản ghi JSON riêng (id = mã luồng ở đầu mỗi mục) để nạp cho hệ thống tra cứu của chatbot.

## Cách đọc tài liệu này

Mỗi luồng có cấu trúc:
- **Khi nào dùng luồng này**: các câu hỏi/tình huống khách thường hỏi để kích hoạt luồng.
- **Điều kiện tiên quyết**: cần đăng nhập hay không, đơn phải ở trạng thái nào...
- **Các bước**: Bước 1 → Bước 2 → ... theo đúng thứ tự thao tác thật, tên màn hình/nút in đậm.
- **Ghi chú cho chatbot**: các trường hợp đặc biệt, tính năng chưa hoạt động thật (placeholder), hoặc chỗ dễ trả lời sai nếu không biết trước.

**Quan trọng — đánh dấu trạng thái tính năng**, dùng xuyên suốt tài liệu:
- 🟢 **Hoạt động đầy đủ** — chatbot có thể hướng dẫn chắc chắn.
- 🟡 **Có giao diện nhưng chưa xử lý thật** (bấm vào chỉ hiện toast "sắp ra mắt"/"đang phát triển") — chatbot phải nói rõ tính năng chưa khả dụng, không hướng dẫn như thể nó hoạt động.
- 🔴 **Không có điểm vào trong UI** (tính năng có code nhưng người dùng không cách nào bấm tới được) — chatbot **tuyệt đối không được hướng dẫn** "vào mục X để làm Y" vì X không tồn tại trên giao diện thật; phải chuyển hướng sang cách khác hoặc escalate CSKH.

## Bảng tổng hợp toàn bộ luồng

| Mã luồng | Tên luồng | Trạng thái |
|---|---|---|
| `ACC-01` | Đăng ký tài khoản | 🟢 |
| `ACC-02` | Đăng nhập | 🟢 |
| `ACC-03` | Quên mật khẩu | 🟢 |
| `ACC-04` | Đổi mật khẩu (đã đăng nhập) | 🟢 |
| `ACC-05` | Đăng xuất | 🟢 |
| `ACC-06` | Xem/sửa thông tin cá nhân | 🟢 |
| `ACC-07` | Quản lý sổ địa chỉ giao hàng | 🟢 |
| `ACC-08` | Xoá tài khoản | 🟡 (chuyển ra web ngoài) |
| `ACC-09` | Đăng nhập/liên kết Google | 🔴 (nút bị ẩn) |
| `ACC-10` | Đăng ký bán hàng (seller) | 🟡 (chỉ hiện thông báo liên hệ admin) |
| `SHOP-01` | Mua hàng đầy đủ (xem sp → giỏ hàng → checkout → đặt hàng) | 🟢 |
| `SHOP-02` | Thanh toán qua SePay (quét QR) | 🟢 |
| `SHOP-03` | Áp dụng mã giảm giá (voucher sàn + voucher shop) | 🟢 |
| `SHOP-04` | Sử dụng điểm thưởng DP | 🟢 |
| `ORD-01` | Xem danh sách đơn hàng theo trạng thái | 🟢 |
| `ORD-02` | Xem chi tiết đơn hàng | 🟢 |
| `ORD-03` | Huỷ đơn hàng | 🟢 (điều kiện trạng thái) |
| `ORD-04` | Theo dõi vận chuyển | 🟢 (timeline trong trang chi tiết) |
| `ORD-05` | Liên hệ shop về đơn hàng | 🟡 (chỉ toast "sắp ra mắt") |
| `ORD-06` | Yêu cầu đổi trả sản phẩm | 🔴 (không có nút vào trong app) |
| `ORD-07` | Đánh giá sản phẩm sau khi nhận hàng | 🟢 |
| `BOT-01` | Truy cập chatbot & chuyển đổi mode Tư vấn/CSKH | 🟢 (một phần quick-action là 🟡) |

---

## Nhóm A — Tài khoản

### ACC-01. Đăng ký tài khoản 🟢

**Khi nào dùng**: "làm sao đăng ký", "tạo tài khoản mới", "tôi chưa có tài khoản".

**Điều kiện tiên quyết**: chưa đăng nhập.

**Các bước**:
1. Từ tab **"Tài khoản"** (chưa đăng nhập) hoặc màn Đăng nhập, bấm **"Đăng ký ngay"** / **"Đăng ký"**.
2. Điền form: **Họ tên**, **Email**, **Số điện thoại**, **Mật khẩu**, **Xác nhận mật khẩu**.
3. Tick đồng ý **"Tôi đồng ý với Điều khoản sử dụng và Chính sách bảo mật"** (bắt buộc, không tick sẽ báo lỗi).
4. Bấm **"Đăng ký"**.
5. App gửi mã OTP về email, chuyển tới màn **"Xác thực email"** — nhập mã 6 số, bấm **"Xác nhận"**. Có thể bấm **"Gửi lại mã"** sau khi hết đếm ngược, hoặc **"Quay lại đăng ký"**.
6. Xác thực thành công → tự động đăng nhập, vào **Trang chủ**.

**Ghi chú cho chatbot**: OTP gửi qua **email** đăng ký (không phải SMS) — nếu khách hỏi "sao không thấy tin nhắn", cần hỏi lại "đã kiểm tra hộp thư email chưa" trước khi kết luận lỗi hệ thống.

---

### ACC-02. Đăng nhập 🟢

**Khi nào dùng**: "không đăng nhập được", "làm sao đăng nhập".

**Các bước**:
1. Vào màn **"Đăng nhập tài khoản"** — từ nút **"Đăng nhập"** ở tab Tài khoản khi chưa login, hoặc app tự đưa tới màn này khi bấm vào chức năng cần đăng nhập.
2. Nhập **"Email hoặc số điện thoại"** và **"Mật khẩu"**.
3. Bấm **"Đăng nhập"**.

**Ghi chú cho chatbot**: Ô định danh nhận cả email lẫn số điện thoại — nếu khách chắc chắn nhớ đúng nhưng vẫn báo lỗi, hướng khách sang luồng `ACC-03` (quên mật khẩu) thay vì chỉ lặp lại "thử lại".

---

### ACC-03. Quên mật khẩu 🟢

**Khi nào dùng**: "quên mật khẩu", "không nhớ mật khẩu", "không đăng nhập được vì quên mật khẩu".

**Các bước**:
1. Tại màn Đăng nhập, bấm **"Quên mật khẩu?"**.
2. Màn **"Quên mật khẩu?"** hiện ra, nhập **"Email"** đã đăng ký, bấm **"Gửi mã OTP"**.
3. App chuyển sang màn nhập mã OTP (đặt lại mật khẩu) — nhập mã 6 số vừa nhận qua email, bấm xác nhận. Nếu hết hạn, bấm **"Gửi lại mã"**.
4. Xác thực đúng → chuyển tới màn **"Tạo mật khẩu mới"**.
5. Nhập **"Mật khẩu mới"** và **"Xác nhận mật khẩu"**, bấm **"Đặt lại mật khẩu"**.
6. Thành công → quay lại màn Đăng nhập, đăng nhập lại bằng mật khẩu mới.

**Ghi chú cho chatbot**: đây là luồng **khác hoàn toàn** với `ACC-04` (đổi mật khẩu khi đang đăng nhập) — luồng này dùng khi khách **không vào được app**. Nếu khách đang đăng nhập bình thường chỉ muốn đổi mật khẩu, hướng dẫn theo `ACC-04`, không đưa luồng này (không cần nhập email lại, không cần OTP).

---

### ACC-04. Đổi mật khẩu (đã đăng nhập) 🟢

**Khi nào dùng**: "làm sao đổi mật khẩu" (khi đã đăng nhập bình thường). *Đây chính là ví dụ mẫu bạn đưa ra.*

**Điều kiện tiên quyết**: đã đăng nhập.

**Các bước**:
1. Vào tab **"Tài khoản"**.
2. Bấm mục **"Thông tin tài khoản"**.
3. Trong màn **"Thông tin tài khoản"**, kéo xuống mục **"Bảo mật & cài đặt"**, bấm dòng **"Đổi mật khẩu"**.
4. Màn **"Đổi mật khẩu"** hiện ra, nhập **"Mật khẩu hiện tại"**, **"Mật khẩu mới"**, **"Xác nhận mật khẩu mới"**.
5. Bấm **"Cập nhật mật khẩu"**.
6. Thành công → thông báo **"Đổi mật khẩu thành công."**, quay lại màn trước.

**Ghi chú cho chatbot**: **không** có mục "Bảo mật" hay "Security" riêng trên tab Tài khoản — đường vào duy nhất là qua **Thông tin tài khoản**. Không hướng dẫn khách tìm một mục "Bảo mật" độc lập vì mục đó không có nút bấm tới trong giao diện thật (xem `ACC-09` phần liên quan).

---

### ACC-05. Đăng xuất 🟢

**Khi nào dùng**: "làm sao đăng xuất", "thoát tài khoản".

**Các bước**:
1. Vào tab **"Tài khoản"**, bấm icon **bánh răng (cài đặt)** ở góc trên bên phải.
2. Trong màn **"Cài đặt"**, kéo xuống cuối, bấm nút đỏ **"Đăng xuất"**.
3. Xuất hiện hộp thoại xác nhận **"Bạn có chắc muốn đăng xuất không?"** — bấm **"Đăng xuất"** để xác nhận, hoặc **"Hủy"** để huỷ bỏ.
4. Xác nhận → về **Trang chủ** ở chế độ khách.

---

### ACC-06. Xem/sửa thông tin cá nhân 🟢

**Khi nào dùng**: "đổi tên", "đổi ảnh đại diện", "sửa số điện thoại", "cập nhật thông tin cá nhân".

**Điều kiện tiên quyết**: đã đăng nhập.

**Các bước**:
1. Tab **"Tài khoản"** → bấm **"Thông tin tài khoản"**.
2. **Đổi ảnh đại diện**: bấm vào ảnh đại diện (có nhãn "Sửa") → chọn ảnh từ thư viện → tự động cập nhật.
3. **Sửa thông tin**: trong mục **"Thông tin cá nhân"**, bấm vào từng dòng để mở hộp thoại chỉnh sửa:
   - **"Họ và tên"** → hộp thoại "Cập nhật Họ và tên"
   - **"Số điện thoại"** → hộp thoại "Cập nhật Số điện thoại"
   - **"Địa chỉ"** → hộp thoại "Cập nhật Địa chỉ" (đây là địa chỉ text hiển thị trên hồ sơ, **khác** sổ địa chỉ giao hàng ở `ACC-07`)
4. Nhập giá trị mới, bấm **"Xác nhận"** (hoặc **"Hủy"** để bỏ qua).
5. Lưu thành công → thông báo cập nhật thành công.

**Ghi chú cho chatbot**: dòng **"Email"** trong Thông tin tài khoản chỉ hiển thị (đã ẩn một phần), **không sửa được** trực tiếp — nếu khách muốn đổi email đăng ký, đây là trường hợp cần escalate CSKH, không có tự phục vụ trong app.

---

### ACC-07. Quản lý sổ địa chỉ giao hàng 🟢

**Khi nào dùng**: "thêm địa chỉ giao hàng", "sửa địa chỉ nhận hàng", "xoá địa chỉ", "đặt địa chỉ mặc định".

**Điều kiện tiên quyết**: đã đăng nhập.

**Các bước**:
1. Tab **"Tài khoản"** → bấm mục **"Địa chỉ của tôi"** → vào màn **"Địa chỉ của tôi"** (danh sách toàn bộ địa chỉ đã lưu).
2. **Thêm mới**: bấm icon **"+"** hoặc nút **"Thêm địa chỉ mới"** → điền **Họ và tên người nhận, Số điện thoại**, chọn **Tỉnh/Huyện/Xã**, nhập **địa chỉ cụ thể (số nhà, tên đường)**, đặt nhãn (Nhà/Văn phòng...), bật/tắt **"Mặc định"** → bấm **"Lưu"**.
3. **Sửa**: trên mỗi thẻ địa chỉ, bấm **"Sửa"** → chỉnh thông tin → **"Lưu"**.
4. **Đặt mặc định**: bấm **"Đặt mặc định"** trên địa chỉ chưa mặc định.
5. **Xoá**: bấm **"Xóa"** trên thẻ địa chỉ → hộp thoại xác nhận **"Xóa địa chỉ?"** → bấm **"Xóa"** để xác nhận, **"Hủy"** để giữ lại.

**Ghi chú cho chatbot**: sửa/xoá địa chỉ trong sổ địa chỉ **không** tự động cập nhật địa chỉ giao của các đơn đã đặt trước đó (đơn dùng "ảnh chụp" địa chỉ tại thời điểm đặt hàng).

---

### ACC-08. Xoá tài khoản 🟡 (được xử lý qua trang web ngoài, không xoá ngay trong app)

**Khi nào dùng**: "làm sao xoá tài khoản", "tôi muốn xoá dữ liệu".

**Điều kiện tiên quyết**: đã đăng nhập.

**Các bước**:
1. Tab **"Tài khoản"** → cuối danh sách menu, bấm **"Xóa tài khoản"**.
2. Xuất hiện cảnh báo: *"Tài khoản của bạn sẽ bị xóa vĩnh viễn. Tất cả dữ liệu bao gồm điểm thưởng, voucher, lịch sử mua hàng sẽ không thể khôi phục. Các thông tin đơn hàng cũ vẫn được lưu trữ theo quy định của pháp luật. Bạn có chắc chắn muốn tiếp tục?"* — bấm **"Xóa tài khoản"** để tiếp tục, **"Hủy"** để dừng lại.
3. Nếu xác nhận, app mở **trình duyệt ngoài** tới trang `delippy.com/request-data-deletion` — người dùng phải hoàn tất yêu cầu **trên trang web đó**, việc xoá **không xảy ra ngay trong app**.

**Ghi chú cho chatbot**: luôn trả lời đúng rằng bước cuối cùng diễn ra trên **web**, không phải trong app, để khách không tưởng lầm là đã xoá xong ngay sau khi bấm nút trong app.

---

### ACC-09. Đăng nhập/liên kết mạng xã hội (Google) 🔴 không có trên giao diện

**Khi nào dùng**: "sao không đăng nhập được bằng Google/Facebook".

**Thực trạng**: nút đăng nhập Google **đã bị ẩn khỏi giao diện** (tồn tại ở tầng xử lý nhưng không có nút để bấm), và **không có** đăng nhập Facebook trong app.

**Chatbot nên trả lời**: hiện tại app chỉ hỗ trợ đăng nhập bằng email/số điện thoại + mật khẩu (`ACC-02`), không hướng dẫn khách tìm nút Google vì nút đó không hiển thị trên app hiện tại. Nếu khách khăng khăng nhớ từng dùng được, escalate CSKH để xác minh (có thể tài khoản cũ liên kết trước đây).

---

### ACC-10. Đăng ký bán hàng trên Delippy (Seller) 🟡 chỉ có thông báo, không có form

**Khi nào dùng**: "làm sao đăng ký bán hàng", "muốn mở shop trên Delippy".

**Các bước**:
1. Tab **"Tài khoản"** → bấm mục **"Bán hàng cùng Delippy"** (mục này **không hiện trên iOS**).
2. Với tài khoản chưa phải người bán: chỉ hiện hộp thoại thông báo **"Vui lòng liên hệ quản trị viên."** — **không có form đăng ký bán hàng ngay trong app**.

**Ghi chú cho chatbot**: đây là do chính sách App Store, không phải lỗi — trả lời khách cần **liên hệ CSKH/quản trị viên** trực tiếp để được hỗ trợ mở gian hàng.

---

## Nhóm B — Mua hàng, Giỏ hàng, Thanh toán

### SHOP-01. Mua hàng đầy đủ (xem sản phẩm → đặt hàng) 🟢

**Khi nào dùng**: "làm sao đặt hàng", "làm sao mua sản phẩm này".

**Các bước**:
1. Vào trang chi tiết sản phẩm, bấm **"Thêm vào giỏ hàng"** (để mua sau) hoặc **"Mua ngay"** (để đặt hàng ngay).
   - Nếu hết hàng, nút hiện **"Hết hàng"** và không bấm được.
   - Nếu chưa đăng nhập, app yêu cầu đăng nhập trước khi tiếp tục (`ACC-02`).
2. Chọn thuộc tính trong bảng hiện lên: **Màu sắc**, **Kích thước**, **Tùy chọn** khác (nếu có), chỉnh số lượng, rồi bấm nút xác nhận (label đổi theo đã chọn Thêm giỏ hay Mua ngay ở bước 1).
   - Nếu bấm "Mua ngay" → app **bỏ qua trang Giỏ hàng**, vào thẳng Checkout.
   - Nếu bấm "Thêm vào giỏ hàng" → hiện thông báo đã thêm, sản phẩm nằm trong Giỏ hàng để mua sau.
3. Vào **Giỏ hàng**: sản phẩm được nhóm theo từng shop. Tick chọn sản phẩm muốn mua (hoặc **"Chọn tất cả"**). Ở mỗi shop có thể áp voucher shop và dùng điểm DP (xem `SHOP-03`, `SHOP-04`). Bấm **"Thanh toán"** ở cuối trang (chỉ bấm được khi đã chọn hết các sản phẩm hiện có trong giỏ).
4. Vào màn **"Đặt hàng"** (Checkout):
   - Chọn **địa chỉ giao hàng** (hoặc thêm địa chỉ mới nếu chưa có — xem `ACC-07`). Nếu chưa chọn địa chỉ, app báo lỗi khi bấm đặt hàng.
   - Chọn **"Phương thức vận chuyển"**.
   - Chọn **"Phương thức thanh toán"**: **"Thanh toán khi nhận hàng"** (COD) hoặc **"Chuyển khoản (SePay)"**.
   - (Tuỳ chọn) ghi **"Ghi chú đơn hàng"**.
   - (Tuỳ chọn) áp **"Mã giảm giá toàn đơn"** và/hoặc mã giảm giá riêng từng shop (`SHOP-03`), dùng điểm DP (`SHOP-04`).
5. Bấm **"Đặt hàng"**.
   - Nếu chọn COD → chuyển thẳng tới trang **"Đặt hàng thành công"**.
   - Nếu chọn SePay → chuyển tới màn quét mã QR thanh toán (`SHOP-02`) trước.
6. Ở trang thành công, có 2 lựa chọn: **"Theo dõi đơn hàng"** (vào thẳng danh sách đơn, tab Đang xử lý) hoặc **"Tiếp tục mua sắm"** (về Trang chủ).

---

### SHOP-02. Thanh toán qua SePay (quét mã QR) 🟢

**Khi nào dùng**: "quét mã QR thế nào", "chuyển khoản xong mà chưa thấy cập nhật".

**Điều kiện tiên quyết**: đã chọn phương thức thanh toán **"Chuyển khoản (SePay)"** ở bước Checkout.

**Các bước**:
1. Sau khi bấm **"Đặt hàng"**, app chuyển tới màn quét mã QR: hiện **mã QR**, **số tiền cần chuyển**, **nội dung chuyển khoản** (có nút copy để dán vào app ngân hàng), và trạng thái **"Đang chờ thanh toán..."** kèm đồng hồ đếm ngược.
2. Khách mở app ngân hàng, quét mã QR (hoặc chuyển khoản đúng nội dung), hoàn tất chuyển khoản.
3. App **tự động kiểm tra** trạng thái thanh toán theo chu kỳ — không cần bấm gì thêm:
   - Nếu ghi nhận thanh toán thành công → tự chuyển sang trang **"Đặt hàng thành công"**.
   - Nếu hết hạn/thất bại → hiện hộp thoại với nút **"Xem chi tiết đơn hàng"** để vào trang chi tiết đơn kiểm tra.

**Ghi chú cho chatbot**: việc xác nhận thanh toán có độ trễ do đối soát ngân hàng — nếu khách báo "đã chuyển tiền nhưng vẫn thấy đang chờ", trước tiên trấn an chờ thêm vài phút, không vội kết luận lỗi hệ thống; nếu quá lâu, escalate kèm thông tin đơn để đối soát.

---

### SHOP-03. Áp dụng mã giảm giá (voucher sàn + voucher shop) 🟢

**Khi nào dùng**: "sao không dùng được mã giảm giá", "áp mã voucher ở đâu".

**Có 2 loại mã, dùng độc lập nhau**:
- **Mã giảm giá toàn sàn**: ở Giỏ hàng hoặc Checkout, tìm mục **"Mã giảm giá toàn đơn"** → nhập mã vào ô **"Nhập mã giảm giá..."** → bấm **"Áp dụng"**. Sau khi áp dụng, hiện dòng "Đã áp dụng {mã} — Giảm {số tiền}" kèm nút **"Xoá"** để gỡ mã.
- **Mã giảm giá riêng của shop**: mỗi nhóm sản phẩm theo shop có ô **"Mã shop / Chọn mã giảm giá"** → bấm mở danh sách mã khả dụng cho shop đó (hoặc chọn **"Không dùng mã"**) → chọn 1 mã, tự động áp dụng.

**Ghi chú cho chatbot**: nếu chưa đăng nhập mà bấm áp mã ở Giỏ hàng, app báo **"Bạn cần đăng nhập để áp dụng mã giảm giá"** — nhắc khách đăng nhập trước (`ACC-02`). Nếu mã báo lỗi dù khách chắc chắn còn hạn/đủ điều kiện, đây là trường hợp cần escalate để kiểm tra điều kiện mã cụ thể, chatbot không tự khẳng định lý do.

---

### SHOP-04. Sử dụng điểm thưởng DP khi thanh toán 🟢

**Khi nào dùng**: "dùng điểm DP thế nào", "điểm DP có hoàn lại không".

**Các bước**:
1. Ở Giỏ hàng hoặc Checkout, với sản phẩm cho phép dùng điểm, bấm dòng **"Dùng điểm DP"**.
2. Hộp thoại **"Sử dụng điểm DP"** hiện ra: số dư điểm hiện có, số điểm tối đa được dùng cho đơn này, các nút chọn nhanh (+100/+500/+1000/+5000 điểm) hoặc tự nhập số điểm, kèm số tiền được giảm tương ứng.
3. Bấm **"Xác nhận"** để áp dụng.

**Ghi chú cho chatbot — quy tắc quan trọng**: **điểm DP đã sử dụng cho một đơn sẽ KHÔNG được hoàn lại, kể cả khi đơn đó bị huỷ sau đó** (`ORD-03`). Đây là câu trả lời chuẩn phải nêu rõ mỗi khi khách hỏi về hoàn điểm DP sau huỷ đơn — tránh im lặng rồi phải xử lý khiếu nại.

---

## Nhóm C — Đơn hàng, Vận chuyển, Đổi trả, Đánh giá

### ORD-01. Xem danh sách đơn hàng theo trạng thái 🟢

**Khi nào dùng**: "đơn hàng của tôi đâu", "xem đơn đã đặt", "đơn nào đang giao".

**Điều kiện tiên quyết**: đã đăng nhập (nếu chưa, app yêu cầu đăng nhập trước).

**Các bước**:
1. Tab **"Tài khoản"** → mục **"Đơn hàng của tôi"**.
2. Có 2 cách xem:
   - Bấm **"Xem tất cả"** → vào danh sách đơn (mặc định ở tab đầu).
   - Hoặc bấm thẳng 1 trong 5 icon trạng thái để lọc ngay: **"Chờ xác nhận"**, **"Đang xử lý"**, **"Chờ giao hàng"**, **"Hoàn thành"**, **"Đã hủy"**.
3. Trong màn danh sách, có thanh tab để chuyển qua lại giữa 5 trạng thái trên. Mỗi đơn hiển thị dưới dạng thẻ, có nút **"Xem chi tiết"** (→ `ORD-02`), và nếu đơn đang **"Chờ xác nhận"** thì có thêm nút **"Hủy"** ngay tại đây (→ `ORD-03`).

**Ghi chú cho chatbot**: nút tìm kiếm trên màn danh sách đơn hiện chỉ hiện thông báo **"Sắp ra mắt"** — chưa tìm kiếm được theo tên sản phẩm/mã đơn tại đây; icon "hỗ trợ" trên mỗi thẻ đơn cũng chỉ hiện email tĩnh `support@delippy.app`, không phải kênh chat thật.

---

### ORD-02. Xem chi tiết đơn hàng 🟢

**Khi nào dùng**: "kiểm tra đơn hàng DLPxxxx", "tình trạng đơn ra sao".

**Các bước**:
1. Từ `ORD-01`, bấm **"Xem chi tiết"** trên đơn cần xem → vào màn **"Chi tiết đơn hàng"**.
2. Màn hiển thị: trạng thái đơn, mã đơn (bấm để copy), ngày đặt, **thanh tiến trình ngang** gồm 4 mốc (Chờ xác nhận → Đang xử lý → Đang giao → Hoàn tất — ẩn hoàn toàn nếu đơn đã huỷ), thông tin giao hàng, danh sách sản phẩm, và tổng kết tiền (tạm tính, giảm giá shop, giảm giá sàn, điểm DP đã dùng, phí vận chuyển, tổng tiền).
3. Các nút hành động ở cuối trang, **tuỳ theo trạng thái đơn**:
   - **"Hủy đơn"** — chỉ hiện khi đơn đang **"Chờ xác nhận"** hoặc **"Đang xử lý"** (→ `ORD-03`).
   - **"Liên hệ shop"** — luôn hiện nhưng hiện chưa hoạt động thật (→ `ORD-05`).
   - Với mỗi sản phẩm, nếu đơn đã **"Hoàn thành"** và sản phẩm đó chưa đánh giá → nút **"Đánh giá"** (→ `ORD-07`); nếu đã đánh giá thì chỉ hiện chữ "Đã đánh giá".

---

### ORD-03. Huỷ đơn hàng 🟢 (có điều kiện trạng thái)

**Khi nào dùng**: "huỷ đơn", "tôi muốn huỷ đơn hàng", "đặt nhầm muốn huỷ".

**Điều kiện tiên quyết — QUAN TRỌNG, cần kiểm tra đúng trạng thái đơn trước khi trả lời**:
- Ở màn **danh sách đơn**, nút Hủy chỉ hiện khi đơn đang **"Chờ xác nhận"**.
- Ở màn **chi tiết đơn**, nút Hủy hiện khi đơn đang **"Chờ xác nhận"** *hoặc* **"Đang xử lý"** (phạm vi rộng hơn ở danh sách).
- Khi đơn đã **"Chờ giao hàng"/"Đang giao"** trở đi, hoặc đã **"Hoàn thành"**, hoặc đã **"Đã hủy"** → không thể huỷ qua app nữa.

**Các bước**:
1. Vào chi tiết đơn (`ORD-02`) hoặc danh sách đơn (`ORD-01`), bấm **"Hủy đơn"**.
2. Hộp thoại xác nhận hiện ra: *"Bạn có chắc chắn muốn huỷ đơn hàng này không?"* — bấm **"Xác nhận"** để huỷ, **"Đóng"** để giữ nguyên.
3. Huỷ thành công → thông báo **"Hủy đơn hàng thành công."**.

**Ghi chú cho chatbot**:
- **Không có bước chọn lý do huỷ** — quy trình chỉ có 1 bước xác nhận, không hỏi lý do.
- Nếu đơn đã sang trạng thái không cho huỷ mà khách vẫn muốn huỷ, giải thích rõ lý do và chuyển hướng: đơn đang giao → chờ nhận rồi xử lý theo `ORD-06`/escalate; hướng dẫn **không được** hứa hẹn huỷ giúp qua chatbot.
- Nhắc kèm quy tắc điểm DP không hoàn lại nếu đơn có dùng điểm (`SHOP-04`).

---

### ORD-04. Theo dõi vận chuyển 🟢

**Khi nào dùng**: "hàng tôi tới đâu rồi", "bao giờ giao hàng".

**Các bước**:
1. Vào **Chi tiết đơn hàng** (`ORD-02`).
2. Xem **thanh tiến trình ngang** ở đầu trang — đây chính là nơi hiển thị tiến độ vận chuyển: Chờ xác nhận → Đang xử lý → Đang giao → Hoàn tất.

**Ghi chú cho chatbot**: app **không có** một trang "tra cứu vận đơn" riêng biệt hay timeline chi tiết theo từng mốc thời gian/địa điểm của đơn vị vận chuyển — toàn bộ thông tin tiến độ chỉ gói gọn trong 4 mốc ở trang chi tiết đơn. Không hứa hẹn cung cấp thông tin "vị trí shipper hiện tại" hay mốc tracking chi tiết hơn vì hệ thống hiện chưa có. Trong chatbot mode CSKH cũng có nút riêng **"Theo dõi đơn hàng"** để chọn nhanh 1 đơn rồi hỏi bot ngay trong khung chat (xem `BOT-01`), nhưng đây chỉ là lối tắt để hỏi bot, không mở ra thêm thông tin gì khác ngoài trang chi tiết đơn.

---

### ORD-05. Liên hệ shop về đơn hàng 🟡 chưa hoạt động thật

**Khi nào dùng**: "làm sao nhắn tin cho shop", "liên hệ người bán".

**Thực trạng**: nút **"Liên hệ shop"** luôn hiện trong Chi tiết đơn hàng (`ORD-02`), nhưng bấm vào **chỉ hiện thông báo "Sắp ra mắt"** — chưa có kênh chat/liên hệ shop thật trong app.

**Chatbot nên trả lời**: hiện app chưa hỗ trợ nhắn tin trực tiếp với shop; nếu khách cần liên hệ shop, hướng dẫn qua kênh hỗ trợ chung (email `support@delippy.app` hiển thị trên thẻ đơn, hoặc escalate CSKH) thay vì chỉ nói "bấm nút Liên hệ shop".

---

### ORD-06. Yêu cầu đổi trả sản phẩm 🔴 không có điểm vào trong app

**Khi nào dùng**: "trả hàng", "đổi hàng", "hàng lỗi muốn trả lại".

**Thực trạng quan trọng**: màn hình yêu cầu đổi trả **đã được lập trình sẵn** (chọn sản phẩm cần trả, chọn lý do trong 4 nhóm: sản phẩm lỗi/hỏng, giao sai sản phẩm, không đúng mô tả, khác — kèm ô nhập mô tả nếu chọn "khác"), nhưng **không có bất kỳ nút hay mục menu nào trong app dẫn tới màn này** — người dùng không có cách nào tự mở được màn đổi trả từ giao diện hiện tại. Ngoài ra mục đính kèm ảnh minh chứng trên màn này cũng mới chỉ là placeholder ("Tính năng đính kèm ảnh sẽ được bổ sung sau"), chưa upload ảnh thật được.

**Chatbot nên trả lời**: **tuyệt đối không hướng dẫn** "vào đơn hàng, bấm yêu cầu đổi trả..." vì nút đó không tồn tại trên app hiện tại — sẽ khiến khách loay hoay tìm không thấy. Thay vào đó:
1. Xin lỗi vì app hiện chưa hỗ trợ tự thao tác đổi trả.
2. Thu thập thông tin: mã đơn hàng, sản phẩm cần đổi trả, lý do (theo 4 nhóm ở trên), mô tả/ảnh nếu khách gửi được qua kênh khác.
3. Escalate/chuyển thông tin cho bộ phận CSKH xử lý thủ công.

---

### ORD-07. Đánh giá sản phẩm sau khi nhận hàng 🟢

**Khi nào dùng**: "đánh giá sản phẩm ở đâu", "làm sao review đơn đã nhận".

**Điều kiện tiên quyết**: đơn đã ở trạng thái **"Hoàn thành"**, sản phẩm đó chưa được đánh giá trước đó.

**Các bước**:
1. Vào **Chi tiết đơn hàng** (`ORD-02`), tìm sản phẩm cần đánh giá, bấm nút **"Đánh giá"**.
2. Vào màn **"Viết đánh giá"**: chọn **1–5 sao** ("Bạn cảm thấy sản phẩm thế nào?"), (tuỳ chọn) viết nhận xét chi tiết, (tuỳ chọn) thêm tối đa **1 ảnh** (dưới 5MB) qua chụp ảnh hoặc chọn từ thư viện.
3. Bấm **"Gửi đánh giá"** (chỉ bấm được sau khi đã chọn số sao).
4. Thành công → thông báo **"Đánh giá thành công!"**, quay lại đơn hàng, sản phẩm chuyển sang trạng thái "Đã đánh giá".

---

## Nhóm D — Chatbot

### BOT-01. Truy cập chatbot & chuyển đổi mode Tư vấn/CSKH 🟢 (một phần nút quick-action chưa hoạt động)

**Khi nào dùng**: câu hỏi meta về chính chatbot ("chatbot dùng sao", "sao không tìm thấy nút hỗ trợ").

**Các bước**:
1. Icon chatbot hình nổi (kéo-thả được) chỉ hiện trên 3 màn: **Trang chủ**, **Tìm kiếm**, **Kết quả tìm kiếm** — ẩn ở các màn khác, và ẩn hoàn toàn nếu app đang ở chế độ Người bán.
2. Bấm icon → mở khung chat.
3. Bấm nút **"..."** trong khung chat để chuyển đổi giữa 2 chế độ:
   - **"Tư vấn mua sắm"** — trợ lý AI gợi ý/tìm sản phẩm.
   - **"Chăm sóc khách hàng"** — hỗ trợ CSKH (đơn hàng, thanh toán...).
4. Ở chế độ **"Chăm sóc khách hàng"** khi đã đăng nhập, phía trên ô nhập tin nhắn có thêm nút **"Theo dõi đơn hàng"** — bấm vào để chọn nhanh 1 đơn, hệ thống tự điền câu hỏi vào khung chat để bot trả lời.
5. Màn chào có 4 gợi ý nhanh, nhưng chỉ **"Tìm sản phẩm"** hoạt động thật; **"So sánh giá"**, **"Theo dõi đơn"**, **"Hỗ trợ 24/7"** hiện chỉ hiện thông báo "tính năng đang phát triển".
6. Nếu bot yêu cầu đăng nhập để trả lời, app tự hiện hộp thoại **"Yêu cầu đăng nhập"** với nút **"Đăng nhập"** đưa thẳng tới màn đăng nhập (`ACC-02`).

---

## Ghi chú vận hành khi chuyển các luồng trên thành JSON cho hệ thống tra cứu

- Mỗi mã luồng (`ACC-xx`, `SHOP-xx`, `ORD-xx`, `BOT-xx`) nên là 1 bản ghi độc lập, khoá bằng đúng mã này, để chatbot map từ intent/keyword sang đúng luồng.
- Với các luồng đánh dấu 🔴 (`ACC-09`, `ORD-06`), bản ghi JSON cần có cờ rõ ràng kiểu "không hướng dẫn thao tác trong app" để chatbot luôn rẽ sang câu trả lời thay thế/escalate thay vì cố mô tả bước không tồn tại.
- Với các luồng đánh dấu 🟡, bản ghi JSON nên tách riêng phần "câu trả lời khi tính năng chưa khả dụng" khỏi phần "bước thao tác trên UI" để chatbot ưu tiên nói rõ giới hạn trước khi mô tả (nếu có) phần giao diện đã tồn tại.
- Khi có thay đổi giao diện (thêm nút mới, đổi label, mở API đổi trả thật...), cần cập nhật lại đúng mã luồng tương ứng trong tài liệu này trước, rồi mới sinh lại JSON — tránh sửa JSON tay mà quên đồng bộ ngược lại tài liệu gốc.
