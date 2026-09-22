# Đánh giá khả năng sinh lời và cạnh tranh của bot

Ngày đánh giá: **22/09/2026**. Mục tiêu: **tự giao dịch bằng vốn dưới 1.000 USD**. Mã nguồn nền: `b3996a8`, nhánh `docs/hourly-strategy-hardening-plan`. Các tài liệu hardening đang sửa trong workspace được xem là kế hoạch, chưa phải tính năng đã triển khai.

## Kết luận đầu tư

**Chưa đủ bằng chứng để cấp vốn thật cho bot hiện tại.** Điểm yếu quyết định không phải thiếu chiến lược hoặc thiếu mô hình ML: sổ PnL, mô phỏng khớp lệnh và định tuyến spot/futures đang có sai lệch khiến kết quả paper chưa dùng được làm cơ sở đầu tư. Bằng chứng lợi nhuận tốt nhất của Plan D mới ở mức báo cáo lịch sử; chưa có bộ trade/equity đầy đủ trong checkout để tái lập.

Với vốn dưới 1.000 USD, hướng hợp lý nhất là **một chiến lược đơn giản, ít giao dịch, chi phí vận hành gần bằng 0, tiếp tục paper và đo kết quả ròng**. Trend cơ học là ứng viên kiểm chứng đầu tiên vì chỉ có một chân giao dịch và dễ thu nhỏ quy mô. Funding có hedge là ứng viên nghiên cứu thứ hai sau khi sửa accounting và execution; lợi suất trên toàn bộ vốn có thể thấp hơn nhiều con số funding annualized. Basis, market making và cross-exchange hiện không phù hợp để cấp vốn.

Đây là kết luận về **mức độ sẵn sàng và bằng chứng hiện có**, không phải dự báo rằng mọi biến thể của bot sẽ lỗ. Cũng chưa có dữ liệu so sánh đồng thời để khẳng định một bot thương mại cụ thể sẽ kiếm lời tốt hơn.

## Nhóm nghiên cứu và phương pháp

Sáu vai trò làm việc song song: kiểm chứng lợi nhuận; chiến lược và nguồn lợi thế; execution/risk; ML/dữ liệu; đối thủ; tổng hợp kinh tế vốn và phản biện. Đầu ra chi tiết:

| Mảng | Hồ sơ |
|---|---|
| Kết quả và chất lượng backtest | [evidence.md](/home/hoangt/projects/quant/docs/2026-09-22/profitability-review/evidence.md) |
| Từng chiến lược và điều kiện hòa vốn | [strategies.md](/home/hoangt/projects/quant/docs/2026-09-22/profitability-review/strategies.md) |
| Định tuyến lệnh, PnL, margin, recovery | [execution.md](/home/hoangt/projects/quant/docs/2026-09-22/profitability-review/execution.md) |
| ML, leakage, feature parity và timeframe | [ml.md](/home/hoangt/projects/quant/docs/2026-09-22/profitability-review/ml.md) |
| Đối thủ và nguồn chính thức | [competitors.md](/home/hoangt/projects/quant/docs/2026-09-22/profitability-review/competitors.md) |
| Giả định và phép tính vốn nhỏ | [economics.json](/home/hoangt/projects/quant/docs/2026-09-22/profitability-review/economics.json) |

Phân biệt bốn loại bằng chứng: hành vi đọc được trong code; số liệu trong artifact cũ; tuyên bố trong tài liệu; giả định minh họa. Không huấn luyện lại, không chạy lại toàn bộ backtest, không truy cập tài khoản sàn và không đặt lệnh. Không có database nến/funding đầy đủ hoặc config vận hành thực tế trong checkout để xác minh hệ thống đang chạy. Vì vậy, phát hiện về config nói đến **template/default**, không khẳng định cấu hình tài khoản của người dùng.

CodeGraph đã được khởi tạo theo yêu cầu: 208 files, 3.653 nodes, 8.814 edges. Beads không được sử dụng theo chỉ dẫn mới. Skill gstack `/browse` không có trong các đường dẫn đã kiểm tra; nguồn web được đọc bằng công cụ web sẵn có. Chỉ thay đổi tài liệu nghiên cứu và tạo chỉ mục cục bộ.

