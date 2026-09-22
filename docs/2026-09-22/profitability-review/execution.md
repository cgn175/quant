# Quant bot — audit execution/accounting/operations

Phạm vi: internal/execution, các runner, risk, exchange adapters và lifecycle của funding arb, basis trade, market making. Đây là audit chỉ đọc; mỗi finding phân biệt hành vi đã xác minh trong code với tác động cần kiểm chứng trên testnet. Kết luận đặt cho vốn riêng dưới 1.000 USD.

## Kết luận vận hành

Chưa có cơ sở để coi PnL paper là PnL có thể chuyển sang live. Có nhiều blocker P0:

1. Funding arb và basis trade không tách được spot executor với futures executor. Funding live dùng futures executor cho cả lệnh hedge gọi là spot; basis live dùng spot executor cho cả lệnh short perp.
2. Paper market order trả về NEW/FilledPrice=0; execution engine ghi trade trước khi caller mô phỏng fill. Hầu hết đường đóng vị thế của funding/basis/MM không gọi mô phỏng fill. Stats paper vì thế sai nghiêm trọng.
3. Lệnh đóng live không có poll/fallback khi UseLimitOrders=true; engine có thể ghi vị thế đã đóng trong khi GTC order vẫn chưa fill.
4. Không có account/balance/margin/liquidation/order-filter reconciliation. Funding, basis và MM không dùng risk.Manager; vị thế mặc định còn là 1.000 USD mỗi leg.
5. Cross-exchange funding chỉ ghi log, không đặt lệnh; cross-exchange basis có manager nhưng không được gọi trong loop.
6. Restart/crash không khôi phục hoặc đối soát trend/MM live orders/positions; funding/basis chỉ restore DB nội bộ, không đối soát exchange.

Với vốn dưới 1.000 USD, cấu hình mẫu đã yêu cầu 1.000 USD mỗi vị thế (funding/basis) và cấu hình risk mặc định khởi tạo equity 10.000 USD. Đây là sai số quy mô đủ lớn để lệnh live bị reject, hoặc để bot đánh giá rủi ro/liquidation thấp hơn nhiều so với vốn thật.

## Findings

### P0 — venue/leg routing làm hỏng chiến lược

#### P0-1 — Funding delta-neutral không có spot leg thật. [Đã xác minh]

- internal/bot/funding.go:37-45 tạo duy nhất execution.NewLiveFuturesExecutor ở live.
- internal/strategy/funding_arb/strategy.go:321-335 đặt perp entry qua s.executor.
- internal/strategy/funding_arb/strategy.go:337-359 gọi chính s.executor lần nữa cho “spot hedge”.
- internal/execution/live.go:179-201 route mọi market order của futures tới /fapi/v1/order và :186-189 luôn gửi positionSide=BOTH; limit order cũng route futures ở :204-227.

Vì vậy khi delta_neutral=true, cả hai leg là futures cùng symbol. Tác động “lệnh ngược có thể net/reduce vị thế futures one-way thay vì mua spot” là suy luận theo semantics Binance và cần canary testnet; route sai venue đã được xác minh. Cùng lỗi lúc đóng ở strategy/funding_arb/strategy.go:514-526 và shutdown :725-737.

delta_neutral mặc định là true ở internal/config/config.go:598-606, dù file mẫu funding đặt false ở config.example.funding.yaml:19-23. Khi hedge bị xem là tồn tại, managePosition còn bỏ qua MaxLossPct ở strategy/funding_arb/strategy.go:439-452; route hedge sai có thể tắt luôn lớp bảo vệ directional loss.

#### P0-2 — Basis trade live không đặt perp short. [Đã xác minh]

- internal/bot/basis.go:37-46 dùng execution.NewLiveExecutor, constructor mặc định marketType=spot ở internal/execution/live.go:25-34.
- internal/strategy/basis_trade/strategy.go:248-260 gọi cùng executor cho spot buy rồi “short perp”.
- internal/execution/live.go:191-201 xác nhận executor này dùng /api/v3/order spot.

