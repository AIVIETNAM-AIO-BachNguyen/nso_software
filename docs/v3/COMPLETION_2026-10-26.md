> Cập nhật 28/10/2026: phần manufacturing và V3.1 được mở rộng sau báo cáo này; xem [báo cáo mới](V3_MANUFACTURING_V31_COMPLETION_2026-10-28.md).

# Kết quả triển khai các mục 1 đến 7

Ngày cập nhật: 26 tháng 10 năm 2026. Đây là báo cáo kỹ thuật hiện hành; các báo cáo ngày 23 tháng 10 được giữ làm lịch sử. Phần mềm nghiên cứu đã được mở rộng và kiểm thử trên Python 3.12.16. Không có kết luận về hiệu quả lâm sàng hoặc tính phù hợp của một thiết kế kính thật.

## Những phần đã triển khai

| Mục | Kết quả kỹ thuật có thể chạy | Giới hạn cần giữ rõ |
|---|---|---|
| 1 Dữ liệu nghiên cứu | Import quan sát theo mắt, kiểm tra cả batch trước ghi, sửa sai bằng revision mới với optimistic concurrency; giao dịch SQL bao gồm bản ghi, audit và receipt; lịch sử can thiệp được khóa khi kiểm tra trùng; protocol bất biến, enrollment/eligibility, allocation reference, biến cố bất lợi, mất theo dõi và giải quyết biến cố bằng bản ghi riêng | Nội dung đề cương, tính chính xác nguồn đo và quyền sử dụng dữ liệu cần người phụ trách nghiên cứu xác nhận |
| 2 NPM | Hai baseline; mô hình mixed-effects có hiệu ứng tuổi, thời gian và tương tác; gradient boosting; Transformer thời gian nhỏ có thể huấn luyện; tách bệnh nhân giữa train/calibration/test và external-site; kiểm tra temporal leakage và số đo không nhất quán; khoảng dự báo từ residual trên bệnh nhân calibration; báo cáo MAE/RMSE/bias/coverage theo split, tuổi, giới và site; artifact JSON, hash nguồn và môi trường; mô hình không được phục vụ trước duyệt/triển khai | Transformer là prototype độc lập, không phải MPPM của bài báo. Mẫu tổng hợp không chứng minh năng lực trên bệnh nhân. Khoảng dự báo phụ thuộc giả định exchangeability. Phải huấn luyện/xác thực trên dữ liệu được phép và phù hợp |
| 3 IPM | Cohort gắn protocol; ANCOVA với sai số HC3 cấp bệnh nhân cho randomized; AIPW với propensity/outcome nuisance cross-fitting cho observational; chẩn đoán overlap, effective sample size, SMD trước/sau weighting; chặn ước lượng khi thiếu support; bootstrap cấp bệnh nhân; phân tích giả định nhiễu chưa đo và kịch bản outcome của bệnh nhân mất theo dõi | Không có ITE/CATE. Assignment reference không tự chứng minh randomization. Complete-case và partial-eye missingness vẫn cần đánh giá khoa học; không tự coi kết quả là hiệu quả nhân quả đã xác nhận |
| 4 Tối ưu quang học | Simulator scalar Fraunhofer bằng phase screen, PSF/OTF/MTF và Strehl; envelope, đơn vị/range và giới hạn độ phân giải; phân bố điểm có exclusion spacing và lớp fiber; evolutionary multiobjective search với seed; Pareto; kiểm tra decentration, rotation, thay đổi pupil và sai số chiều cao; tham số candidate giữ trong kho server, API chỉ trả ID/metric cho phép; workflow kiểm tra measured calibration/verification và reviewer độc lập | Đây là simulator tham chiếu một bước sóng với giả định giản lược. Chưa có xác thực NSO lens/material/process thật, ray tracing đầy đủ, chromatic/polarization/tissue modeling hoặc hiệu quả lâm sàng. Synthetic calibration bị chặn khỏi measured-evidence gate |
| 5 Phê duyệt | Acceptance policy bất biến gắn trước training; author/reviewer/deployer tách nhau; review decision có sequence; deploy và rollback bất biến, sắp đúng thứ tự trên SQL; rút duyệt chặn phục vụ tiếp; Transformer phải cải thiện so với comparator; gate thiết kế kiểm tra envelope/calibration hiện hành và biến cố nặng chưa giải quyết | Chỉ triển khai nghiên cứu. Không tạo lệnh manufacturing hoặc đơn điều trị V3. Không tự cấp chấp thuận chuyên môn/pháp lý |
| 6 Giao diện | Demo forecast, study randomized/observational, optical search và bảng training kết quả tổng hợp; session có expiration và idle timeout; clinical page dùng assigned patient; import/correction, protocol/enrollment/event, cohort/adjusted report, model validation/review/deploy/rollback và engineering JSON upload/review | Production build và 8 kiểm thử component đã qua; công cụ trình duyệt hiện bị tắt trong Work settings, nên phiên bản giao diện mới chưa được kiểm thử tương tác trực tiếp hoặc kiểm tra mobile/screen-reader. Các API được thử qua HTTP thật và fixture riêng |
| 7 Vận hành | Python 3.12.16 riêng và dependency lock; PostgreSQL 16 riêng cho kiểm thử; transaction guard, training job leases và recovery worker; bảo vệ legacy API production theo vai trò/patient scope; CORS chính xác; credential hết hạn; no-store; request-size/rate controls; readiness và counters; backup logical checksum, restore vào target rỗng; Next.js nâng lên 15.5.28, transitive dependencies được vá và npm audit không còn advisory; Docker/CI cấu hình và local production-mode staging | Chưa chạy GitHub-hosted CI hoặc triển khai cloud. Docker daemon không chạy nên image chưa được build/test. Cần reverse proxy với giới hạn streaming body/rate phân tán, secret manager/identity provider, TLS, backup mã hóa và cloud restore rehearsal trước production thật |

