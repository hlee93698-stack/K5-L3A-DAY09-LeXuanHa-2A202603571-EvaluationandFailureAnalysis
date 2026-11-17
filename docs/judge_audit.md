# Judge audit

Chạy (từ `src/`):
```bash
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 10      # exit 0
python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 21   # exit 1
```

Lớp positive là **FAIL**, vì việc của judge là tìm ra reply hỏng. Judge chạy chế độ replay: verdict đã lưu sẵn trong CSV, không gọi model.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | **0.757** | **0.857** | **0.800** | **Đạt** | **dùng**, nhưng chỉ làm metric non-blocking cho giọng văn |
| helpful | 100 | 0.375 | 1.000 | **0.300** | **Không** (κ và R dưới sàn) | **loại**, không dùng làm gate |

| Ma trận nhầm lẫn | tp | fp | fn | tn | Specificity | Tỉ lệ FAIL judge thấy → hiệu chỉnh Rogan-Gladen | Tỉ lệ FAIL thật (người) |
|---|---|---|---|---|---|---|---|
| tone_ok | 24 | 4 | 6 | 66 | 66/70 = 0.943 | 0.28 → **0.30** | 30/100 = 0.30 |
| helpful | 9 | 0 | 21 | 70 | 70/70 = 1.000 | 0.09 → **0.30** | 30/100 = 0.30 |

Rogan-Gladen: `(p_obs + spec − 1) / (sens + spec − 1)`. Với tone, judge thấy 28% FAIL. Sau khi hiệu chỉnh theo sens 0.8 và spec 0.943 ta được 30%, khớp tỉ lệ người gán. Với helpful, hiệu chỉnh đưa 9% về 30%, cũng đúng về **tỉ lệ tổng**. Nhưng đó chỉ là con số trung bình: hiệu chỉnh không cho biết **reply nào** hỏng, nên vẫn không dùng được để chặn từng PR.

## Case audit thủ công (tone: cả 10 bất đồng, helpful: 6 đại diện cho 3 nhóm lỗi)

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú → hành động sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | **Người** | Xưng "em", dùng "nha" là quá suồng sã với khách khiếu nại. **Rubric:** thêm luật xưng hô "LogiX ↔ anh/chị", cấm "em/bạn/nha/nhé", kèm ví dụ FAIL |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ … rồi nha." | PASS | FAIL | **Người** | Cùng lỗi xưng hô như #1. Judge coi "thân thiện" là tốt. **Rubric:** nói rõ thân thiện ≠ suồng sã |
| 3 | H-029 "Dạ, vui lòng chờ … không cần nhắn thêm." | PASS | FAIL | **Người** | Judge chỉ nhìn từ lịch sự ở đầu câu ("Dạ, vui lòng"). **Rubric:** chấm cả câu; câu mệnh lệnh hoặc chặn khách liên hệ thì FAIL dù có "Dạ" |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | **Người** | Judge phạt vì "thiếu xin lỗi". **Rubric:** xin lỗi không bắt buộc khi đã giải quyết xong; ngắn mà đủ ý vẫn PASS |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ …" | FAIL | PASS | **Người** | Style guide CS của LogiX cho phép "refund". **Rubric:** thêm danh sách từ tiếng Anh được phép (refund, ship, voucher) |
| 6 | H-063 "… đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | **Người** | Giọng thì ổn, nhưng reply hứa điều hệ thống không làm. Đây là lỗi **nội dung**, không phải lỗi tone. **Rubric:** tách khỏi tone; lời hứa ngoài kết quả hệ thống do grader code chấm (FM-08/FM-02), không giao cho judge tone |
| 7 | H-070 "… đã hoàn 90.000đ cho đơn O-909 ạ 😂😂" | PASS | FAIL | **Người** | **Rubric:** cấm emoji trong ngữ cảnh khiếu nại, kèm ví dụ FAIL |
| 8 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn …" | FAIL | PASS | **Judge** | Ghi chú ở CSV: người đọc nhầm ticket. **Hành động:** sửa nhãn người sang FAIL trong bản nhãn kế tiếp, ghi lại người sửa và lý do. Đây là lỗi nhãn, không phải lỗi rubric. Sau khi sửa, P của tone tăng lên 25/28 |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ …" | FAIL | PASS | **Người** (chấp nhận được) | Lặp chữ do gõ nhầm, vẫn lịch sự. **Rubric:** lỗi gõ nhỏ không làm FAIL tone |
| 10 | H-094 "Da, LogiX da hoan 40.000đ … xin loi vi su bat tien." | PASS | FAIL | **Người** | Reply mất dấu tiếng Việt (dịch máy). **Rubric:** reply không dấu thì FAIL; có thể kiểm bằng code (tỉ lệ ký tự có dấu) trước khi gọi judge |
| 11 | HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger ghi 40.000đ) | PASS | FAIL | **Người** | Judge không thấy ledger nên **không thể** biết số tiền sai. 18/21 ca judge bỏ sót thuộc nhóm "sai tiền". **Hành động:** bỏ tiêu chí tiền khỏi rubric helpful; tiền do code chấm (metric FM-08 `reply_amount_matches_ledger`) |
| 12 | HL-016 xin lỗi 2 lần rất dài + "đã hoàn 55.000đ" (ledger 35.000đ) | PASS | FAIL | **Người** | Judge ưu ái reply dài, nhiều lời xin lỗi (verbosity bias) và bỏ qua số sai. **Rubric:** chấm trên nội dung đã lược bỏ câu xã giao; độ dài không cộng điểm |
| 13 | HL-043 "rất tiếc … đã hoàn 35.000đ cho đơn O-202" ×2 (ledger 20.000đ) | PASS | FAIL | **Người** | Cùng kiểu với #12: reply lặp câu xin lỗi, judge cho PASS. Bổ sung ví dụ FAIL cho reply lặp ý vào rubric |
| 14 | HL-087 "Dạ, LogiX đã hoàn 60.000đ cho đơn O-202 ạ." (ledger 90.000đ) | PASS | FAIL | **Người** | Reply nói **thấp hơn** ledger. Lỗi tiền theo cả hai chiều, nên grader code phải so bằng (`==`), không chỉ chặn trường hợp reply lớn hơn |
| 15 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | **Người** | Sai xưng hô và không nói kết quả cụ thể. Judge tone đã bắt được loại lỗi này. **Rubric helpful:** reply phải nêu kết quả (đã hoàn bao nhiêu / vì sao từ chối / cần gì thêm) |
| 16 | HL-091, HL-097 "Ok bạn, đơn … xử lý rồi nhé." | PASS | FAIL | **Người** | Giống #15 (3/3 ca "sai xưng hô" bị bỏ sót). Phần xưng hô chuyển cho judge tone, không chấm lại trong helpful |