Lệnh thứ hai là spot sell, không phải futures short. Entry live không capture basis và không có cash-and-carry delta-neutral. Đường đóng strategy/basis_trade/strategy.go:327-355 tiếp tục bán/mua spot và ghi trạng thái basis như đã đóng; nếu leg spot fail, code chỉ log rồi tiếp tục.

#### P0-3 — Cross-exchange không tạo vị thế thật. [Đã xác minh]

- Funding chỉ bỏ qua Binance trong internal/strategy/funding_arb/strategy.go:78-108 (log “already available”, không AddExchange); nếu cấu hình chỉ có Binance + exchange khác thì manager thiếu một data source.
- strategy/funding_arb/strategy.go:614-645 tạo arbPosition, log TODO “Execute orders on both exchanges”, rồi vẫn đưa position vào memory và portfolio monitor mà không gọi PlaceOrder.
- strategy/funding_arb/strategy.go:683-705 đóng cũng chỉ log, không có lệnh.
- Basis khởi tạo crossExchangeManager ở internal/strategy/basis_trade/strategy.go:64-94, nhưng scanAndManage ở :175-214 không đọc field này; manager không bao giờ được dùng.

Bất kỳ backtest/metric nào tính spread cross-exchange vì thế không chứng minh khả năng thực thi.

### P0 — paper/live fill và PnL không cùng semantics

#### P0-4 — Engine ghi exit trước khi paper fill. [Đã xác minh]

- internal/execution/paper.go:26-57 cố ý trả market order NEW với FilledPrice=0; caller phải gọi SimulateFill ở :130-159.
- internal/execution/engine.go:194-247 gọi executor, sau đó ngay lập tức tính fee/PnL từ order.FilledPrice và append Trade; không kiểm tra status và không chờ fill.
- Trend gọi SimulateFill sau engine ở internal/bot/trend.go:619-632, nên trade đã ghi vẫn giữ exit price 0/PnL sai.
- Funding đóng qua engine ở internal/strategy/funding_arb/strategy.go:496-512 nhưng không gọi SimulateFill.
- Basis đóng qua engine ở internal/strategy/basis_trade/strategy.go:334-345 nhưng không gọi SimulateFill.
- MM recordRoundTrip gọi engine ở internal/strategy/market_making/strategy.go:705-717 nhưng cũng không mô phỏng fill.

Ví dụ deterministic: long entry 100, size 1, exit signal 110, zero fee. Engine.ClosePosition ghi trade với exit 0 và gross PnL -100; caller mô phỏng 110 chỉ sửa object order, không sửa trade đã append. Vì vậy GetTradeStats, saveStats và Prometheus trade metrics không thể dùng làm bằng chứng cạnh tranh lợi nhuận.

#### P0-4a — Funding/basis paper entry cũng không mô phỏng fill. [Đã xác minh]

- PaperExecutor yêu cầu caller gọi SimulateFill; các call site hiện có chỉ ở internal/bot/trend.go:573-575, :628-630, :679-681 và internal/bot/ml.go:366, :415, :489, :544.
- Funding tạo pos từ order.FilledPrice/FilledSize ngay sau ExecuteMarketOrder ở internal/strategy/funding_arb/strategy.go:321-335, không SimulateFill.
- Basis tạo cả spot/perp position từ FilledPrice/FilledSize ở internal/strategy/basis_trade/strategy.go:248-272, không SimulateFill.

Vì vậy paper funding/basis có thể lưu entry price/size bằng 0, hedge size bằng 0, rồi ghi DB/memory như đã mở. Khi đóng, size 0 làm executor paper trả lỗi; nếu đường đóng vẫn ghi trade thì PnL/position state càng lệch. Đây là lý do paper carry/basis không dùng được để suy ra cash PnL.

#### P0-5 — Đóng limit live có thể là “đã đóng” giả. [Đã xác minh]

- internal/execution/engine.go:205-209 dùng ExecuteLimitOrder khi UseLimitOrders=true.
- internal/execution/engine.go:215-247 không poll, không cancel/fallback và không kiểm tra FILLED/REJECTED; vẫn ghi trade từ FilledPrice có thể bằng 0.
- config.example.trend.yaml:48-52 bật use_limit_orders=true và đặt aggressive timeout 3 giây, nhưng timeout chỉ được dùng trong OpenPosition ở engine.go:123-126; close không dùng ExecuteAggressiveLimitOrder.

