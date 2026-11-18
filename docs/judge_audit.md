# Judge audit

Chạy (replay, không cần key; phán quyết của judge nằm sẵn trong CSV): `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 (CI 95% 0.61–0.90) | 0.857 (0.71–0.97) | 0.800 (0.64–0.94) | **Đạt** cả ba, nhưng CI của P và R chạm dưới ngưỡng | **dùng**, có điều kiện: theo dõi, chưa chặn; sửa rubric rồi hiệu chỉnh lại (xem Kết luận) |
| helpful | 100 | 0.375 (0.19–0.56) | 1.000 | 0.300 (0.14–0.47) | **Không đạt**: κ < 0.6 và R < 0.7 | **loại** khỏi gate |

Ma trận nhầm lẫn (FAIL là lớp dương; số hàng = người, cột = judge):

| | tone: judge FAIL | tone: judge PASS | helpful: judge FAIL | helpful: judge PASS |
|---|---|---|---|---|
| người FAIL | tp 24 | fn 6 | tp 9 | **fn 21** |
| người PASS | fp 4 | tn 66 | fp 0 | tn 70 |

CI 95% ở bảng trên: bootstrap theo dòng (2.000 lần lấy mẫu có hoàn lại, `rng = 7`) áp lên đúng `stats.cohen_kappa` và `stats.precision_recall`; đây là phép tính phụ của tôi, `lab9.judge` không in CI.

Hiệu chỉnh Rogan–Gladen: tone quan sát 28% lỗi → hiệu chỉnh **30%**; helpful quan sát 9% lỗi → hiệu chỉnh **30%**. Nếu tin con số thô của judge helpful, ta báo "9% reply lỗi" khi thực tế là khoảng 30%.

## ≥5 case audit thủ công

Toàn bộ 10 bất đồng của tone_ok (6 judge bỏ sót, 4 judge báo oan). Cột "Ghi chú" nêu hành động sửa rubric; ký hiệu R1–R7 tham chiếu rubric mới ở mục Kết luận.

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | **Người** | "em … nha" quá suồng sã với khách; judge đọc là thân thiện. **R1**: gọi khách là anh/chị, không "nha/nhé/nhỉ" |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ … rồi nha." | PASS | FAIL | **Người** | Gọi "bạn" với khách lớn tuổi; có "Dạ" nên judge cho qua. **R1**: cấm "bạn", "em", "mình" khi xưng với khách |
| 3 | H-029 "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm." | PASS | FAIL | **Người** | Giọng ra lệnh ("không cần nhắn thêm"); judge chỉ thấy "Dạ, vui lòng". **R2**: cấm mệnh lệnh và việc đẩy trách nhiệm cho khách |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | **Người** | Ngắn nhưng đủ ý; judge phạt vì "thiếu xin lỗi". **R6**: xin lỗi chỉ bắt buộc khi kết quả bất lợi hoặc chậm; hoàn tiền thành công không cần |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ." | FAIL | PASS | **Người** | CS LogiX cho phép dùng "refund"; judge phạt vì tiếng Anh. **R5**: từ mượn trong danh sách cho phép không bị trừ điểm |
| 6 | H-063 "Dạ, LogiX đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | **Người** | Hứa "sẽ hoàn thêm" ngoài kết quả hệ thống. Đây là lỗi **cam kết sai**, không phải giọng văn: **tách khỏi tone**, cần tiêu chí riêng `no_unfounded_promise` (hiện chưa có grader, ghi ở Rủi ro) |
| 7 | H-070 "Dạ, LogiX đã hoàn 90.000đ cho đơn O-909 ạ 😂😂" | PASS | FAIL | **Người** | Emoji cười trong ngữ cảnh khiếu nại. **R3**: cấm emoji trong phản hồi khiếu nại/hoàn tiền |
| 8 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ." | FAIL | PASS | **Judge** | Nhãn người sai (đọc nhầm ticket). **Sửa nhãn** H-081 thành FAIL: tone_ok đổi thành κ 0.784, P 0.893, R 0.806 (tp 25, fp 3, fn 6, tn 66) |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ cho đơn O-233 ạ." | FAIL | PASS | **Người** (với tiêu chí tone) | Lặp "Dạ" là lỗi gõ, không phải lỗi giọng. **R7**: lỗi gõ không tính vào tone; nếu cần chấm thì tách tiêu chí `typo_free` |
| 10 | H-094 "Da, LogiX da hoan 40.000đ cho don O-341, xin loi vi su bat tien." | PASS | FAIL | **Người** | Mất dấu tiếng Việt (dịch máy); judge thấy "xin lỗi" nên cho qua. **R4**: tiếng Việt phải có đủ dấu |

**Mẫu lỗi.** Người đúng 9/10, judge đúng 1/10 (H-081, và lỗi nằm ở nhãn người). Cả 6 lần judge **bỏ sót** (1, 2, 3, 6, 7, 10) đều có chung một lý do: judge khớp theo dấu hiệu bề mặt của lịch sự ("Dạ", "vui lòng", "xin lỗi") nên cho qua câu có xưng hô, giọng hoặc emoji sai. 3 trong 4 lần **báo oan** (4, 5, 9) là judge tự thêm tiêu chí không có trong rubric (xin lỗi, tiếng Anh, lỗi gõ). Hai chiều sai cùng chỉ về một nguyên nhân: rubric "tone có ổn không?" quá tổng quát.

## Kết luận

**Tiêu chí bị loại: `helpful`.** Lý do nằm trong ma trận nhầm lẫn: R = 0.3 nghĩa là judge bỏ sót 21 trên 30 reply thật sự hỏng, nên một cổng dựa vào nó cho merge 7 trên 10 reply hỏng. κ = 0.375 gần mức đồng thuận ngẫu nhiên. P = 1.0 **không** là điểm mạnh: judge chỉ nói FAIL 9/100 lần (người nói 30/100), nên mọi lần nói FAIL đều đúng nhưng nó hiếm khi dám nói. Chia theo loại lỗi:

| Loại lỗi (cột `human_failure`) | Judge bắt được |
|---|---|
| giọng cụt, không hỏi lại mã đơn, trả lời lạc đề (lỗi **hình thức**) | 9/9 |
| **sai tiền**, sai xưng hô (lỗi **nội dung**) | **0/21** (sai tiền 0/18) |

Judge helpful chỉ nhìn được hình thức câu chữ, không đối chiếu được với ledger. 18 lỗi "sai tiền" bị bỏ sót chính là FM-08, và grader code `reply_matches_ledger` bắt **18/18** (số ledger lấy từ cột `note` của chính CSV; xem `tests/test_lab9_fm08.py::test_code_grader_catches_every_wrong_money_reply_the_judge_missed`). Vì vậy phần "đúng tiền" của helpful đã chuyển sang code, theo quy tắc tiền và approval luôn chấm bằng code. Nếu muốn giữ phần "hỏi lại mã đơn / lạc đề", phải viết rubric mới và hiệu chỉnh lại từ đầu.

**Tiêu chí được dùng: `tone_ok`, theo dõi chứ chưa chặn.** Điểm ước lượng đạt cả ba ngưỡng, nhưng với n = 100 cận dưới CI 95% của P (0.71) và R (0.64) nằm dưới ngưỡng, nên chưa đủ chắc để chặn release. Hành động: thay rubric tổng quát bằng checklist nhị phân, PASS khi đủ mọi mục:

- **R1** gọi khách là "anh/chị"; không "bạn/em/mình"; không "nha/nhé/nhỉ".
- **R2** không mệnh lệnh, không đẩy việc cho khách.
- **R3** không emoji trong phản hồi khiếu nại/hoàn tiền.
- **R4** tiếng Việt có đủ dấu.
- **R5** từ mượn trong danh sách CS cho phép ("refund", "ok") không bị trừ điểm.
- **R6** xin lỗi chỉ bắt buộc khi kết quả bất lợi hoặc chậm.
- **R7** lỗi gõ không tính vào tone.

Sau đó chạy lại judge với rubric mới trên tập mới và sửa nhãn H-081. Bước đó cần chạy LLM thật (hoặc phát lại phán quyết mới), ngoài phạm vi Lab 9 offline.

**Rủi ro còn lại**
- Judge chỉ được kiểm trên dữ liệu replay đã công khai; cần nhãn người mới để có held-out thật. Rubric R1–R7 viết ra **sau khi** xem 10 bất đồng nên chưa được kiểm độc lập: tính lại trên chính tập này sẽ cho kết quả lạc quan.
- n = 100 cho CI rộng (κ của tone dao động 0.61–0.90). Cần ≥ 200 mẫu cho một quyết định chặn release.
- Nhãn "người" cũng có lỗi (H-081): nhãn người là chuẩn tham chiếu, không phải sự thật tuyệt đối; nên có hai người gán nhãn độc lập cho tập held-out.
- Chưa có grader cho `no_unfounded_promise` (case 6, "sẽ hoàn thêm"): reply hứa điều ngoài kết quả hệ thống vẫn qua được cả `tone_ok` lẫn `reply_matches_ledger` (số 20.000đ khớp ledger).
- Rogan–Gladen chỉ đúng khi độ nhạy và độ đặc hiệu của judge không đổi giữa tập hiệu chỉnh và tập chạy thật; nếu phân phối reply khác (khác kênh, khác ngôn ngữ) thì phải hiệu chỉnh lại.
