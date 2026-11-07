# US00 - Task 4: Kết quả spike Flet Web

- Python: 3.13.15
- Flet: 1.0.5
- flet-charts: 1.0.5
- Matplotlib: phiên bản kiểm tra được trong môi trường thực tế
- Môi trường: Windows + PyCharm, Web

| Thử nghiệm | Cách thực hiện | Kết quả quan sát | Đạt/Chưa đạt |
| --- | --- | --- | --- |
| Mở website | `flet run --web spikes/flet_web_spike.py` | | |
| Chuyển route | Bấm Form rồi quay lại Trang chủ | | |
| Form validation | Bấm Lưu khi chưa nhập tên | | |
| Session trong cùng tab | Nhập tên rồi lưu và mở trang Session | | |
| F5 | Lưu tên, nhấn F5 tại trang Session | | |
| Tab mới | Sao chép URL vào tab mới | | |
| Back/Forward | Sử dụng nút quay lại/tiến tới của trình duyệt | | |
| Deep link | Mở trực tiếp `/form` và `/session` trên trình duyệt | | |
| MatplotlibChart | `flet run --web spikes/matplotlib_spike.py` | | |
| Console/Terminal | Không có exception hoặc thiếu API | | |

**Chú ý:** Ghi nhận kết quả F5/tab mới đúng thực tế; P1 không yêu cầu giữ đăng nhập sau F5 hoặc đồng bộ các tab. Thử nghiệm này không phải xác thực người dùng thật.