Ở live, strategy/risk state có thể bị xoá sau một GTC close chưa fill, còn order thật vẫn mở. Với trend, đường gọi cụ thể là internal/bot/trend.go:611-655; funding/basis/MM cũng dùng cùng engine.

#### P0-6 — Aggressive limit fallback có race/overfill. [Đã xác minh]

- internal/execution/engine.go:166-181 poll trạng thái rồi hết hạn.
- :183-191 bỏ qua lỗi CancelOrder và lập tức gửi market full size; không query lại order sau cancel.
- internal/execution/live.go:144-147 map PARTIALLY_FILLED thành internal OrderStatusNew nhưng giữ FilledSize ở :169-172.
- internal/bot/trend.go:577-595 chỉ kiểm tra FilledPrice, sau đó đăng ký full requested size, không dùng FilledSize.

Nếu limit đã fill một phần hoặc fill trong race cancel/fallback, account có thể có partial + full market fill, còn risk state chỉ biết một vị thế size khác thực tế.

Funding/basis entry cũng không kiểm tra OrderStatus sau market order: funding lấy order.FilledSize ở strategy/funding_arb/strategy.go:328-359, còn basis vẫn gửi leg perp theo requested size ở strategy/basis_trade/strategy.go:248-272. Với response partial/NEW, hedge ratio có thể lệch hoặc entry zero; live parser đã biến PARTIALLY_FILLED thành internal NEW ở live.go:144-147.

#### P0-7 — MM round-trip phát sinh lệnh thứ ba. [Đã xác minh]

- internal/strategy/market_making/strategy.go:650-695 phát hiện buy và sell đã fill, đồng thời cập nhật inventory.
- Ngay sau đó :705-717 gọi execEngine.ClosePosition với side=LONG. ClosePosition luôn đặt thêm close order ở internal/execution/engine.go:205-209.

Vậy một buy + sell đã hoàn tất vẫn tạo thêm sell (live là lệnh thật; paper là lệnh NEW không được mô phỏng). Đây vừa là rủi ro inventory vừa làm PnL/stats sai.

### P1 — accounting/carry làm PnL bị thổi phồng hoặc bỏ sót

#### P1-1 — Funding collection đếm theo scan, không theo funding event. [Đã xác minh]

- internal/strategy/funding_arb/strategy.go:408-423 cộng payment mỗi lần managePosition chạy nếu funding còn cùng dấu, rồi tăng FundingPayments.
- :169-189 tạo ticker theo ScanIntervalMs.
- Default là 300.000 ms ở internal/config/config.go:598-604; config mẫu cũng là 300.000 ms ở config.example.funding.yaml:19-23.
- FundingRateInfo có FundingTime ở internal/exchange/types.go:76-82 nhưng strategy không dùng field này để gate payment.

Với lịch funding 8 giờ, scan 5 phút có thể đếm khoảng 96 payment cho một funding event; đây là lỗi PnL carry, không chỉ sai reporting. Lịch thực tế có thể 1h/4h/8h theo symbol/exchange, nên tỷ lệ overcount cần kiểm tra theo event ledger.

#### P1-2 — Funding/basis leg fees và funding không vào cùng sổ PnL. [Đã xác minh]

- internal/execution/engine.go:219-247 chỉ tính fee cho entryPrice/exitPrice của một trade size.
- Funding tính totalPnL gồm perp, spot và FundingCollected chỉ để log ở internal/strategy/funding_arb/strategy.go:535-566; không đưa vào Engine.Trade.
- Spot hedge close ở :514-526 gọi executor trực tiếp, không ghi spot fee/fill vào engine.
- Basis log tổng spot + perp PnL ở internal/strategy/basis_trade/strategy.go:357-369, nhưng engine chỉ ghi perp close; basis funding carry không được tính.