## Môi trường Python

`.python-version` pin 3.12.16. Mã nguồn Python được tải từ python.org và kiểm tra SHA-256 trước khi build vào `.runtime/python-3.12.16`; môi trường ứng dụng là `.venv312`. Môi trường `.venv` Python 3.9 cũ được giữ để đối chiếu và không dùng cho kết quả kiểm thử mới. Interpreter kiểm tra được SSL, SQLite, bz2, lzma và ctypes; các module desktop tùy chọn gdbm/Tk không cần cho backend này.

Các thư viện ML và database nằm trong `requirements-research.txt`; phiên bản đã cài được khóa trong `requirements-research.lock.txt`. FastAPI được giữ ở nhánh 0.128 để tránh đổi hành vi router trong cùng lần di chuyển Python. Đây là quyết định tương thích có kiểm thử, không phải chứng nhận an toàn của mọi dependency.

## Cách chạy lại

Từ thư mục repository:

```sh
source .venv312/bin/activate
OMP_NUM_THREADS=1 .venv312/bin/python -m pytest -q -rs src/backend
OMP_NUM_THREADS=1 .venv312/bin/python src/backend/scripts/v3_training_demo.py
.venv312/bin/python src/backend/scripts/v3_inventory.py > docs/v3/inventory.json
.venv312/bin/python src/backend/scripts/v3_openapi.py > docs/v3/openapi.json
```

Để chạy toàn bộ PostgreSQL tests, đặt `NSO_TEST_POSTGRES_URL` đến **database riêng chỉ dùng kiểm thử**; tests tạo schema riêng và dọn chính schema đó sau khi hoàn thành. Không dùng URL production. Trên máy này PostgreSQL kiểm thử dùng Unix socket `/private/tmp/nso-v3-pg-socket`, port 55432. Test restore có cả nguồn và đích PostgreSQL, kiểm tra checksum tương đương sau phục hồi, và từ chối backup bị sửa/target không rỗng.

Frontend: `npm test` và `npm audit`, sau đó `npm run build` rồi `npm run start -- --hostname 127.0.0.1 --port 3000` tại `src/frontend`. Build có thể báo không tải được stylesheet Google Fonts dưới chính sách mạng hiện tại; ứng dụng có fallback font và build vẫn thành công.