## 1. Bot đã chứng minh được bao nhiêu lợi nhuận?

| Bằng chứng | Số liệu hiện có | Có thể kết luận |
|---|---|---|
| Plan D, báo cáo khoảng sáu năm | Tổng return +65,58%; CAGR 8,81%; Sharpe 2,25; max DD 16,38%; 426 vị thế | Có giả thuyết đáng kiểm chứng; raw trades/equity và kết quả walk-forward đầy đủ không có trong checkout |
| ML/meta cũ, walk-forward run 1 | 213 trades; PF 0,659; Sharpe -2,47 | Bằng chứng bất lợi cho thí nghiệm ML/meta cũ, không phải kết quả của toàn bộ bot hiện tại |
| ML/meta cũ, run 2 | 181 trades; PF 0,478; Sharpe -6,26 | Thay đổi mô hình không tạo cải thiện trong summary đã lưu |
| Filter ablation | All filters: +36,2%; Sharpe 1,45; 427 trades | Có phí/slippage nhưng dùng toàn sample; không phải OOS độc lập |
| Funding snapshots | Ba snapshot: 0 trades, 0 PnL | Chưa có lợi nhuận giao dịch để đánh giá |
| Basis/MM/liquidation | Code, cấu hình, tài liệu | Chưa có track record ròng có thể đối soát |

Nguồn: [Plan D report](/home/hoangt/projects/quant/docs/2026-02-09/PLAN_D_PROGRESS.md:75), [run 1](/home/hoangt/projects/quant/results/walk_forward_summary.json:2), [run 2](/home/hoangt/projects/quant/results_v2/walk_forward_summary.json:2), [ablation](/home/hoangt/projects/quant/results/filter_ablation_1771110472.txt:5), [funding snapshot](/home/hoangt/projects/quant/stats_funding_arb_1771102578.json:2).

Không được diễn giải `overall_total_return` của ML/meta như mức lỗ tài khoản: script cộng lợi nhuận từng trade và chưa mô phỏng đầy đủ vốn dùng chung/overlap. Các Sharpe trong bảng cũng không đồng nhất cách tính, nên chưa dùng để xếp hạng trực tiếp. [Cách tính summary](/home/hoangt/projects/quant/scripts/walk_forward.py:521).

Các mục tiêu APY 15–30%, Sharpe 2–3 hoặc tuyên bố “thêm feature tăng PnL 20–40%” trong tài liệu cũ **chưa phải kết quả được kiểm chứng**. Báo cáo stress và survivorship có thành phần đơn giản hóa hoặc dữ liệu mô phỏng; không thể coi là proof bot chịu được khủng hoảng thật. IC -0,044 được nhắc trong tài liệu cũng chỉ là cảnh báo về tín hiệu, không đủ để suy ra PnL của toàn bộ lifecycle. [Chi tiết audit](/home/hoangt/projects/quant/docs/2026-09-22/profitability-review/evidence.md).

## 2. Những lỗi làm mất độ tin cậy của PnL

Các finding dưới đây được xác định bằng phân tích tĩnh; tác động cụ thể trên tài khoản thật chưa được thử nghiệm.