Do đó stats JSON (internal/bot/stats.go:30-62) và metrics không phải net account PnL. Trong paper, spot/perp còn bị giả lập cùng một executor nên không có fee/margin ledger riêng cho từng leg.

#### P1-3 — Paper limit fill quá lạc quan cho market making. [Đã xác minh]

- internal/execution/paper.go:92-127 fill toàn bộ limit order ngay khi market price (mid từ s.prices) chạm limit, với giá limit.
- internal/strategy/market_making/strategy.go:658-665 gọi TryFillLimitOrder bằng mid-price; không có queue position, depth consumption, partial fill, latency, cancellation race hay adverse selection.
- Live refresh cancel/requote mỗi vòng ở :454-465, nhưng partial fill không được xử lý ở :674-695.

Kết quả MM paper không phải lower bound cho live; nó thường giả định fill thuận lợi và bỏ sót inventory markout.

#### P1-4 — Backtest bỏ qua entry slippage. [Đã xác minh]

- internal/backtest/engine.go:494-509 ghi entry tại bar.Close, không áp dụng SlippageBP.
- :517-530 chỉ trừ exitSlippage và hai phía fee.

Backtest vì vậy không khớp paper/live market fill, nhất là với strategy turnover cao. ExecutionConfig.Mode ở :78-83 không có nhánh xử lý trong execution path.

### P1 — account, margin và sizing không phản ánh vốn dưới 1.000 USD

#### P1-5 — Không có account/balance/margin/liquidation reconciliation. [Đã xác minh]

- Executor chỉ có market/limit/cancel/get-order/close ở internal/execution/engine.go:65-71; không có account balance, positions, open-order listing, margin, leverage, liquidation hoặc exchange-info filter.
- internal/execution/live.go:179-264 chỉ thực hiện order endpoints; không có account/position-risk calls và Close() là no-op ở :266-268.
- risk.Manager khởi tạo equity từ config ở internal/risk/manager.go:56-63, tính size từ equity nội bộ ở :72-103, và chỉ giới hạn notional của positions đã đăng ký ở :110-225.
- Trend tạo risk manager ở internal/bot/common.go:63-74; funding/basis/MM runners không tạo risk manager (internal/bot/funding.go:69-94, internal/bot/basis.go:70-95, internal/bot/mm.go:34-68).

Risk này không bảo vệ funding/basis/MM khỏi thiếu balance hoặc liquidation. MaxLeverage chỉ là gate in-memory; bot không gửi leverage/initial-margin setting hay đọc maintenance margin từ exchange.

#### P1-6 — Default equity và position size lớn hơn vốn mục tiêu. [Đã xác minh + suy luận tác động]

- internal/config/config.go:71-78 default InitialEquity() về 10.000 USD.
- internal/config/config.go:509-513 default risk initial equity 10.000 USD.
- config.example.trend.yaml:41-46 đặt initial equity 10.000 USD.
- config.example.funding.yaml:13-23 đặt position size 1.000 USD; config.example.basis.yaml:13-35 cũng đặt 1.000 USD; funding/basis không dùng risk equity.
- Market-making default order_amount=0.01, max_inventory=1.0 ở internal/config/config.go:575-580; đây là guard inventory nội bộ, không phải available balance.

Với vốn thật dưới 1.000 USD, một funding/basis vị thế 1.000 USD đã chạm hoặc vượt toàn bộ vốn cho một leg; delta-neutral cần thêm leg spot và margin. Đây là suy luận vốn/liquidation cần xác nhận bằng balance và filter thật, nhưng code hiện không có cơ chế tự phát hiện.

#### P1-7 — Quantity/price không được chuẩn hoá theo exchange filters. [Đã xác minh]

- internal/execution/live.go:179-185 gửi raw float quantity.
- :204-212 gửi raw float quantity và price.
- Không có exchangeInfo, LOT_SIZE, PRICE_FILTER, MIN_NOTIONAL, tick/step rounding hoặc fee-tier lookup trong live executor hay Executor.

Các lệnh size nhỏ có thể bị Binance reject; làm tròn thủ công gây sai notional/hedge ratio. Bybit/OKX adapters cũng không giải quyết được route chính: internal/exchange/bybit.go:263-277 cố định qty 4 decimals; internal/exchange/okx.go:255-275 dùng instrument SWAP và sz integer contracts, không có mapping asset quantity.

