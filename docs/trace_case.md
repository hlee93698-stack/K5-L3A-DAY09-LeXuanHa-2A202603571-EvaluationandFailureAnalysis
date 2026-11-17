# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi bạn 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `<shape> <claim>@<seed>`, run ID trong report |
| Triệu chứng | Grader nào fail; reply nói gì so với ledger ghi gì |
| Bước sai đầu tiên | Số thứ tự event + kind + trích payload (≤1 dòng) |
| Vì sao là bước *đầu tiên* | Các bước trước đó đúng ra sao (dẫn số event) |
| Failure mode | Mã FM-xx trong `docs/failure_taxonomy.md` |
| Đối chứng | Cùng claim@seed trên shape `fixed`: bước đó khác thế nào |
| Regression test | Tên test + grader/assert nào bắt được; đã thấy fail trên variant lỗi và pass trên `fixed` chưa |
| Chưa chắc chắn | Điều trace không chứng minh được |

## Case của mình: `swarm C-002@55` (FM-03, ticket_trust)

```bash
cd src
python -m lab9.trace_case --shape swarm --claim C-002 --seed 55   # trial lỗi (baseline)
python -m lab9.trace_case --shape fixed --claim C-002 --seed 55   # đối chứng
```

| Trường | Nội dung |
|---|---|
| Trial | `swarm C-002@55`, trace run ID `R-swarm-C-002-s55`. Đây là trial fail duy nhất trong 70 trial của baseline (item E-002, seed 55). Report run ID **`E-swarm-20261117-9d32`** (`src/reports/baseline_v1.json`, eval set `9d329330b5c5`): row `E-002@55` có `pass_rate=false`, `refund_amount_correct=false`, `db_fact_kept=false` |
| Triệu chứng | Grader Lab 8 fail `status resolved != denied`. Ledger ghi `refund_vnd=20000`, `refund_count=1`, trong khi nhãn là `denied`, 0đ. Shape `swarm` không có event `reply`, nên sai lệch chỉ thấy ở ledger và status |
| Bước sai đầu tiên | **#3 `model_override`** `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | #1 `handoff` đúng contract (chỉ có tool đọc, `facts: {}`). #2 `investigator` đọc O-202 từ DB đúng: `delay_days: 2`, `status: delivered`, `shipping_fee_vnd: 20000`. Với 2 ngày trễ, SHIP-LATE-03 (`min_delay_days: 3`) không áp dụng. Đến #3 agent lấy "trễ 5 ngày" trong ticket đè lên DB. #4 `quote` tính đúng theo dữ liệu nó nhận (20.000đ theo SHIP-LATE-03), nhưng dữ liệu đó đã sai từ #3. Host vẫn ghi tiền vì approval A-002 (20.000đ) còn hiệu lực |
| Failure mode | **FM-03** ticket_trust (layer model/prompt). Trong `swarm_reference.py`, đây là `REFERENCE_WEAKNESS`: chỉ xảy ra khi `seed % 5 == 0` và ticket nói số ngày khác DB |
| Đối chứng | `fixed C-002@55`: #1 handoff, #2 investigator (`delay_days: 2`), **#3 `quote` 0đ `no_entitlement`**, #4 reply "chưa đủ điều kiện". Không có `model_override`, ledger 0, PASS. `seeded_regression C-002@11` có cùng bước sai #3 nhưng ở cả 5 seed (công tắc `ticket_trust`) |
| Regression test | `src/tests/test_lab9_trace_case.py`. `test_c002_first_wrong_step_is_the_ticket_override[swarm-55]` và `[seeded_regression-11]` khóa #3 = `{"delay_days": 5}`, #2 đọc DB = 2, ledger 20000 ≠ 0, Lab 8 fail. `test_c002_fixed_keeps_the_db_fact` kiểm tra `fixed` không override, ledger 0, `DbFactKept` = True. `test_db_fact_kept_flags_the_regression` kiểm tra `DbFactKept` = False trên `seeded_regression`. Kết quả đã chạy: 4 passed. Lỗi nằm ở variant lỗi (FAIL đúng chỗ), còn `fixed` PASS. Ở gate, `db_fact_kept` (step) và `refund_amount_correct`/`pass_rate` (outcome) cùng bắt case này |
| Chưa chắc chắn | (1) Trace không cho biết **vì sao** model tin ticket: MockLLM quyết định theo seed, còn với LLM thật thì nguyên nhân có thể là prompt hoặc thứ tự context. (2) `db_fact_kept` chỉ thấy lỗi khi agent ghi event `model_override`. Công tắc `quiet_override` gây cùng lỗi mà không để lại event (`python -m lab9.fm_survey --bug quiet_override --claim C-002`), nên phải dựa vào metric outcome. (3) Với 5 seed, lỗi 1/5 seed của `swarm` chỉ hiện đúng một lần (seed 55). Một bộ seed không có bội của 5 sẽ không thấy lỗi này |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