| Mức | Phát hiện | Ý nghĩa với lợi nhuận |
|---|---|---|
| P0 | Khi live và bật delta-neutral, funding runner dùng futures executor cho cả perp và “spot hedge”; basis live dùng spot executor cho cả hai chân | Bật cờ hedge chưa tạo ra spot + futures hedge đúng như mô hình kinh tế |
| P0 | Trend phát cả tín hiệu short nhưng setup live dùng spot executor | Chưa có đường short futures đúng; chỉ là ứng viên paper cho tới khi chọn và xác minh venue/side được hỗ trợ |
| P0 | `ClosePosition` ghi trade/PnL trước khi paper order được fill; một số đường funding/basis không mô phỏng fill entry | Giá/size có thể bằng 0; stats paper không phải kết quả đầu tư đáng tin |
| P0 | Limit close có thể được ghi nhận trước khi khớp; fallback chưa xử lý đầy đủ partial fill/cancel race | Trạng thái local có thể khác vị thế thật; có thể phát sinh exposure ngoài dự tính |
| P0 | MM ghi nhận một cặp buy/sell đã fill bằng cách gọi thêm lệnh close | Có thể tạo lệnh thứ ba và làm sai inventory/PnL |
| P1 | Funding được cộng theo lần quét thay vì event settlement | Với quét 5 phút và settlement 8 giờ, có thể đếm khoảng 96 payment thay vì 1; không phải tiền thực nhận |
| P1 | Thiếu đối soát balance/margin, exchange filters và startup positions/open orders | Risk budget, minimum order và recovery chưa phản ánh tài khoản vốn nhỏ |

Nguồn: [trend live setup](/home/hoangt/projects/quant/internal/bot/common.go:77), [trend signal](/home/hoangt/projects/quant/internal/strategy/trend.go:599), [funding runner](/home/hoangt/projects/quant/internal/bot/funding.go:37), [funding hedge](/home/hoangt/projects/quant/internal/strategy/funding_arb/strategy.go:321), [basis runner](/home/hoangt/projects/quant/internal/bot/basis.go:37), [paper orders](/home/hoangt/projects/quant/internal/execution/paper.go:26), [close accounting](/home/hoangt/projects/quant/internal/execution/engine.go:194), [MM recording](/home/hoangt/projects/quant/internal/strategy/market_making/strategy.go:698), [funding accrual](/home/hoangt/projects/quant/internal/strategy/funding_arb/strategy.go:408).