#### P1-8 — Close order không reduceOnly. [Đã xác minh]

internal/execution/live.go:179-215 chỉ gửi side, quantity và (futures) positionSide=BOTH; không gửi reduceOnly. Nếu state local lệch account, close có thể mở/reverse exposure thay vì chỉ giảm vị thế. Cần test bằng account position mode thật trước khi coi lifecycle an toàn.

### P1 — restart, partial leg và state desync

#### P1-9 — Trend/MM không restore exchange state sau restart. [Đã xác minh]

- Trend chỉ load candle history ở internal/bot/trend.go:94-108; không persist/restore RiskManager positions.
- Engine orders/trades chỉ nằm trong memory (internal/execution/engine.go:81-96).
- MM chỉ huỷ order đang có trong map local ở internal/strategy/market_making/strategy.go:735-742; không query/cancel GTC orders từ process trước và không restore inventory.
- Live executor không có reconciliation API (internal/execution/live.go:248-268 chỉ get một order theo id rồi Close no-op).

Crash/SIGKILL có thể để lại GTC order hoặc futures position mà process mới không biết.

Graceful shutdown cũng không có giá live đáng tin: common.go:179-215 lấy EntryPrice nếu RiskManager.UnrealizedPnL bằng 0, gọi Engine.ClosePosition nhưng không SimulateFill cho paper, rồi cập nhật risk equity bằng exitPrice ước lượng. Trend không gọi UpdatePositionPnL trong handleTrendTick (trend.go:481-505); các snapshot ở common.go:240-258 vì vậy có thể báo unrealized PnL bằng 0 khi vị thế đang lỗ.

#### P1-10 — Funding/basis DB restore không đối soát exchange và không atomic hai leg. [Đã xác minh]

- Funding restore chỉ đọc LoadOpenPositions ở internal/strategy/funding_arb/strategy.go:122-166; không gọi exchange account/order/position và không đăng ký lại exposure với PortfolioMonitor.
- Basis restore tương tự ở internal/strategy/basis_trade/strategy.go:99-149.
- Funding đặt các leg trước rồi mới SavePosition ở :321-374; basis làm vậy ở :248-286. Crash/network failure giữa các bước tạo orphan leg không có DB record.
- Nếu SavePosition lỗi, funding/basis chỉ log rồi vẫn đưa position vào map (funding_arb/strategy.go:362-382, basis_trade/strategy.go:274-294).
- Khi đóng, spot-leg failure chỉ log rồi state/DB vẫn có thể bị xoá/đóng: funding :514-574, basis :327-377.
- Shutdown raw close errors chỉ log nhưng vẫn mark DB closed/reset map (funding_arb/strategy.go:707-748, basis_trade/strategy.go:380-406).

arb_positions không có strategy/venue/leg identifier ở internal/data/funding_store.go:60-89; basis và funding dùng chung schema và LoadOpenPositions ở :244-272. Nếu dùng chung DB/path, basis có thể restore funding position có SpotSize>0, vì không có cột loại strategy.

### P2 — portfolio guard không phản ánh gross capital

#### P2-1 — Monitor tính một notional cho hai leg và không shared giữa process. [Đã xác minh]

- Funding đăng ký notional=size*markPrice một lần ở internal/strategy/funding_arb/strategy.go:384-391.
- Basis đăng ký một lần ở internal/strategy/basis_trade/strategy.go:296-299.
- PortfolioMonitor chỉ cộng exposure đã đăng ký ở internal/risk/portfolio_monitor.go:253-272.
- Mỗi runner tự tạo monitor riêng (internal/bot/funding.go:76-94, internal/bot/basis.go:77-95); không có shared store/IPC.

Vì vậy delta-neutral gross legs và cross-process funding+basis overlap không được phản ánh đầy đủ. Correlated check chỉ có tác dụng khi cùng một monitor object.

## Verified behavior vs speculation