Judge helpful **không có false positive nào** (fp = 0, P = 1.0): mọi reply nó gắn FAIL đều đúng là hỏng. Ngoài ra nó bắt đủ các lỗi dễ thấy: giọng cụt 4/4, không hỏi lại mã đơn 3/3, lạc đề 2/2. Vấn đề là **recall 0.3**: nó bỏ sót 18/18 ca sai tiền và 3/3 ca sai xưng hô.

## Kết luận

- **tone_ok: dùng được.** Judge đạt cả ba sàn (κ 0.757, P 0.857, R 0.800). Nó chỉ dùng cho một metric **non-blocking** về giọng văn và không được chấm tiền hay approval. Trong 6 ca bỏ sót (fn), lỗi lặp lại là xưng hô suồng sã và giọng mệnh lệnh (#1–3, #7, #10); sửa rubric theo bảng trên. Có 1 ca fp là lỗi nhãn người (#8), cần sửa nhãn.
- **helpful: loại, không dùng làm gate.** κ = 0.375 < 0.6 và R = 0.30 < 0.7: judge bỏ sót 21/30 reply hỏng. Ma trận nhầm lẫn cho thấy lỗi có hệ thống chứ không phải ngẫu nhiên. 18/21 ca fn là **sai số tiền so với ledger**, một thông tin judge không có trong input. Gate dựa vào judge này sẽ cho qua chính FM-08 (`misreport`), lỗi mà grader Lab 8 cũng bỏ sót (xem `failure_taxonomy.md`). Precision 1.0 không cứu được: một judge chỉ bắt lỗi dễ thấy vẫn để lọt phần lớn lỗi nguy hiểm. Rogan-Gladen ước lượng đúng tỉ lệ 30%, nhưng chỉ ở mức tổng, không chỉ ra được reply nào hỏng.
- **Thay thế:** tiền được chấm bằng code (`refund_amount_correct` trên ledger, cộng metric FM-08 so reply với ledger). Phần "có ích" còn lại (nêu kết quả cụ thể, hỏi lại mã đơn khi thiếu) đưa vào rubric v2. Rubric v2 phải được calibrate lại trên nhãn người mới trước khi dùng.
- **Rủi ro còn lại:** judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí, không có held-out). Rubric sửa theo chính các ca này có nguy cơ overfit, nên cần một bộ nhãn người mới để calibrate lại. Nhãn người cũng có lỗi (#8), vì vậy mỗi lần sửa nhãn phải ghi lại người sửa và lý do. Trong lab, verdict là replay nên κ cố định; với judge LLM thật, κ dao động giữa các lần chạy và phải đo nhiều lần.
