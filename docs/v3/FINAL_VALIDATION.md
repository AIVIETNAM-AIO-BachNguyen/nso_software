> Cập nhật 28/10/2026: phần manufacturing và V3.1 được mở rộng sau báo cáo này; xem [báo cáo mới](V3_MANUFACTURING_V31_COMPLETION_2026-10-28.md).

# Kiểm chứng cuối — 26/10/2026

Phạm vi: mã local trên macOS, Python **3.12.16** trong `.venv312`, PostgreSQL 16 riêng, Node **26.5.0**, Next.js **15.5.28**. Không có dữ liệu bệnh nhân thật trong fixture và staging của lần kiểm tra này.

| Kiểm tra | Kết quả | Bằng chứng |
|---|---|---|
| Toàn bộ pytest backend, bật PostgreSQL | **563 passed, 1 skipped**, 71.44 giây | [Log](backend-test-results.txt) |
| Statement coverage package `nso` | **93.39%**, 3605/3860 câu lệnh | Coverage trong log pytest; không bao gồm toàn bộ các file API ngoài package |
| React component tests | **8 passed**, không fail/skip | `npm test` tại `src/frontend`; test source trong `tests/research-ui.test.cjs` |
| Frontend production build | **PASS** | [Log build](frontend-build-results.txt) |
| npm dependency audit | **0 advisory** tại thời điểm kiểm tra | [JSON audit](frontend-dependency-audit.json) |
| HTTP staging production mode | **24 bước PASS** | [JSON HTTP](staging-http-verification.json) |
| Frontend `/` và `/research` | **200**, mỗi trang 7 asset trả 200 | [JSON frontend HTTP](frontend-http-verification.json) |
| Clinical black-box check | **PASS**, 10 response, 3 bundle, 3 trang PDF, không phát hiện storage API/thuật ngữ thiết kế bị cấm trong phạm vi scanner | [JSON black-box](black-box-verification.json) |
| Ruff checks nhóm F, bỏ E402 cho script cần điều chỉnh import path | **PASS** | Lệnh bên dưới |
| Whitespace diff | **PASS** | `git diff --check` |

Bài test bỏ qua duy nhất là kiểm tra biến thiên chiều cao phần tử V2 ở `test_nso_package.py:673`, có điều kiện threshold chưa vượt trong fixture. Có một DeprecationWarning từ alias BlockingPortal của Starlette/AnyIO; không có test thất bại.

HTTP staging thử xác thực, readiness, randomized/observational demo, optical demo, trained-model demo, khóa policy, training, independent review, deploy, prediction, outcome, optimizer job, chặn approval thiếu measured calibration, operations và chặn phục vụ sau khi rút duyệt. Mã trạng thái 401/409 ở bước kiểm tra từ chối là kết quả mong đợi, không phải lỗi bị bỏ qua. Access code không được lưu vào báo cáo/source.

Tám component tests kiểm tra: payload demo không gửi dữ liệu bệnh nhân; hủy/bỏ kết quả request cũ; hiển thị lỗi và cho thử lại; import bị ràng buộc bởi case/mắt đã chọn; correction giữ revision/provenance; ẩn chức năng không thuộc vai trò; file training không ghi đè locked policy; engineering view chỉ hiển thị field được phép. Đây là kiểm thử component bằng React test renderer, không phải trình duyệt.

## Lệnh tái hiện

Từ repository root, với PostgreSQL **chỉ dùng kiểm thử** đang chạy:

```sh
OMP_NUM_THREADS=1 NSO_TEST_POSTGRES_URL='postgresql:///postgres?host=/private/tmp/nso-v3-pg-socket&port=55432' \
  .venv312/bin/python -m pytest -q -rs src/backend \
  --cov=src/backend/nso --cov-report=term-missing:skip-covered
.venv312/bin/ruff check --isolated --select F --ignore E402 \
  src/backend/nso/research*.py src/backend/research*.py \
  src/backend/test_v3*.py src/backend/scripts/v3*.py
git diff --check
cd src/frontend
npm ci
npm audit
npm test
npm run build
cd ../backend
OMP_NUM_THREADS=1 ../../.venv312/bin/python verify_black_box.py
```

`npm ci` dùng lockfile với overrides PostCSS 8.5.31, nanoid 3.3.18 và source-map-js 1.2.2. Next.js 15.5.28 là bản vá nhánh 15 theo [thông báo chính thức](https://nextjs.org/blog/nextjs-security-update-october-14-2026). Audit chỉ phản ánh các advisory được registry công bố lúc chạy, không phải bằng chứng phần mềm không có lỗ hổng.

## Chưa được kiểm chứng trong lần này

- Công cụ trình duyệt bị tắt trong Work settings: chưa có interactive browser/mobile/accessibility QA cho giao diện mới. HTTP và component tests không thay thế phần này.
- GitHub-hosted CI chưa chạy; cấu hình frontend runner dùng Node 24 LTS theo [lịch hỗ trợ Node.js](https://nodejs.org/en/about/previous-releases). Chưa kiểm tra kết quả trên runner đó.
- Docker daemon không khả dụng: chưa build/run container. Chưa cloud deployment, TLS/identity provider, proxy streaming limit hoặc cloud backup/restore rehearsal.
- Chưa có external validation trên số đo thật, phê duyệt khoa học/clinical độc lập hoặc hiệu chuẩn với kính và QC thật. Simulator là scalar reference; không phải bộ mô phỏng quang học đầy đủ đã được xác nhận. Adaptive V3.1 và ITE/CATE chưa khả dụng.

Xem [báo cáo 1–7](COMPLETION_2026-10-26.md) để phân biệt phần đã triển khai với các giới hạn khoa học và vận hành.