Đã xác minh trực tiếp từ code: route endpoint spot/futures; paper order status; engine ghi trade trước fill; close limit không chờ fill; fallback bỏ qua cancel; funding/basis/MM không dùng account risk; cross-exchange không execute; thiếu filter/balance/reconciliation; state persistence chỉ một phần.

Cần xác nhận ở testnet/live-read-only trước khi kết luận tác động cụ thể: Binance account one-way hay hedge mode; lệnh futures đối ngược sẽ net thế nào; actual commission/funding ledger; exchange min-notional/step-size cho từng symbol; partial fill/cancel race; lệnh GTC còn tồn sau crash. Không dùng API key hoặc đặt trade để chứng minh các điểm này trong audit.

## Blockers trước khi đánh giá cạnh tranh lợi nhuận

1. Tách SpotExecutor và FuturesExecutor, kèm venue/account/leg metadata; basis/funding chỉ ghi position sau khi cả hai leg đã xác nhận FILLED hoặc có hedge-recovery state.
2. Thiết kế execution state machine có idempotency, partial-fill handling, cancel/replace reconciliation, reduce-only close và startup recovery.
3. Sửa paper ledger: fill trước, fee từng fill/leg, funding theo event timestamp, balance/margin/liquidation và trade stats sau fill; test expected PnL với một trade đơn giản.
4. Đồng bộ account equity thật, available margin, leverage/maintenance margin, exchange filters và fee tier; sizing theo vốn thực dưới 1.000 USD.
5. Vô hiệu hoá cross-exchange cho tới khi có executor thật cho từng exchange; không ghi opportunity thành active position.
6. Thêm kill/restart canary trên testnet: mở tiny order, SIGKILL, restart, list account/open orders/positions, rồi chỉ coi recovery đạt khi local state khớp exchange.

## Cheap validation actions

- Fake executor smoke test: assert funding delta-neutral emits two futures calls, basis emits two spot calls, and MM completed buy+sell emits no third order. Đây là test không chạm network.
- Paper accounting smoke test: entry 100, exit 110, size 1, fee/slippage 0; assert recorded trade exit=110/PnL=10. Current code should fail because Engine records exit=0 before SimulateFill.
- Read-only exchange audit: query account balances, open orders, positions/position mode, exchangeInfo filters, commission and funding history; compare với config và DB. Không đặt lệnh.
- Funding ledger test: chạy qua đúng một FundingTime, kiểm tra một payment event trong ledger và so với FundingPayments; scan count không được dùng thay ledger.
- MM replay test: replay L2/trades with queue/partial-fill/markout windows 1s/5s/30s, rồi compare paper mid-touch fills.
- Crash test: use an isolated testnet account and testnet GTC order, kill the process, restart, and verify startup cancels/reconciles it; no live orders are authorized by this research; current implementation has no startup path for this.

## Cost intuition cho vốn mục tiêu

Repository examples use fee_percent=0.04 and slippage_bp=5 for funding/basis (config.example.funding.yaml:45-47, config.example.basis.yaml:37-39). A real two-leg round trip has four fills; at 0.04% fee alone, a position with 1.000 USD notional per leg (2.000 USD gross exposure) costs about 1.60 USD before slippage. At 0.01% funding per 8h, one 1.000 USD perp leg yields only about 0.30 USD/day gross under an 8h schedule, so fees alone consume several days of carry. Đây là illustration từ assumptions trong repo; fee tier, maker/taker result và funding interval thật phải đọc từ account/exchange.


## Peer-review bổ sung: Trend short / live spot routing

`internal/bot/common.go:77-84` luôn tạo `NewLiveExecutor` dạng spot trong live setup, trong khi `internal/strategy/trend.go:599-626` phát cả `SignalShort`. Lệnh live đi tới `/api/v3/order`; vì vậy khả năng short futures của trend chưa có trong đường runner này. Trend vẫn chỉ là ứng viên paper; trước mọi cân nhắc live phải xác minh executor đúng sản phẩm hoặc định nghĩa rõ một biến thể long-only spot và kiểm chứng lại. Chưa thực hiện giao dịch để xác minh tác động tài khoản.