### Local staging chỉ chứa dữ liệu tổng hợp

```sh
OMP_NUM_THREADS=1 .venv312/bin/python src/backend/scripts/v3_local_staging.py \
  --database-url 'postgresql:///nso_staging_synthetic?host=/private/tmp/nso-v3-pg-socket&port=55432'
```

Launcher chỉ lắng nghe 127.0.0.1:8000, chạy production mode, từ chối database có patient ID không thuộc fixture tổng hợp, tạo session tám giờ với ba vai trò riêng. Access code và file import được ghi quyền 0600 trong thư mục tạm 0700; chúng không nằm trong source hay báo cáo. CORS chỉ cho hai địa chỉ localhost frontend. Có thể chạy `v3_staging_smoke.py <thư-mục-tạm>` để kiểm tra HTTP thật. Script không in credential và từ chối URL ngoài loopback. Môi trường này kiểm tra hành vi production, không phải bản đã đưa lên hosting thật.

### Worker và backup

- `scripts/v3_training_worker.py` khôi phục job chưa xong với lease tránh chạy trùng. Job lỗi không tự promote model.
- `scripts/v3_optimizer_worker.py` khôi phục optical job; envelope chưa đăng ký sẽ bị chặn.
- `scripts/v3_backup.py backup <file.backup.json>` và `restore` dùng `NSO_DATABASE_URL`. Dừng/quiesce các writer khi backup để bao quát cả V2. Bản backup chứa dữ liệu nhạy cảm, cần mã hóa và kiểm soát lưu trữ khi dùng với dữ liệu thật. File đích không được ghi đè; restore yêu cầu target rỗng.
- `/api/v3/ready` và `/api/v3/operations` có xác thực; operations không trả số đo hay thiết kế. Khi production dùng in-memory store, health trả 503.

## Điều còn phải xác nhận ngoài phần mềm

Chưa thể xác nhận clinical performance, khả năng khái quát trên dữ liệu NSO, hiệu chuẩn simulator theo vật liệu/kính thật, dung sai sản xuất thật, IRB/consent và independent clinical/QA review. Không có model trained hoặc measured calibration thật được tạo ra trong lần làm này. Các mô hình từ fixture bị giới hạn phục vụ cho case có nhãn synthetic; cờ `clinical_use_allowed` luôn false.

V3.1 adaptive clinical ranking không thuộc đợt 1–7 này và vẫn không khả dụng. Chưa push mã lên GitHub, chưa chạy workflow trên runner từ xa, chưa thay đổi production hosting và chưa gửi thư cho thầy. Triển khai cloud cần xem cấu hình/tài khoản thực tế, provision authentication/database và chạy staging/restore/security review ở chính môi trường đó.

## Nguồn kỹ thuật được đối chiếu

- [Python 3.12.16 release và checksum](https://www.python.org/downloads/release/python-31216/).
- [statsmodels MixedLM implementation](https://www.statsmodels.org/stable/_modules/statsmodels/regression/mixed_linear_model.html).
- [POPPY physical optics overview](https://poppy-optics.readthedocs.io/en/latest/) và [HCIPy Fraunhofer propagation](https://docs.hcipy.org/dev/api/hcipy.propagation.FraunhoferPropagator.html), dùng làm tham chiếu phương pháp; không sao chép mã hay tuyên bố tái hiện đầy đủ các thư viện đó.
- [Next.js security update 14 October 2026](https://nextjs.org/blog/nextjs-security-update-october-14-2026).
- [Node.js release support](https://nodejs.org/en/about/previous-releases): CI cấu hình Node 24 LTS; lần build local dùng Node 26.5.0, chưa chạy runner Node 24.
- [PyTorch official CPU wheels](https://download.pytorch.org/whl/cpu/torch/), dành cho cấu hình CI/container.

Kết quả cuối cùng và các lệnh kiểm thử được lưu trong `FINAL_VALIDATION.md`; báo cáo HTTP, black-box và OpenAPI là các artifact đi kèm.
