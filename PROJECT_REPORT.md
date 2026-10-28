# NSO AI-PC Fitting Platform — Báo cáo dự án

**Phiên bản:** V2.1 · **Cập nhật:** 28/08/2026 · **Trạng thái:** Đang chạy production

---

## Mục lục

1. [Tóm tắt cho lãnh đạo](#1-tóm-tắt-cho-lãnh-đạo)
2. [Bối cảnh và mục tiêu](#2-bối-cảnh-và-mục-tiêu)
3. [Kiến trúc hệ thống](#3-kiến-trúc-hệ-thống)
4. [Bảo vệ tài sản trí tuệ](#4-bảo-vệ-tài-sản-trí-tuệ)
5. [Những gì đã hoàn thành](#5-những-gì-đã-hoàn-thành)
6. [Sẵn sàng cho Machine Learning](#6-sẵn-sàng-cho-machine-learning)
7. [Kiểm thử và chất lượng](#7-kiểm-thử-và-chất-lượng)
8. [Triển khai](#8-triển-khai)
9. [Rủi ro và giới hạn](#9-rủi-ro-và-giới-hạn)
10. [Việc còn lại](#10-việc-còn-lại)
11. [Lộ trình đề xuất](#11-lộ-trình-đề-xuất)
12. [Phụ lục](#12-phụ-lục)

---

## 1. Tóm tắt cho lãnh đạo

### Dự án là gì

Nền tảng phần mềm biến **kết quả đo thị giác của bệnh nhân** thành **thiết kế tròng
kính kiểm soát cận thị cá nhân hoá**, rồi thành **file hình học gửi nhà máy gia
công** — đồng thời giữ cho công thức thiết kế không bao giờ rời khỏi máy chủ.

### Trạng thái hiện tại

| | |
|---|---|
| Phần mềm | ✅ Hoàn thiện, đang chạy production |
| Mô hình quang học | ⚠️ **Chưa hiệu chỉnh** — theo đánh giá của cố vấn khoa học là "khoảng V0.5" |
| Bảo vệ IP | ✅ Hoạt động, có kiểm chứng tự động |
| Sẵn sàng cho ML | ✅ Hạ tầng xong, chờ dữ liệu |

### Điều quan trọng nhất lãnh đạo cần biết

Hệ thống **nhìn hoàn chỉnh** và chạy đúng về mặt kỹ thuật, nhưng **các hệ số bên
trong phần lớn chưa được hiệu chỉnh bằng dữ liệu thật**. Mọi kết quả hiện tại đều
mang nhãn "concept estimate, not clinically validated".

Đây không phải thiếu sót kỹ thuật mà là **giai đoạn tự nhiên của dự án**: phần mềm
đã sẵn sàng nhận dữ liệu, dữ liệu thì phần lớn **chưa tồn tại** — cần đo trên bench
và theo dõi bệnh nhân mới có.

**Nút thắt đã chuyển từ kỹ thuật phần mềm sang thu thập dữ liệu vật lý và lâm sàng.**

### Con số

| Chỉ số | Giá trị |
|---|---|
| Tổng dòng code | 9.903 |
| Engine (Python) | 4.795 dòng, 22 module |
| Test tự động | **441 test**, 100% pass |
| Giao diện (Next.js) | 1.215 dòng |
| Tham số cấu hình | 109 |
| Ô nhập liệu lâm sàng | 61 trường, 3 tầng |
| Endpoint API | 9 |
| Tài liệu | 3 file (~2.000 dòng) |

---

## 2. Bối cảnh và mục tiêu

### Vấn đề kinh doanh

Kính kiểm soát cận thị (DIMS, HAL, MiSight…) hiện là sản phẩm **một cỡ cho tất cả**.
NSO hướng tới **cá nhân hoá theo hồ sơ thị giác đa chiều** của từng bệnh nhân.

Bài toán phần mềm gồm ba phần:

1. **Đo lường → thiết kế.** Biến hàng chục chỉ số lâm sàng thành thông số quang học.
2. **Thiết kế → sản xuất.** Biến thông số quang học thành hình học gia công được.
3. **Bảo vệ know-how.** Không để công thức thiết kế lọt ra ngoài.

### Vì sao phần 3 quan trọng ngang phần 1 và 2

Bằng sáng chế bảo vệ được **phương pháp và hệ thống**, nhưng phải công khai. Còn
**hệ số cụ thể** — thứ làm sản phẩm chạy được — chỉ được bảo vệ dưới dạng **bí mật
kinh doanh**, và bí mật kinh doanh mất hiệu lực ngay khi lộ ra.

Về mặt pháp lý, bí mật kinh doanh chỉ được bảo hộ nếu chủ sở hữu **có biện pháp bảo
vệ hợp lý**. Nếu API công khai trả về thông số thiết kế, toà sẽ coi đó không còn là
bí mật — và mất luôn quyền khởi kiện.

Vì vậy kiến trúc bảo vệ IP vừa là yêu cầu kỹ thuật, vừa là **bằng chứng pháp lý**.

### Mô hình kinh doanh mà kiến trúc này cho phép

| | Nếu bán sản phẩm | Với kiến trúc hiện tại |
|---|---|---|
| Đối thủ sao chép | Mua một chiếc kính, đo, sao chép | Kính chỉ là hệ quả; công thức nằm trên server |
| Doanh thu | Một lần mỗi tròng kính | Mỗi lần fitting đều gọi server → tính phí được |
| Cập nhật thuật toán | Phải thu hồi sản phẩm | Deploy lại server |

---

## 3. Kiến trúc hệ thống

### Bảy tầng xử lý

Kiến trúc theo đúng V2.1 Design Baseline do cố vấn khoa học đưa ra:

```
1. Clinical Phenotype          Đo lường → 8 chỉ số AI + phenotype R/B/S/N/T
2. Functional Requirement      Phenotype → vector nhu cầu chuẩn hoá 0–1
3. Optical Target              Nhu cầu → mục tiêu quang học từng vùng (dioptre)
4. Design Profile              9 phương án/mắt → tối ưu đồng thời OD/OS
5. Geometry Projection         Thiết kế → toạ độ, hai kênh quang học riêng biệt
6. Manufacturing Compensation  Bù trừ hao hụt quy trình gia công
7. Execution Package           Phát hành theo từng nhà máy, mỗi bên một mảnh
```

**Tầng 1 và 2 không biết tròng kính tồn tại.** Đây là ranh giới quan trọng nhất về
mặt kiến trúc: nếu công ty chuyển sang vật liệu MR-8, sang polycarbonate, hay sang
kính áp tròng, **tầng lâm sàng không phải viết lại**. Tính chất này được khẳng định
bằng test tự động, không phải bằng lời hứa trong tài liệu.

Tương tự, **thay đổi quy trình nhà máy chỉ động tới tầng 6 và 7**. Việc lớp phủ
cứng làm hao hụt chiều cao vi cấu trúc là chuyện của nhà máy, không được phép ảnh
hưởng ngược lên thuật toán lâm sàng.

### Hai kênh quang học tách biệt

Đây là điểm sửa quan trọng nhất trong V2.1. Trước đó hệ thống gộp hai thứ khác nhau
về bản chất làm một, và đó là **sai từ gốc**.

| Kênh | Nội dung | Xuất ra |
|---|---|---|
| **Mặt sau / nền** | Đơn kính · freeform · aspheric SA tuỳ chọn | Bản đồ sag `z(r, θ)` |
| **Vi cấu trúc mặt trước** | Điều biến theo thống kê không gian · phân bố Poisson-disk · bất đối xứng thái dương | Danh sách toạ độ phần tử |

NSO **không phải** kiến trúc lenslet add-power kiểu DIMS/HAL. Hai kênh này đi hai
đường riêng từ thiết kế tới nhà máy và không bao giờ trộn lẫn.

### Mô hình ba vùng

Số liệu tham chiếu do cố vấn khoa học cung cấp:

| Vùng | Kích thước phần tử | Chiều cao | Fill factor |
|---|---|---|---|
| A | 22 µm | 2,2 µm | 38% |
| B | 28 µm | 1,5 µm | 35% |
| C | 32 × 16 µm | 1,0 µm | 28% |

Mục tiêu quang học theo tier: **Low `1-3-2D`** · **Medium `3-5-4D`** · **High `5-8-6D`**.

Vùng thái dương có thêm điều biến **+25–35%**.

### Ngăn xếp công nghệ

| Thành phần | Công nghệ | Nơi chạy |
|---|---|---|
| Giao diện | Next.js 14, React | Vercel |
| API | FastAPI, Python 3.11 | Render |
| Cơ sở dữ liệu | SQLite (sẵn sàng chuyển Postgres) | Render |
| Báo cáo PDF | ReportLab | — |
| Mã nguồn | GitHub | `bachng23/nso_software` |

---

## 4. Bảo vệ tài sản trí tuệ

### Ba tầng phân quyền

| Tầng | Nội dung | Ai được thấy |
|---|---|---|
| **Clinical** | Design ID, phenotype, chỉ số, % dự báo, lý do chọn | Bác sĩ, trình duyệt, báo cáo PDF |
| **Design IP** | SA, hình học vi cấu trúc, thống kê không gian, bất đối xứng OD/OS | **Chỉ máy chủ** |
| **Manufacturing IP** | Bản đồ bề mặt, bản đồ vi cấu trúc, toolpath | Nhà máy, **mỗi bên một mảnh** |

### Cơ chế bảo vệ

**1. Trình duyệt không nhận công thức.** Phản hồi API chỉ chứa mã thiết kế dạng
`NSO-P425W` và các chỉ số dự báo. Mở công cụ phát triển của trình duyệt cũng không
thấy thông số quang học nào.

Có hàm `assert_no_design_leak()` quét đệ quy **mọi** phản hồi trước khi gửi đi —
phát hiện từ khoá cấm thì ném lỗi ngay, không âm thầm gửi.

**2. Không có endpoint nào trả về công thức.** Quy trình sản xuất là **chỉ gửi đi,
không tải về**: phòng khám uỷ quyền sản xuất chứ không cầm dữ liệu sản xuất.

**3. Chia mảnh theo nhà máy.** Mỗi vendor có API key riêng, chỉ mở đúng mảnh của
mình:

| Key | FS (mặt trước) | BS (mặt sau) | AV (nghiệm thu) |
|---|---|---|---|
| `front_surface` | ✅ 200 | ❌ 403 | ❌ 403 |
| `back_surface` | ❌ 403 | ✅ 200 | ❌ 403 |
| `assembly` | ❌ 403 | ❌ 403 | ✅ 200 |

**Không key bên ngoài nào lấy được quá một mảnh** — có test khẳng định điều này.

**4. Trừu tượng hoá tham số.** Chia mảnh thôi chưa đủ: nhà máy nhận được nửa công
thức vẫn đọc ra ngôn ngữ thiết kế. Nên mỗi gói chỉ chứa **toạ độ**, không chứa
tham số:

| Gói | Nội dung |
|---|---|
| `FS` | `[[x, y, đường kính, chiều cao], …]` — danh sách vị trí phần tử |
| `BS` | `[[r, θ, z], …]` — lưới sag |
| `AV` | Chỉ dung sai, không có mục tiêu sinh ra dung sai đó |

Không gói nào chứa từ "spherical aberration", "fill factor", "density", "jitter"
hay "zone". Nhà máy gia công được nhưng không suy ngược ra thiết kế.

### Vì sao đủ

Muốn tái tạo know-how, đối thủ cần **đồng thời** hồ sơ bệnh nhân và thiết kế tương
ứng, lặp lại trên nhiều ca. Kiến trúc đảm bảo:

- Bác sĩ biết **tại sao** chọn thiết kế này, không biết **thiết kế là gì**
- Nhà máy biết **làm thế nào**, không biết **cho bệnh nhân nào và tại sao**
- Không bên nào cầm cả hai đầu

---

## 5. Những gì đã hoàn thành

### 5.1 Giao diện lâm sàng ba tầng

| Tầng | Số ô | Bắt buộc | Nội dung |
|---|---|---|---|
| **Tier 1 — Quick Fitting** | 13 | Có | Đủ để sinh thiết kế hoàn chỉnh |
| **Tier 2 — Advanced Clinical** | ~19 | Không | Binocular, điều tiết, thần kinh thị giác |
| **Tier 3 — Research Mode** | ~29 | Không | Protocol CSF, điện sinh lý, eye tracking, wavefront |

Nguyên tắc **"UI complexity ≠ algorithm complexity"**: backend phức tạp tuỳ ý,
màn hình bác sĩ vẫn đơn giản. Bác sĩ chỉ cần Tier 1 là bấm Generate ra kết quả đầy đủ.

### 5.2 Engine lâm sàng

**8 chỉ số AI** (thang 0–100): refractive risk · binocular load · accommodative
stress · spatial frequency sensitivity · visual stress · neural adaptation ·
dynamic robustness · interocular image balance.

**Phenotype R/B/S/N/T** — mã 5 miền, ví dụ `R2-B1-S1-N2-T2`.

**Vector nhu cầu chuẩn hoá 0–1** — control demand, visual tolerance, contrast
reserve, peripheral modulation, temporal asymmetry. Đây là ranh giới độc lập sản phẩm.

### 5.3 Tối ưu hoá thiết kế

**9 phương án mỗi mắt** trên lưới hai trục (cường độ SA × độ phủ), **81 cặp** được
chấm điểm đồng thời cho hai mắt.

Hai trục đánh đổi khác nhau — đây là điểm có ý nghĩa lâm sàng thật:

| Tăng | Kiểm soát cận | Thị lực | Thoải mái |
|---|---|---|---|
| **SA** (cường độ) | ↑ | **↓** | ↓ |
| **Fill factor** (độ phủ) | ↑ | **không đổi** | ↓ |

Nghĩa là muốn thêm kiểm soát mà giữ thị lực thì mua bằng **độ phủ**, không phải
cường độ. Hệ thống chọn đúng như vậy: mục tiêu "Night Vision" ra thiết kế SA thấp +
fill factor cao, khác hẳn "Myopia Management".

**Thuật toán chọn:** augmented weighted Tchebycheff thay vì tổng có trọng số. Lý
do kỹ thuật: tổng tuyến tính trên tập rời rạc **luôn** chọn điểm cực trị, nên 9 mục
tiêu lâm sàng chỉ ra được 2 thiết kế. Tchebycheff tối thiểu hoá khoảng thiếu hụt
tệ nhất, nhờ đó phương án cân bằng mới thắng được — kết quả **5/9 mục tiêu ra thiết
kế khác nhau**.

### 5.4 Chiếu hình học sản xuất

**Mặt sau:** bản đồ sag `z(r, θ)`. Số hạng bậc cao chỉ tồn tại trong vùng quang học
chức năng, chuyển tiếp trơn ở biên bằng hàm cửa sổ liên tục tới đạo hàm bậc hai —
tránh tạo vòng khuyết tật quang học trên mặt kính.

**Mặt trước:** phân bố **Poisson-disk thật** (không phải lưới nhiễu). Thuật toán
dart-throwing với ưu tiên xác định, cho phép truy cập ngẫu nhiên theo trang. Đã đo:
khoảng cách tối thiểu giữa hai phần tử luôn ≥ bán kính đĩa.

Hiệu năng: ~325.000 phần tử, phân trang, **0,1 giây** cho một trang bất kỳ.

### 5.5 Bù trừ quy trình sản xuất

Lớp phủ cứng làm cấu trúc danh nghĩa **3,0 µm** chỉ còn **~1,8 µm** thực tế
(retention 0,6 — số liệu từ cố vấn khoa học).

Hệ thống tự động tăng chiều cao thiết kế để sau khi phủ đạt đúng mục tiêu. Quan
trọng: việc này nằm ở **tầng 6**, không được phép ảnh hưởng ngược lên thuật toán
fitting — có test khẳng định đổi hệ số bù trừ không làm đổi thiết kế.

### 5.6 Vòng lặp đóng

```
Khám lần đầu → Design ID → Sản xuất → Nghiệm thu
    → Tái khám (đo AL) → Đánh giá tiến triển → Refit → Design ID mới (revision 2)
```

Hệ thống theo dõi chiều dài trục qua các lần khám, phân loại tiến triển
(Controlled / Borderline / Progressing), và sinh thiết kế mới có liên kết với bản cũ.

### 5.7 Chuẩn lâm sàng đã áp dụng

Những chỗ có tiêu chuẩn y văn thì dùng trực tiếp, không bịa hệ số:

| Tiêu chuẩn | Áp dụng |
|---|---|
| **Chuẩn Morgan** | Phoria gần chuẩn là −3Δ exo, đo lệch hai chiều |
| **Tiêu chuẩn Sheard** | Dự trữ đối kháng ≥ 2× độ lệch; exo cần PFV, eso cần NFV |
| **Hofstetter** | Biên độ điều tiết tối thiểu = 18,5 − 0,30 × tuổi |
| **Nhu cầu điều tiết** | demand (D) = 100 / khoảng cách (cm) |
| **Loạn thị dư** | = |trụ khúc xạ| − loạn giác mạc |

### 5.8 Độ tin cậy có ý nghĩa

Công thức: `55 + 25 × độ phủ đo lường + 20 × tính hợp lý`

Hệ thống kiểm tra **33 khoảng giá trị lâm sàng**. Giá trị bất thường **làm giảm** độ
tin cậy và được nêu đích danh trong kết quả:

| Trường hợp | Độ tin cậy |
|---|---|
| Không đo thêm | 75 |
| Đo 1 giá trị hợp lý | 80 |
| **Đo 1 giá trị bất thường** | **70** |

Và theo yêu cầu của cố vấn, **làm xét nghiệm không tự động làm tăng độ tin cậy**:
một con số VEP trần không có stimulus, đơn vị hay mốc tham chiếu thì được ghi lại
nhưng không được tính là bằng chứng. Chỉ Z-score hoặc chỉ số có thang xác định mới
được tính.

### 5.9 CSF độc lập thiết bị

Mỗi phép đo mang theo protocol của chính nó:

```
device · test_protocol · spatial_frequency_cpd[] · raw_sensitivity[]
logCS[] · normalization_reference · AUC · slope · centroid
```

Đổi máy đo chỉ đổi dữ liệu lưu trữ, không phải sửa code. Nếu phòng khám không báo
tần số, hệ thống giả định và **đánh dấu rõ là giả định** — để giả định đi theo dữ
liệu chứ không nấp trong engine.

---

## 6. Sẵn sàng cho Machine Learning

Hệ thống hiện tại là rule-based, nhưng được thiết kế để **thay bằng mô hình học
máy mà không phải viết lại**.

### Ba mối nối đã dựng sẵn

**1. `EngineConfig` — 109 tham số ra khỏi code.** Hiệu chỉnh là đổi file cấu hình
JSON, không phải sửa code, review, deploy. Mọi kết quả mang `config_version` nên
truy vết được.

**2. `FeatureVector` — 103 feature bệnh nhân + 22 feature thiết kế, có version.**

- **Train/serve parity:** cùng một hàm sinh feature cho huấn luyện và cho production
- **Missing ≠ average:** mỗi trường tuỳ chọn có cờ `*_measured` đi kèm, để model
  phân biệt "trung bình" với "chưa đo" — bỏ qua chuyện này là nguồn bias âm thầm kinh điển
- **Schema mismatch báo lỗi** thay vì đọc nhầm mảng rồi trả về kết quả sai một cách tự tin

**3. `Predictor` protocol — thay model là đổi một dòng đăng ký.**

Ranh giới quan trọng: **predictor nói *sẽ xảy ra gì*, hàm loss nói *ta coi trọng
gì***. Đổi model không âm thầm đổi ưu tiên lâm sàng, và không mở rộng được không
gian thiết kế.

**4. `training_row()` — định dạng dataset đã có sẵn.** Log mỗi ca fitting, gắn kết
quả ở lần tái khám. Đó chính là dataset.

### Kiến trúc ML đề xuất

**Không dùng deep learning trong giai đoạn đầu.** Với 20–200 bệnh nhân và ~125
feature, `p >> n` — mạng nơ-ron sẽ học thuộc nhiễu và vi phạm những quan hệ ta biết
chắc là đúng (ví dụ kết luận "SA cao hơn → kiểm soát kém hơn" từ nhiễu).

**Tách làm hai model:**

| | Model A — Quang học | Model B — Lâm sàng |
|---|---|---|
| Học | hình học → MTF/PSF/defocus ngoại vi | (bệnh nhân + hiệu năng) → kết quả |
| Nguồn | Bench + **mô phỏng ray-tracing** | Theo dõi bệnh nhân |
| Cỡ mẫu | Hàng nghìn (mô phỏng: vô hạn) | 20–200, tăng chậm |

Model A **làm được ngay, không cần bệnh nhân nào** — và đây là chỗ deep learning
thật sự hợp lý, vì mô phỏng sinh được dữ liệu vô hạn.

**Model B học phần dư, không học kết quả:**

```
outcome = dự_đoán_rule_based + f_học_được(bệnh nhân, thiết kế)
```

Với 20 ca, `f` học được rất ít nhưng hệ thống vẫn chạy tốt vì rule-based gánh phần
chính. **Không có thời điểm nào hệ thống tệ đi.**

**Lộ trình theo cỡ mẫu:**

| n | Kiến trúc |
|---|---|
| 20–100 | Bayesian hierarchical linear trên phần dư — chuẩn mực cho dữ liệu lặp trong nhãn khoa |
| 200–1000 | GBM có **ràng buộc đơn điệu** (bắt buộc: tải quang học ↑ → control ↑) |
| >2000 | GBM + random effect theo trung tâm |

Deep learning chỉ hợp cho ba việc, đều là **encoder nén tín hiệu chiều cao**: bản
đồ địa hình giác mạc, đường cong CSF đầy đủ, chuỗi eye-tracking thô.

---

## 7. Kiểm thử và chất lượng

### 441 test tự động, 100% pass

| File | Số test | Nội dung |
|---|---|---|
| `test_nso_core.py` | 95 | Engine tính toán gốc |
| `test_nso_v2.py` | 102 | Tầng V2 qua shim tương thích |
| `test_nso_package.py` | 244 | Kiến trúc, ML seam, persistence, hình học |

### Những gì test bảo vệ

Không chỉ kiểm tra "code chạy", mà kiểm tra **các tính chất kiến trúc**:

- **Ranh giới IP** — không thông số thiết kế nào lọt vào phản hồi lâm sàng
- **Hai kênh tách biệt** — đổi vi cấu trúc không làm nhúc nhích bản đồ sag
- **Độc lập sản phẩm** — hai tầng đầu không chứa từ nào về hình học tròng kính
- **Cách ly quy trình** — đổi hệ số nhà máy không đổi thiết kế
- **Không có ô nhập nào trơ** — thêm trường mới mà quên nối vào engine thì **fail**
- **Không phương án nào áp đảo** — chặn bảng so sánh giả
- **Không hạng mục loss nào bất biến** — chặn trọng số vô nghĩa

### Bốn nhóm lỗi tự phát hiện

Quá trình phát triển đã tìm và sửa những lỗi **ảnh hưởng hành vi lâm sàng**:

| Lỗi | Hậu quả nếu không sửa |
|---|---|
| Dropdown "Primary Goal" vô tác dụng | 9 mục tiêu ra cùng một thiết kế |
| Control không phụ thuộc SA | Bảng so sánh phương án là giả — chỉ có một đáp án |
| Eso hoàn toàn vô hình | Mọi bệnh nhân lác trong chấm điểm như không có vấn đề |
| Ngưỡng fusion sai thang đo | Penalty hai mắt **đã ngừng hoạt động** mà không ai biết |
| Confidence không nhìn giá trị | Nhập số bất khả thi vẫn tăng độ tin cậy |
| "Blue-noise" chỉ có trong comment | Code thực tế là lưới nhiễu, phổ không gian khác hẳn |

Đáng chú ý: **lỗi ngưỡng fusion được phát hiện nhờ chính test chặn "hạng mục loss
bất biến"** viết ở đợt trước — tức hệ thống test đang tự bảo vệ chính nó.

### Chất lượng mã nguồn

- `pyflakes` sạch, không cảnh báo
- Frontend build production thành công
- Tài liệu: 3 file (README, ASSUMPTIONS, INPUTS) ~2.000 dòng

---

## 8. Triển khai

### Đang chạy production

| Thành phần | Địa chỉ | Trạng thái |
|---|---|---|
| Giao diện | https://nso-software.vercel.app | ✅ V2.1 |
| API | https://nso-api-l0w7.onrender.com | ✅ V2.1 |
| Cơ sở dữ liệu | SQLite trên Render | ✅ Hoạt động |

### Kiểm chứng trên production

```
design_store   SQLiteDesignStore
pipeline       7 tầng đầy đủ
predict        NSO-P008B, control score 54
IP leak scan   clean
submit         NSO-26-SG-008721-R01
serial tăng    8721 → 8723 → 8724
refit          NSO-P918L rev 2, đọc được thiết kế cũ
```

Kết quả trên production **trùng khớp chính xác** với chạy local — tính xác định
được giữ qua các môi trường.

### Giới hạn hạ tầng hiện tại

Render gói miễn phí cho container **ngủ sau ~15 phút** không dùng, và ổ đĩa là
ephemeral. Thiết kế sống qua khởi động lại tiến trình nhưng **mất khi container
ngủ hẳn**.

Đủ cho demo, **không đủ cho vận hành thật**. Cần nâng cấp lên Postgres ngoài
(khoảng 2–4 giờ công, cộng chi phí hosting).

---

## 9. Rủi ro và giới hạn

### 🔴 Rủi ro cao

**R1 — Mô hình quang học chưa hiệu chỉnh**

Đánh giá của cố vấn khoa học: *"381 test pass nghĩa là phần mềm V2 đã xong, nhưng
mô hình quang học mới ở khoảng V0.5."*

Trong 109 tham số cấu hình, chỉ một phần nhỏ đến từ số liệu thật (bảng ba vùng, mục
tiêu D theo tier, đường kính 65 mm, hệ số HC). Phần còn lại — đặc biệt **toàn bộ
trọng số tầng lâm sàng** — do đội phát triển đặt ra cho "trông hợp lý".

*Ảnh hưởng:* Không được dùng cho quyết định lâm sàng thật.
*Giảm thiểu:* Mọi kết quả mang nhãn "concept estimate". Cần giữ nhãn này cho tới
khi có dữ liệu.

**R2 — Chưa có kiểm định quang học**

Hệ thống chỉ kiểm tra **hình dạng** tròng kính thành phẩm, không đo MTF hay
through-focus. Một tròng kính đạt kiểm tra vẫn có thể không đạt hiệu năng dự đoán.

*Giảm thiểu:* Hàm đã đổi tên thành `geometric_verification` và mọi kết quả ghi rõ
`optical_performance_verified: false`.

**R3 — Thông số cấu tạo tròng kính chưa đầy đủ**

Chiết suất (1,60), base curve (4,0 D), bán kính vùng chức năng (10 mm), và **ranh
giới bán kính ba vùng** (0–4, 4–9, 9–16 mm) đều là giá trị tạm.

Riêng ranh giới vùng đặc biệt quan trọng: cố vấn đã cho **kích thước phần tử** từng
vùng nhưng **chưa nói vùng nằm ở đâu** trên mặt kính.

*Ảnh hưởng:* Quyết định toàn bộ hình học gửi nhà máy.

### 🟠 Rủi ro trung bình

**R4 — Dung sai nghiệm thu chưa hỏi nhà máy**

Ngưỡng đạt/không đạt hiện là phỏng đoán. Quá chặt loại oan hàng tốt, quá lỏng cho
qua hàng lỗi.

**R5 — Hạ tầng chưa sẵn sàng vận hành**

Xem mục 8. Cần Postgres.

**R6 — `PostgresDesignStore` chưa chạy thử với server thật**

Cùng schema và câu lệnh SQL với SQLite (đã test đầy đủ), nhưng phần kết nối chưa
kiểm chứng.

### 🟡 Rủi ro thấp

**R7 — Một số ô nhập chưa vào thuật toán**

`ocular_dominance` và `corneal_eccentricity` đã nối đường nhưng hệ số để 0 chờ cố
vấn. Đã đánh dấu **NOT YET USED** trên giao diện để bác sĩ không hiểu nhầm.

---

## 10. Việc còn lại

### Cần dữ liệu — không phải việc lập trình

| Cần gì | Nguồn | Ai lấy được |
|---|---|---|
| Ranh giới bán kính ba vùng | Cố vấn khoa học | Đã hỏi, chờ trả lời |
| Chiết suất, base curve | Cố vấn / spec sản phẩm | Đã hỏi |
| Hệ số tầng lâm sàng | Cố vấn / y văn / dữ liệu | Cần hiệu chỉnh |
| Dung sai quy trình (Cpk) | **Nhà máy** (瑞儀) | Cần đầu mối liên hệ |
| Máy đo CSF, tần số, thang đo | **Phòng khám** | Hỏi người vận hành |
| Đơn vị VEP/ERG | **Kỹ thuật viên** | Hỏi người vận hành |
| **MTF/PSF của tròng kính mẫu** | **Bench đo** | ⚠️ Phải đo mới có |
| **Chiều dài trục theo thời gian** | **Theo dõi bệnh nhân** | ⚠️ Phải theo dõi mới có |

Hai hàng cuối quan trọng nhất và **không ai đưa được** — chúng phải được **tạo ra**.

> **Con đường rẻ hơn:** nếu phòng khám đã lắp kính kiểm soát cận cho vài chục ca có
> đo AL theo dõi, đó là **bộ dữ liệu đầu tiên có ngay hôm nay**, không cần chờ 12
> tháng. Đây là câu hỏi nên đặt ra sớm.

### Cần lập trình

| Việc | Công sức | Chặn bởi |
|---|---|---|
| **NSO Design Calibration Matrix** | 3–5 ngày | Không — làm được ngay |
| Model A: surrogate quang học từ mô phỏng | 1–2 tuần | Cần forward model quang học |
| Nâng cấp Postgres + test | 2–4 giờ | Không |
| Đưa 2 ô còn lại vào thuật toán | 2 giờ | Chờ hệ số từ cố vấn |

**Calibration Matrix** là việc cố vấn chỉ định làm tiếp:

```
Phenotype × SA × D × H × FF × thống kê không gian × bất đối xứng thái dương
    → MTF / PSF / CSF / comfort / control response
```

Đây **không phải bảng số chờ điền** mà là hệ thống cần xây: schema lưu kết quả đo,
đường nạp dữ liệu từ bench và tái khám, tầng hồi quy biến điểm đo thành hệ số.

### Giới hạn năng lực cần nêu rõ

Đội phần mềm **không dựng được mô hình quang học vật lý** cho vi cấu trúc này. Cần
Zemax/VirtualLab hoặc kỹ sư quang học viết forward model. Đội làm được hạ tầng ML
bao quanh nó, không làm được phần vật lý.

---

## 11. Lộ trình đề xuất

### Giai đoạn 1 — Không chặn bởi ai (2–3 tuần)

| | Việc | Kết quả |
|---|---|---|
| 1 | Nâng cấp Postgres, test với server thật | Hạ tầng sẵn sàng vận hành |
| 2 | Xây Calibration Matrix (schema + nạp dữ liệu + hồi quy) | Sẵn sàng nhận số đo đầu tiên |
| 3 | Đường nạp dữ liệu hồi cứu | Dùng được hồ sơ bệnh nhân cũ |

### Giai đoạn 2 — Cần phối hợp bên ngoài (1–3 tháng)

| | Việc | Cần ai |
|---|---|---|
| 4 | Lấy thông số tròng kính đầy đủ | Cố vấn khoa học |
| 5 | Liên hệ nhà máy về dung sai và định dạng file | 瑞儀 |
| 6 | Xác định protocol đo bench | Cố vấn + phòng lab |
| 7 | Forward model quang học (Zemax/VirtualLab) | Kỹ sư quang học |

### Giai đoạn 3 — Hiệu chỉnh (3–12 tháng)

| | Việc | Điều kiện |
|---|---|---|
| 8 | Đo MTF/PSF tròng kính mẫu | Có tròng kính mẫu |
| 9 | Model A: surrogate quang học | Có dữ liệu bench/mô phỏng |
| 10 | Hồi cứu hồ sơ bệnh nhân | Phòng khám có dữ liệu cũ |
| 11 | Model B giai đoạn 1 (Bayesian, n=20–100) | Có 20+ ca |
| 12 | Theo dõi tiến cứu | Bắt đầu từ ca đầu tiên |

### Mốc đánh giá

| Mốc | Tiêu chí |
|---|---|
| **M1** | Hạ tầng vận hành thật (Postgres, không mất dữ liệu) |
| **M2** | Calibration Matrix nhận được số đo đầu tiên |
| **M3** | Model A thay được hệ số hình học → quang học |
| **M4** | Model B chạy trên dữ liệu hồi cứu, tốt hơn rule-based |
| **M5** | Mô hình quang học đạt V1.0 — hết hệ số chưa hiệu chỉnh ở đường chính |

---

## 12. Phụ lục

### 12.1 Tài liệu kèm theo

| File | Nội dung |
|---|---|
| `README.md` | Kiến trúc, cách chạy, cách triển khai |
| `ASSUMPTIONS.md` | **Mọi con số là giá trị tạm**, phân mức P0–P3 |
| `INPUTS.md` | Từng ô nhập liệu: vai trò, đường đi, độ tin cậy |

`ASSUMPTIONS.md` là tài liệu quan trọng nhất về mặt quản trị rủi ro — nó liệt kê
đầy đủ những gì chưa được kiểm chứng, để không ai nhầm tưởng một con số đã có cơ sở.

### 12.2 Danh sách API

| Endpoint | Chức năng | Ai gọi |
|---|---|---|
| `GET /api/health` | Trạng thái, phiên bản, pipeline | Giám sát |
| `POST /api/predict` | Sinh thiết kế cá nhân hoá | Giao diện |
| `POST /api/followup` | Đánh giá tiến triển | Giao diện |
| `POST /api/refit` | Vòng lặp đóng — thiết kế mới | Giao diện |
| `POST /api/manufacturing/submit` | Gửi sản xuất | Giao diện |
| `POST /api/manufacturing/package` | Nhận gói gia công | **Nhà máy** (cần key) |
| `POST /api/manufacturing/verify` | Nghiệm thu hình học | **Nhà máy** (cần key) |
| `POST /api/report/prediction` | Báo cáo PDF | Giao diện |
| `POST /api/report/followup` | Báo cáo tái khám PDF | Giao diện |

### 12.3 Cấu trúc mã nguồn

```
src/backend/nso/
  clinical.py            Tầng lâm sàng — thứ duy nhất qua mạng
  pipeline.py            Bảy tầng, chạy được từng chặng
  design/
    synthesis.py         Phenotype → thiết kế quang học
    candidates.py        Sinh phương án + hàm loss
    joint.py             Tối ưu đồng thời hai mắt
    identity.py          Design ID
  manufacturing/
    geometry.py          Bản đồ sag + phân bố Poisson-disk
    compensation.py      Bù trừ quy trình
    registry.py          Lưu trữ + phát hành theo vendor
    store.py             SQLite / Postgres
    verification.py      Nghiệm thu hình học
  predictors/            ← chỗ cắm mô hình ML
  features.py            ← ML seam, feature có version
  csf.py                 CSF độc lập thiết bị
  phenotype.py           Phân hạng R/B/S/N/T
  patient.py             Đầu vào lâm sàng
  recipe.py              Công thức thiết kế (Design IP)
  config.py              109 tham số, load được từ JSON
  ip.py                  Chốt chặn rò rỉ
```

### 12.4 Lịch sử phiên bản

| Phiên bản | Nội dung |
|---|---|
| v0.3 | Engine rule-based, giao diện demo |
| V2 | Phân tầng IP, phenotype đa chiều, refactor thành package, ML seam |
| **V2.1** | Hai kênh quang học, mô hình ba vùng, bảy tầng, CSF độc lập thiết bị |

---

## Kết luận

**Phần mềm đã hoàn thiện.** Kiến trúc bảy tầng, hai kênh quang học tách bạch, ba
tầng bảo vệ IP có kiểm chứng, hạ tầng ML sẵn sàng, 441 test, đang chạy production.

**Mô hình quang học thì chưa.** Hệ thống đang tính toán bằng những con số phần lớn
chưa ai đo. Đây là giai đoạn tự nhiên, không phải thiếu sót — nhưng cần được hiểu
đúng khi trình bày ra bên ngoài.

**Nút thắt đã chuyển.** Từ "viết thêm code" sang "đo trên bench và theo dõi bệnh
nhân". Việc giá trị nhất bây giờ không phải mở rộng tính năng, mà là xây Calibration
Matrix và bắt đầu thu thập dữ liệu — trong đó **hồi cứu hồ sơ bệnh nhân cũ là con
đường nhanh nhất** để có bộ dữ liệu đầu tiên.