Funding thực tế phụ thuộc thời điểm settlement và notional; không cố định là ba kỳ mỗi ngày cho mọi trường hợp. Tài liệu Binance cho phép lịch 1h/4h/8h theo điều kiện hợp đồng. Vì vậy, sửa bằng cách chia cứng cho 96 vẫn chưa đủ; cần ledger event duy nhất. [Binance funding rules](https://www.binance.com/en/support/faq/detail/360033525031).

Template trend dùng equity 10.000 USD; funding/basis dùng position size 1.000 USD. Những con số này không phù hợp để giả lập tài khoản dưới 1.000 USD nếu giữ nguyên. Vốn cho hedge phải là **tiền mua spot + ký quỹ futures + dự phòng + phí**; gross notional của hai chân không đồng nghĩa tiền mặt cần nộp hai lần cộng thêm margin. [Risk defaults](/home/hoangt/projects/quant/internal/config/config.go:509), [funding template](/home/hoangt/projects/quant/config.example.funding.yaml:13), [basis template](/home/hoangt/projects/quant/config.example.basis.yaml:13).

## 3. Kinh tế của tài khoản 250–1.000 USD

Lợi nhuận tài khoản cần tính từ biến động equity theo giá thị trường, điều chỉnh nạp/rút, sau toàn bộ phí/funding/slippage. Lợi nhuận kinh tế còn phải trừ hạ tầng, dữ liệu và thời gian vận hành. Các phép tính dưới đây chưa gồm thuế và giả định USD/USDT ngang giá.

### Chi phí cố định đã tạo rào cản lớn

Tỷ suất chỉ để bù chi phí cố định = `12 × chi phí tháng / vốn đầu kỳ`:

| Vốn | 5 USD/tháng | 10 USD/tháng | 20 USD/tháng |
|---:|---:|---:|---:|
| 250 USD | 24%/năm | 48%/năm | 96%/năm |
| 500 USD | 12%/năm | 24%/năm | 48%/năm |
| 1.000 USD | 6%/năm | 12%/năm | 24%/năm |

Đây là kịch bản chi phí, không phải báo giá VPS hay dự báo lợi nhuận. Nếu tạm chấp nhận CAGR Plan D lịch sử 8,81% là tái lập được, phép nhân minh họa `8,81% × 500 USD` cho khoảng 44 USD/năm trước hạ tầng; 60 USD/năm tiền máy đã lớn hơn con số đó. Không thể dùng CAGR lịch sử này làm kỳ vọng hiện tại khi chưa tái lập.

### Turnover và minimum order

Biểu phí spot Binance hiện hiển thị regular maker/taker 0,1% mỗi lượt, trước ưu đãi. Một vòng mua-bán notional 100 USD tốn khoảng 0,20 USD; 20 vòng/tháng tốn khoảng 4 USD, chưa spread/slippage. Nếu vốn 500 USD và thêm 5 USD/tháng hạ tầng, riêng hai khoản đã là 1,8% vốn/tháng. [Binance spot fees](https://www.binance.com/en/fee/trading).

Partial exit nhỏ có thể vướng lượng tối thiểu, bước khối lượng hoặc minimum notional. Ví dụ giả định vốn 500 USD, rủi ro 0,25%, stop cách 2% cho vị thế 62,50 USD; chốt 10% chỉ còn 6,25 USD. Có đặt được hay không phải đọc filters của đúng symbol/product, không đoán một ngưỡng chung. [Binance filters](https://developers.binance.com/en/docs/products/spot/filters).

### Funding: notional APR khác lợi suất trên vốn

Kịch bản minh họa, **không phải forecast**: vốn 1.000 USD gồm 400 USD spot, 400 USD ký quỹ/dự phòng futures và 200 USD tiền mặt; short perp notional 400 USD. Giả định funding dương cố định 0,01% mỗi 8 giờ trong cả năm:

- Gross funding: `400 × 0,0001 × 3 × 365 = 43,80 USD`.
- 10,95%/năm trên notional chỉ là **4,38%/năm trên tổng vốn**; đây là lãi đơn, không phải APY tái đầu tư.
- Giả định một vòng mở/đóng hedge: spot 0,1%/fill và futures 0,05%/fill, tổng phí 1,20 USD.
- Sau hạ tầng 60 USD/năm: còn **-17,40 USD**, chưa basis movement, spread/slippage, liquidation và thuế.
- Với vốn 500 USD, notional mỗi chân 200 USD, cùng chi phí máy: **-38,70 USD**.

Futures 0,05% trong phép tính là mức **minh họa** ở FAQ, chưa xác minh commission tài khoản; trang fee futures không trả bảng mức phí trong lần đọc này. Funding không giữ nguyên và margin reserve không loại bỏ liquidation. [Binance fee calculation](https://www.binance.com/en/support/faq/detail/360033544231), [funding mechanics](https://www.binance.com/en/support/faq/detail/360033525031).

## 4. Đánh giá từng chiến lược

| Chiến lược | Lợi thế có thể có | Đánh giá với vốn dưới 1.000 USD |
|---|---|---|
| Trend cơ học | Tần suất thấp, quy tắc rõ, sizing theo rủi ro, không cần thắng về tốc độ | **Ưu tiên kiểm chứng paper**, một cặp và một hệ thống vốn chung; edge chưa chứng minh, short signal/live spot routing còn là blocker |
| Funding có hedge | Nguồn carry quan sát được, có thể giải thích dòng tiền | **Nghiên cứu sau khi sửa ledger/routing**; lợi nhuận tuyệt đối nhỏ, hedge chiếm vốn; bản không hedge là directional trade |
| Basis perpetual | Có thể hưởng thay đổi basis và funding | **Loại khỏi cấp vốn hiện tại**: công thức annualization sai ý nghĩa kinh tế, chi phí bốn fill và yêu cầu vốn |
| Market making | Thu spread nếu bù được inventory loss/adverse selection | **Không ưu tiên**: fill model thiếu queue/partial fills, accounting lỗi, cạnh tranh tổ chức mạnh |
| Mean reversion | Có thể phù hợp vốn nhỏ và giai đoạn đi ngang | Thư viện/research chưa có route bot hoàn chỉnh; lựa chọn symbol và xác suất thắng cần kiểm chứng |
| Momentum | Có thể giảm giao dịch ở tài sản yếu | Chưa tích hợp đầy đủ vào Go `OnBar`; kết quả Python chưa đủ chi phí |
| Liquidation cascade | Quan sát flow cưỡng bức | Hiện chủ yếu tín hiệu/log; cluster và long/short ratio là proxy, chưa có lifecycle giao dịch |
| Cross-exchange | Funding/price chênh giữa venue | Execution chưa hoàn chỉnh; vốn phân mảnh, thêm phí và recovery; **không phù hợp ưu tiên** |

Một lỗi basis đáng chú ý: code dùng `(1+basis)^(365×3)-1`. Ngưỡng “15% năm” tương đương premium tức thời chỉ **1,276 bps**; exit “5% năm” tương đương 0,446 bps. Nếu vào/ra đúng ngưỡng, chênh captured chỉ khoảng **0,831 bps**, trong khi kịch bản phí bốn fill ở trên là **30 bps trên notional một chân**, chưa trượt giá (không phải 30 bps trên tổng vốn). Perpetual không có ngày đáo hạn đảm bảo premium hội tụ; không thể mặc nhiên tái đầu tư premium này 1.095 lần/năm. [Code](/home/hoangt/projects/quant/internal/strategy/basis_trade/strategy.go:175), [đặc điểm perpetual](https://www.binance.com/en/blog/futures/2106113045523004581).

Tài liệu mô tả Plan D đầy đủ hơn đường Go hiện tại: entry chính dùng Donchian và EMA trend, trong khi crossover/volume không được áp dụng như mô tả; momentum có TODO chưa tích hợp. Điều này **không có nghĩa phải thêm mọi filter**: ablation cũ còn cho thấy crossover làm kết quả xấu hơn. Cần xác định chính xác chiến lược được thử và chiến lược được chạy rồi so sánh có đối chứng. [Go entry](/home/hoangt/projects/quant/internal/strategy/trend.go:592), [momentum TODO](/home/hoangt/projects/quant/internal/strategy/trend.go:633).

## 5. ML có tạo lợi thế cạnh tranh không?

**Chưa có bằng chứng tăng lợi nhuận ròng.** XGBoost cũ có train AUC khoảng 0,94–0,96 và OOS 0,54–0,61; giữ tắt là quyết định đúng. Regime SOL v1 có AUC 0,7567 trên 138 test entries, ETH v2 có AUC 0,695; đây là các tín hiệu khám phá, chưa chứng minh PnL của lifecycle có trailing, partial exit và phí. [Phân tích XGBoost](/home/hoangt/projects/quant/docs/2026-02-09/ML_MODEL_ANALYSIS.md:12), [SOL metadata](/home/hoangt/projects/quant/ml/models/regime_v1/SOLUSDT_meta.json:19), [ETH v2](/home/hoangt/projects/quant/ml/models/regime_v2/ETHUSDT_meta.json:21).

Các hạn chế chính: outcome window của nhãn có thể vượt ranh giới train/test; nhiều sự kiện dùng chung future bars; chọn threshold/model trên chính OOS đang báo cáo; SAFE-minus-DANGER win rate không phải net expectancy; HMM dùng feature và chuỗi đầu vào khác quá trình train. Volatility R² thấp không tự nó bác bỏ tính hữu ích, nhưng chưa có thử nghiệm chứng minh stop ML làm tăng lợi nhuận sau phí.

Template trend hiện thiếu `bar_size`, trong khi default là **1m**, và các cờ ML mặc định tắt. Nếu bật model 4H mà quên timeframe, dữ liệu runtime sai phân phối. Không có config vận hành để khẳng định lỗi này đang xảy ra trên tài khoản của người dùng. [Default config](/home/hoangt/projects/quant/internal/config/config.go:491), [audit ML](/home/hoangt/projects/quant/docs/2026-09-22/profitability-review/ml.md).

Với quy mô vốn này, ưu tiên sửa dữ liệu/PnL, parity và holdout trước; thêm HMM, ensemble hoặc dữ liệu trả phí chưa có luận cứ kinh tế.

## 6. Đối thủ: phần mềm và người cùng giao dịch

| Phương án | Chi phí và thế mạnh đã kiểm tra | Hàm ý cạnh tranh |
|---|---|---|
| Binance bots | Các sản phẩm grid/DCA/rebalancing/arb tích hợp; loại bỏ additional algo fees cho sản phẩm đủ điều kiện, vẫn có trading fees | Mạnh về tiện vận hành và chi phí; không thay thế trực tiếp logic Plan D tùy biến. [Nguồn](https://www.binance.com/en/support/announcement/detail/d51d8110eb4645278925193ee3d063fa) |
| Pionex | Built-in bots không có subscription riêng; spot standard được công bố 0,05%/fill | Rẻ cho grid/DCA; chưa có proof alpha phù hợp hơn trend của repo. [Bot fees](https://www.pionex.com/blog/is-there-any-fees-for-starting-a-bot-or-only-transaction-fees/), [fee table](https://www.pionexapp.com/en/fees) |
| 3Commas | Starter 20 USD/tháng hoặc 15 USD/tháng khi thanh toán năm; còn phí sàn | Riêng subscription bằng 48%/năm của 500 USD nếu trả tháng; không ưu tiên. [Pricing](https://3commas.io/pricing) |
| Freqtrade/FreqAI | Miễn phí, tùy biến, backtest/dry-run và ML; vẫn tốn máy và công bảo trì | Đối thủ gần nhất về công cụ nghiên cứu. Không cần chuyển framework nếu chưa sửa được phép đo PnL. [Docs](https://docs.freqtrade.io/en/stable/), [FreqAI](https://www.freqtrade.io/en/stable/freqai/) |
| Hummingbot | Open source cho MM/arb/connectors; vẫn chịu phí venue và vận hành | Mốc so sánh execution, không phải lời hứa lợi nhuận tự động. [FAQ](https://hummingbot.org/faq/) |
| Giữ BTC/ETH, tiền mặt, rule trend đơn giản | Ít giao dịch, không cần subscription | Các benchmark chi phí thấp bắt buộc; giữ coin vẫn chịu drawdown thị trường, tiền mặt/stablecoin không đồng nhất rủi ro |

Giá/phí là thông tin trang công khai tại lần nghiên cứu; sản phẩm, khuyến mại và điều kiện tài khoản/khu vực cần xác nhận riêng. Không nguồn nào trong tập này chứng minh net return đã kiểm toán đủ để xếp hạng lợi nhuận các bot. ROI leaderboard có thể khác cách tính funding, unrealized PnL và selection bias. [Binance bot metrics](https://www.binance.com/en/support/faq/detail/f0c2bd5bc16c40b9998d22549e91cd1c).

Đối thủ trong order book còn là các tổ chức như **Wintermute và GSR**, không chỉ phần mềm bán lẻ. Họ công bố hạ tầng giao dịch thuật toán, connectivity và cung cấp thanh khoản trên nhiều venue. Suy luận nghiên cứu: MM/arbitrage công khai, ngắn hạn là sân chơi khó cho bot vốn nhỏ thiếu queue model và kiểm soát inventory. Đây là so sánh năng lực được công bố, không phải nhận định về PnL riêng của họ. [Wintermute](https://www.wintermute.com/algorithmic-trading), [GSR](https://www.gsr.io/services/markets).

Lợi thế có thể xây của bot là khả năng kiểm soát toàn bộ quy tắc, tận dụng quy mô nhỏ và kiểm chứng minh bạch ở horizon chậm. Donchian, EMA hay tên “Avellaneda–Stoikov” đều không tự tạo lợi thế độc quyền. Ở dưới 1.000 USD, chi phí tối thiểu và độ đúng của hệ thống đáng ưu tiên hơn capacity lớn hay tối ưu tốc độ.

## 7. Kế hoạch nghiên cứu tiếp theo và điều kiện dừng

Đây là backlog đề xuất, **chưa triển khai**, không dùng Beads và không cấp quyền chuyển live.

| Ưu tiên | Công việc độc lập | Bằng chứng hoàn thành |
|---|---|---|
| P0-A | Fill lifecycle và ledger PnL | Trade entry 100 → exit 110, size 1, fee 0 phải ghi +10; partial/cancel/retry không tạo phantom trade; MM không thêm lệnh thứ ba |
| P0-B | Spot/futures routing và hedge recovery | Fake-executor xác nhận venue từng chân; hedge lỗi không báo neutral; state gắn actual fills |
| P0-C | Funding settlement | N lần poll qua một settlement chỉ ghi đúng một payment; nhận và trả funding đều đối soát được |
| P0-D | Vốn 250/500/1.000, filters và recovery | Equity dùng chung, không vượt cash/margin; lệnh nhỏ xử lý tick/step/notional; restart đối soát orders/positions |
| P1-A | Một baseline trend cơ học, timeframe rõ | Go và nghiên cứu phát cùng tín hiệu; entry sau signal, cùng rules exit và cost model |
| P1-B | Holdout và benchmark | Equity curve có phí, funding, spread, slippage; cùng giai đoạn và vốn; trial log, purge và các cửa sổ bull/bear/sideways |
| P1-C | Forward paper tối thiểu 8–12 tuần | Trade/fill ledger không lệch, measured slippage, đủ số giao dịch và khoảng tin cậy; thời gian này chỉ là kiểm tra vận hành, không tự chứng minh alpha |
| P2 | Funding có hedge hoặc ML ablation | Chỉ mở rộng sau baseline; đánh giá lợi nhuận tăng thêm sau chi phí toàn bộ vốn |

Benchmark bắt buộc: tiền mặt không lãi làm control kế toán; BTC/ETH buy-and-hold; một trend đơn giản không ML; Plan D đúng production. Native grid chỉ so sánh khi có ledger cùng thời gian, universe và capital constraints. Bot không nhất thiết phải thắng BTC ở mọi thị trường: có thể đáng dùng nếu giảm drawdown rõ rệt với mức return chấp nhận được, sau điều chỉnh exposure/risk.

Báo cáo kết quả cần có net PnL bằng USD và %, daily marked-to-market equity, drawdown/time-under-water, turnover, fee/funding decomposition, exposure, số giao dịch thực và confidence interval bằng block bootstrap. Với crypto dùng tần suất thời gian phù hợp; không annualize chuỗi trade không đều bằng `sqrt(252)` như daily returns. 30 hay 100 trades không tự động đủ ý nghĩa thống kê; số mẫu hiệu dụng còn phụ thuộc overlap, serial correlation và regime.

Điều kiện để cân nhắc lại: không còn blocker accounting/execution; có net expectancy OOS dương với độ bất định được báo cáo; chịu được stress chi phí gấp đôi; thêm lợi ích rõ so với benchmark ở mức rủi ro tương đương. Nếu interval còn bao gồm 0, kết luận là **chưa đủ bằng chứng**, không tăng leverage để bù lợi nhuận thấp. Nếu chi phí cố định ăn hết lợi nhuận thực chứng, dừng nhánh đó hoặc giữ làm dự án học tập.

## Giới hạn và bàn giao

Kết quả trên là audit mã nguồn, metadata và nghiên cứu nguồn chính thức, không phải certification bảo mật hoặc replay thị trường mới. Không biết phí tài khoản thật, quyền dùng futures, chế độ position, chi phí máy thực tế hoặc nghĩa vụ thuế cá nhân; không suy ra nơi cư trú từ múi giờ máy. Chưa có cơ sở để đưa ra một APY tương lai đáng tin cậy.

Không thay đổi strategy, model, API keys, dữ liệu hoặc trading mode. Không gửi Telegram vì môi trường không có token/chat ID cho skill thông báo. Các tài liệu hardening có sẵn và thay đổi của người dùng được giữ nguyên.
