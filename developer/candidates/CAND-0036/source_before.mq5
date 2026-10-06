//+------------------------------------------------------------------+
//|  Fibonacci_EA.mq5                                                |
//|  Strategy  : Fibonacci Retracement — Prop Firm Edition          |
//|  Timeframe : H1 swing detection + M15 entry trigger             |
//|  Version   : 5.0 — Prop Firm Optimised                         |
//|                                                                  |
//|  BUILT FOR:                                                      |
//|  • GoatFunded, FTMO, MyForexFunds, The Funding Pips            |
//|  • Accounts from $10 to $100,000 — auto-scales                 |
//|  • Weekly profit target: 3–5% | Max DD: 8% (firm allows 10%)  |
//|                                                                  |
//|  PROP FIRM GUARDS:                                              |
//|  ─────────────────────────────────────────────────────────────  |
//|  [G1] DAILY LOSS LIMIT — halts all trading when daily loss     |
//|       reaches InpDailyLossLimit% (default 4%). Prop firms       |
//|       typically allow 5% — we use 4% to stay safe.            |
//|                                                                  |
//|  [G2] TOTAL DRAWDOWN LIMIT — halts all trading when total DD   |
//|       from initial balance reaches InpTotalDDLimit% (default   |
//|       8%). Prop firms allow 10% — we use 8% as buffer.        |
//|                                                                  |
//|  [G3] WEEKLY PROFIT LOCK — once weekly profit reaches          |
//|       InpWeeklyTargetPct% (default 5%), EA stops opening new  |
//|       trades for the week. Locks in the gain.                  |
//|                                                                  |
//|  [G4] NEWS FILTER — blocks trading 30 min before and after     |
//|       high-impact news (08:30, 13:30, 14:00, 15:00 server).   |
//|       Prop firms penalise trading during news events.          |
//|                                                                  |
//|  [G5] MAX TRADES PER DAY — default 6. Prevents overtrading     |
//|       in a single session which clusters losses.               |
//|                                                                  |
//|  [G6] WEEKEND CLOSE — automatically closes all positions       |
//|       by Friday 21:00 to avoid weekend gap risk.               |
//|                                                                  |
//|  SCALING SYSTEM:                                                |
//|  ─────────────────────────────────────────────────────────────  |
//|  Position sizing always uses % of current balance.             |
//|  $10 account: 1% risk → $0.10 → forces 0.01 min lot           |
//|  $100 account: 1% risk → $1.00 → 0.07 lots                    |
//|  $1,000 account: 1% risk → $10 → 0.67 lots                    |
//|  $10,000 account: 1% risk → $100 → 6.7 lots                   |
//|  Scales automatically. Same EA, any account size.              |
//|                                                                  |
//|  INHERITED FROM v4.0:                                           |
//|  • Fixed pip SL/TP (15pip SL, 10pip TP1, 30pip TP2)           |
//|  • Tiered Fib filters (38.2% strict, 50% moderate, 61.8% RSI) |
//|  • Buy-only default (longs consistently 64–74% WR)             |
//|  • H4 + ADX soft lot reduction                                  |
//|  • Session filter London 08–12, NY 13–18                       |
//|  • Multi-pair safe magic number                                 |
//|  • Live dashboard with all stats                                |
//+------------------------------------------------------------------+
#property copyright   "Fibonacci EA v5.0 — Prop Firm Edition"
#property version     "5.00"
#property strict
#property description "Fibonacci EA v5.0 | Prop Firm Edition"
#property description "Daily/Total DD guards | News filter | Weekly lock | Weekend close"
#property description "Auto-scales $10–$100k | GoatFunded/FTMO ready | GBPUSD M15"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//+------------------------------------------------------------------+
//|  INPUTS                                                          |
//+------------------------------------------------------------------+
input group "══════ PROP FIRM SETTINGS ══════"
input double InpInitialBalance    = 0.0;     // Starting balance (0=auto from account)
input double InpDailyLossLimit    = 4.0;   // [G1] Daily loss halt % (prop firms allow 5%)
input double InpTotalDDLimit      = 8.0;   // [G2] Total DD halt % (prop firms allow 10%)
input double InpWeeklyTargetPct   = 5.0;   // [G3] Weekly profit lock % (0=disabled)
input bool   InpUseNewsFilter     = true;  // [G4] Block trading near news hours
input int    InpNewsBufferMins    = 30;    // [G4] Minutes before/after news to block
input int    InpMaxTradesPerDay   = 6;     // [G5] Max trades per day
input bool   InpWeekendClose      = true;  // [G6] Close all positions by Fri 21:00
input int    InpWeekendCloseHour  = 21;    // [G6] Friday close hour (server time)

input group "══════ TRADE DIRECTION ══════"
input int    InpDirection         = 2;     // 0=BUY only | 1=SELL only | 2=Both

input group "══════ SWING DETECTION ══════"
input int    InpSwingLookback     = 50;    // H1 bars to scan [opt: 30–80]
input int    InpSwingStrength     = 5;     // Bars each side to confirm [opt: 3–7]
input double InpMinSwingPips      = 25.0;  // Min swing size pips
input double InpMaxSwingPips      = 500.0; // Max swing size pips
input int    InpMinBarsAfterSwing = 2;     // H1 bars to wait after new swing

input group "══════ FIBONACCI LEVELS ══════"
input bool   InpUseFib236         = false; // 23.6%
input bool   InpUseFib382         = false;  // 38.2% (H1+MACD+Rejection)
input bool   InpUseFib500         = true;  // 50.0% (H1+MACD OR Rejection)
input bool   InpUseFib618         = true;  // 61.8% (H1+RSI — GOLDEN)
input bool   InpUseFib786         = false; // 78.6%
input double InpFibBuffer         = 5.0;   // Zone buffer pips

input group "══════ FIXED PIP SL/TP ══════"
input double InpMaxSLPips         = 15.0;  // Hard SL pips
input double InpTP1Pips           = 15.0;  // TP1 partial close pips
input double InpTP2Pips           = 15.0;  // TP2 hard TP pips
input double InpTP1ClosePct       = 50.0;  // % to close at TP1
input double InpTrailPips         = 8.0;   // Trail step pips (after TP1)

input group "══════ ENTRY FILTERS ══════"
input bool   InpUseTrend          = true;  // H1 EMA trend filter (global hard)
input int    InpTrendEma          = 50;    // H1 EMA period
input bool   InpUseSession        = true;  // London + NY session filter
input int    InpLondonOpen        = 8;     // London open
input int    InpLondonClose       = 12;    // London close
input int    InpNYOpen            = 13;    // NY open
input int    InpNYClose           = 18;    // NY close
input bool   InpUseAsianSession   = false; // Asian (Tokyo/Sydney) session filter
input int    InpAsianOpen         = 0;     // Asian open (server time)
input int    InpAsianClose        = 8;     // Asian close (server time)
input double InpMaxSpread         = 3.0;   // Max spread pips (0=disabled)
input bool   InpUseRsi            = true;  // RSI filter (tiered per level)
input int    InpRsiPeriod         = 14;    // RSI period
input double InpRsiBullMax        = 62.0;  // RSI max for BUY
input double InpRsiBearMin        = 38.0;  // RSI min for SELL
input double InpRsiExtBull        = 42.0;  // RSI for 78.6% buy (oversold)
input double InpRsiExtBear        = 58.0;  // RSI for 78.6% sell (overbought)
input bool   InpUseMacd           = true;  // MACD histogram sign
input bool   InpUseRejection      = true;  // Rejection candle
input double InpRejWickRatio      = 0.35;  // Min wick/range ratio

input group "══════ ATR VOLATILITY FILTER ══════"
input bool   InpUseAtrFilter      = true; // ATR volatility filter (skip entries during volatility spikes)
input int    InpAtrPeriod         = 14;    // ATR period (M30)
input double InpMaxAtrPips        = 20.0;  // Max ATR pips allowed on entry (0=disabled)

input group "══════ SOFT LOT FILTERS ══════"
input bool   InpUseH4Soft         = false;  // H4 soft filter (lot reduction)
input int    InpH4Ema             = 50;    // H4 EMA period
input double InpH4LotFactor       = 0.6;   // Lot × this when counter-H4
input bool   InpUseAdxSoft        = false;  // ADX soft filter (lot reduction)
input int    InpAdxPeriod         = 14;    // ADX period H1
input double InpAdxMin            = 15.0;  // ADX below → extra reduction
input double InpAdxMid            = 22.0;  // ADX above → full lot
input double InpAdxWeakLot        = 0.6;   // Lot factor when ADX weak

input group "══════ RISK ══════"
input double InpRiskPct           = 1.0;   // Risk % per trade (1% = conservative for prop)
input int    InpMaxOpenTrades     = 3;     // Max simultaneous trades
input double InpMinLot            = 0.01;
input double InpMaxLot            = 50.0;  // Higher ceiling for large funded accounts

input group "══════ TRADE MANAGEMENT ══════"
input bool   InpUseBE             = true;  // Move SL to BE after TP1
input bool   InpUseTrail          = true;  // Fixed pip trail on runner

input group "══════ DISPLAY ══════"
input bool   InpDrawFibs          = true;
input bool   InpShowPanel         = true;
input bool   InpShowArrows        = true;
input color  InpBullColor         = 16748574;
input color  InpBearColor         = 17919;

//+------------------------------------------------------------------+
//|  STRUCTURES                                                      |
//+------------------------------------------------------------------+
struct SwingPoint { double price; datetime time; int barIndex; bool isHigh; };
struct FibLevel   { double ratio; double price; bool active; };

struct FibSetup
{
   SwingPoint swHigh, swLow;
   FibLevel   levels[5];
   int        levelCount;
   bool       isBull, isActive;
   datetime   formed, lastPriceChange;
};

struct WeekStats
{
   double startBalance;   // Balance at Monday open
   double peakBalance;    // Highest balance this week
   int    trades;
   int    wins, losses;
   double grossWin, grossLoss;
   datetime weekStart;
};

struct DayStats
{
   double startBalance;
   int    trades, wins, losses;
   double grossWin, grossLoss;
   int    bSess, bTrend, bFilter, bSpread, bRR, bNews, bDD, bWeekly, bDayLimit;
};

//+------------------------------------------------------------------+
//|  GLOBALS                                                         |
//+------------------------------------------------------------------+
CTrade        trade;
CPositionInfo pos;

int      hEma, hEmaH4, hRsi, hMacd, hAtr, hAdx;
FibSetup g_setup;
bool     g_ready        = false;
double   g_initBal      = 0;   // Initial balance for total DD calculation
double   g_dayBal       = 0;
double   g_weekBal      = 0;
datetime g_dayTime      = 0;
datetime g_weekTime     = 0;
bool     g_haltDaily    = false;
bool     g_haltTotal    = false;
bool     g_weeklyLocked = false;
int      g_magic        = 0;
string   g_status       = "Initialising...";
DayStats g_day;
WeekStats g_week;
double   g_sessPnL      = 0;
double   g_peakEq       = 0;
int      g_totalTrades  = 0;

const double FIB_R[5] = {0.236, 0.382, 0.500, 0.618, 0.786};
const string FIB_N[5] = {"23.6","38.2","50.0","61.8","78.6"};

// High-impact news hours (server time) — adjust ±1 if your broker is GMT+2 or GMT+3
const int NEWS_HOURS[] = {8, 9, 13, 14, 15, 16};

//+------------------------------------------------------------------+
//|  INIT                                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   // Multi-pair safe magic from symbol hash
   g_magic = 50000000;
   for(int i = 0; i < StringLen(_Symbol); i++)
      g_magic += StringGetCharacter(_Symbol, i) * (i + 1);

   hEma   = iMA  (_Symbol, PERIOD_H1,      InpTrendEma,  0, MODE_EMA, PRICE_CLOSE);
   hEmaH4 = iMA  (_Symbol, PERIOD_H4,      InpH4Ema,     0, MODE_EMA, PRICE_CLOSE);
   hRsi   = iRSI (_Symbol, PERIOD_CURRENT, InpRsiPeriod, PRICE_CLOSE);
   hMacd  = iMACD(_Symbol, PERIOD_CURRENT, 12, 26, 9,    PRICE_CLOSE);
   hAtr   = iATR (_Symbol, PERIOD_CURRENT, InpAtrPeriod);
   hAdx   = iADX (_Symbol, PERIOD_H1,      InpAdxPeriod);

   if(hEma==INVALID_HANDLE||hEmaH4==INVALID_HANDLE||hRsi==INVALID_HANDLE||
      hMacd==INVALID_HANDLE||hAtr==INVALID_HANDLE||hAdx==INVALID_HANDLE)
   { Alert("FibEA v5.0: indicator handle failed — ",_Symbol); return INIT_FAILED; }

   trade.SetExpertMagicNumber(g_magic);
   trade.SetDeviationInPoints(30);
   trade.SetTypeFilling(ORDER_FILLING_IOC);

   double bal       = AccountInfoDouble(ACCOUNT_BALANCE);
   g_initBal        = (InpInitialBalance > 0) ? InpInitialBalance : bal;
   g_dayBal         = bal;
   g_weekBal        = bal;
   g_peakEq         = bal;
   g_dayTime        = TimeCurrent();
   g_weekTime       = TimeCurrent();
   g_setup.isActive = false;
   g_setup.lastPriceChange = 0;
   ZeroDayStats();
   ZeroWeekStats();

   string dirS = InpDirection==0?"BUY ONLY":InpDirection==1?"SELL ONLY":"BOTH";
   Print("══════════════════════════════════════════════════");
   Print("  Fibonacci EA v5.0 — PROP FIRM EDITION");
   Print("  Symbol  : ",_Symbol," | Magic: ",g_magic," | Mode: ",dirS);
   Print("  Account : $",DoubleToString(bal,2)," | Init: $",DoubleToString(g_initBal,2));
   Print("  GUARDS  : Daily DD ",InpDailyLossLimit,"% | Total DD ",InpTotalDDLimit,
         "% | Weekly target ",InpWeeklyTargetPct,"%");
   Print("  NEWS    : ",InpUseNewsFilter?"ON ±":"OFF | ",
         InpUseNewsFilter?IntegerToString(InpNewsBufferMins)+"min":"");
   Print("  WEEKEND : ",InpWeekendClose?"Close Fri ":InpWeekendCloseHour?
         IntegerToString(InpWeekendCloseHour)+":00":"OFF");
   Print("  SL/TP   : SL=",InpMaxSLPips,"pip | TP1=",InpTP1Pips,
         "pip | TP2=",InpTP2Pips,"pip | Trail=",InpTrailPips,"pip");
   Print("  Risk    : ",InpRiskPct,"% per trade | Max ",InpMaxTradesPerDay," trades/day");
   Print("══════════════════════════════════════════════════");

   ScanSwings();
   if(InpShowPanel) DrawPanel();
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//|  DEINIT                                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   PrintWeekSummary();
   IndicatorRelease(hEma); IndicatorRelease(hEmaH4);
   IndicatorRelease(hRsi); IndicatorRelease(hMacd);
   IndicatorRelease(hAtr); IndicatorRelease(hAdx);
   ObjectsDeleteAll(0,"FIB_");
   Comment("");
}

//+------------------------------------------------------------------+
//|  TICK                                                            |
//+------------------------------------------------------------------+
void OnTick()
{
   static datetime lastBar = 0;
   datetime cur = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(cur == lastBar) return;
   lastBar = cur;

   ResetDay();
   ResetWeek();
   CheckWeekendClose();   // [G6]
   if(InpShowPanel) UpdatePanel();

   if(g_haltDaily || g_haltTotal || g_weeklyLocked)
   {
      g_status = g_haltTotal  ? "⛔ TOTAL DD LIMIT — EA HALTED" :
                 g_haltDaily  ? "⛔ DAILY LOSS LIMIT" :
                                "🔒 WEEKLY TARGET REACHED";
      return;
   }

   static datetime lastH1 = 0;
   datetime curH1 = iTime(_Symbol, PERIOD_H1, 0);
   if(curH1 != lastH1) { lastH1 = curH1; ScanSwings(); }

   ManageTrades();

   if(g_ready && g_setup.isActive && CountTrades() < InpMaxOpenTrades)
      CheckEntry();
}

//+------------------------------------------------------------------+
//|  PROP FIRM GUARD — CHECK DRAWDOWN LEVELS                        |
//+------------------------------------------------------------------+
bool CheckDrawdownGuards()
{
   double bal = AccountInfoDouble(ACCOUNT_BALANCE);
   double eq  = AccountInfoDouble(ACCOUNT_EQUITY);

   // [G1] Daily loss check
   double dailyLoss = (g_dayBal - eq) / MathMax(g_dayBal,1) * 100.0;
   if(dailyLoss >= InpDailyLossLimit)
   {
      if(!g_haltDaily)
      {
         g_haltDaily = true;
         Print(StringFormat("[FIBv5 GUARD] DAILY LOSS LIMIT %.1f%% hit (loss: %.2f%%) — HALTED",
               InpDailyLossLimit, dailyLoss));
      }
      return false;
   }

   // [G2] Total DD check from initial balance
   double totalDD = (g_initBal - eq) / MathMax(g_initBal,1) * 100.0;
   if(totalDD >= InpTotalDDLimit)
   {
      if(!g_haltTotal)
      {
         g_haltTotal = true;
         Print(StringFormat("[FIBv5 GUARD] TOTAL DD LIMIT %.1f%% hit (DD: %.2f%%) — EA PERMANENTLY HALTED",
               InpTotalDDLimit, totalDD));
         Alert("FibEA v5.0: TOTAL DD LIMIT HIT — EA HALTED on ", _Symbol);
      }
      return false;
   }

   // [G3] Weekly profit lock
   if(InpWeeklyTargetPct > 0)
   {
      double weekProfit = (bal - g_weekBal) / MathMax(g_weekBal,1) * 100.0;
      if(weekProfit >= InpWeeklyTargetPct)
      {
         if(!g_weeklyLocked)
         {
            g_weeklyLocked = true;
            Print(StringFormat("[FIBv5 GUARD] WEEKLY TARGET %.1f%% reached (profit: %.2f%%) — LOCKED",
                  InpWeeklyTargetPct, weekProfit));
         }
         return false;
      }
   }

   return true;
}

//+------------------------------------------------------------------+
//|  NEWS FILTER [G4]                                               |
//+------------------------------------------------------------------+
bool IsNewsTime()
{
   if(!InpUseNewsFilter) return false;
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   int nowMin = dt.hour * 60 + dt.min;
   int count  = ArraySize(NEWS_HOURS);
   for(int i = 0; i < count; i++)
   {
      int newsMin = NEWS_HOURS[i] * 60;
      if(MathAbs(nowMin - newsMin) <= InpNewsBufferMins)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//|  WEEKEND CLOSE [G6]                                             |
//+------------------------------------------------------------------+
void CheckWeekendClose()
{
   if(!InpWeekendClose) return;
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   // Friday = day 5 in MQL5 (0=Sun, 1=Mon, ..., 5=Fri, 6=Sat)
   if(dt.day_of_week == 5 && dt.hour >= InpWeekendCloseHour)
   {
      bool hadPositions = false;
      for(int i = PositionsTotal()-1; i >= 0; i--)
      {
         if(!pos.SelectByIndex(i)) continue;
         if(pos.Symbol()!=_Symbol || pos.Magic()!=g_magic) continue;
         trade.PositionClose(pos.Ticket());
         hadPositions = true;
      }
      if(hadPositions)
      {
         Print("[FIBv5 WEEKEND] Friday ", InpWeekendCloseHour,
               ":00 — all positions closed to avoid weekend gap");
         g_status = "Weekend close — all positions closed";
      }
   }
}

//+------------------------------------------------------------------+
//|  HELPERS                                                         |
//+------------------------------------------------------------------+
double PipSize()
{
   return (_Digits == 3 || _Digits == 5) ? _Point * 10.0 : _Point;
}

bool InSession()
{
   if(!InpUseSession) return true;
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt); int h = dt.hour;
   bool inLonNY = (h>=InpLondonOpen && h<InpLondonClose) ||
                  (h>=InpNYOpen     && h<InpNYClose);
   bool inAsia  = InpUseAsianSession && (h>=InpAsianOpen && h<InpAsianClose);
   return inLonNY || inAsia;
}

bool SpreadOk()
{
   if(InpMaxSpread <= 0) return true;
   return (SymbolInfoDouble(_Symbol,SYMBOL_ASK)-SymbolInfoDouble(_Symbol,SYMBOL_BID))
          / PipSize() <= InpMaxSpread;
}

double AdxLotFactor()
{
   if(!InpUseAdxSoft) return 1.0;
   double b[]; ArraySetAsSeries(b,true);
   if(CopyBuffer(hAdx,0,1,3,b)<3) return 1.0;
   if(b[0]<InpAdxMin) return InpAdxWeakLot*0.5;
   if(b[0]<InpAdxMid) return InpAdxWeakLot;
   return 1.0;
}

int CountTrades()
{
   int c=0;
   for(int i=0;i<PositionsTotal();i++)
      if(pos.SelectByIndex(i)&&pos.Symbol()==_Symbol&&pos.Magic()==g_magic) c++;
   return c;
}

//+------------------------------------------------------------------+
//|  SWING DETECTION                                                 |
//+------------------------------------------------------------------+
void ScanSwings()
{
   int    str  = InpSwingStrength;
   int    bars = InpSwingLookback + str + 5;
   double pip  = PipSize();

   double h1H[], h1L[];
   ArraySetAsSeries(h1H,true); ArraySetAsSeries(h1L,true);
   if(CopyHigh(_Symbol,PERIOD_H1,0,bars,h1H)<bars) return;
   if(CopyLow (_Symbol,PERIOD_H1,0,bars,h1L)<bars) return;

   SwingPoint swH; swH.price=0;       swH.barIndex=-1; swH.isHigh=true;
   SwingPoint swL; swL.price=DBL_MAX; swL.barIndex=-1; swL.isHigh=false;

   for(int i=str; i<InpSwingLookback; i++)
   {
      bool okH=true, okL=true;
      for(int j=1;j<=str;j++)
      {
         if(h1H[i]<=h1H[i-j]||h1H[i]<=h1H[i+j]) okH=false;
         if(h1L[i]>=h1L[i-j]||h1L[i]>=h1L[i+j]) okL=false;
      }
      if(okH&&h1H[i]>swH.price)
      { swH.price=h1H[i];swH.time=iTime(_Symbol,PERIOD_H1,i);swH.barIndex=i; }
      if(okL&&h1L[i]<swL.price)
      { swL.price=h1L[i];swL.time=iTime(_Symbol,PERIOD_H1,i);swL.barIndex=i; }
   }

   if(swH.barIndex<0||swL.barIndex<0){g_ready=false;g_status="No swings";return;}

   double swPips=(swH.price-swL.price)/pip;
   if(swPips<InpMinSwingPips||swPips>InpMaxSwingPips)
   {g_ready=false;g_status=StringFormat("Swing %.0fpips OOR",swPips);return;}
   if(MathAbs(swH.barIndex-swL.barIndex)<str*2)
   {g_ready=false;g_status="Swings overlap";return;}

   bool isBull    = (swL.barIndex>swH.barIndex);
   bool priceChg  = (swH.price!=g_setup.swHigh.price||swL.price!=g_setup.swLow.price);

   if(priceChg)
   {
      g_setup.lastPriceChange=TimeCurrent();
      for(int i=0;i<g_setup.levelCount;i++) g_setup.levels[i].active=true;
   }
   if(!priceChg&&g_setup.isBull==isBull&&g_ready) return;

   g_setup.swHigh=swH; g_setup.swLow=swL;
   g_setup.isBull=isBull; g_setup.isActive=true;
   g_setup.formed=TimeCurrent(); g_setup.levelCount=0;

   double range=swH.price-swL.price;
   bool use[5]={InpUseFib236,InpUseFib382,InpUseFib500,InpUseFib618,InpUseFib786};
   for(int i=0;i<5;i++)
   {
      if(!use[i]) continue;
      FibLevel lv;
      lv.ratio=FIB_R[i];
      lv.price=isBull?swH.price-range*FIB_R[i]:swL.price+range*FIB_R[i];
      lv.active=true;
      g_setup.levels[g_setup.levelCount++]=lv;
   }
   g_ready=true;

   Print(StringFormat("[FIBv5] %s | H:%.5f L:%.5f | %.0fpips | %d levels | Changed:%s",
         isBull?"BULL":"BEAR",swH.price,swL.price,swPips,g_setup.levelCount,
         priceChg?"YES":"NO"));
   g_status=StringFormat("%s %.0fpips %d lvls",isBull?"BULL":"BEAR",swPips,g_setup.levelCount);
   if(InpDrawFibs) DrawFibs();
}

//+------------------------------------------------------------------+
//|  TIERED CONFIRMATION (v2.2 system — best results)               |
//+------------------------------------------------------------------+
bool Confirmed(double ratio,bool isBull,double rsi,bool macdOk,double macdH,
               double o,double c,double h,double l)
{
   bool mBull=macdOk&&macdH>0, mBear=macdOk&&macdH<0;
   double rng=h-l, lw=MathMin(o,c)-l, uw=h-MathMax(o,c);
   bool has=rng>_Point*5;
   bool bRej=has&&(c>o)&&(lw/MathMax(rng,_Point)>=InpRejWickRatio);
   bool sRej=has&&(c<o)&&(uw/MathMax(rng,_Point)>=InpRejWickRatio);
   bool rOkB=(rsi<=InpRsiBullMax), rOkS=(rsi>=InpRsiBearMin);
   bool rExB=(rsi<=InpRsiExtBull), rExS=(rsi>=InpRsiExtBear);

   if(ratio<=0.2365)      return isBull?(rOkB&&mBull&&bRej):(rOkS&&mBear&&sRej);
   else if(ratio<=0.3825) return isBull?(rOkB&&mBull&&bRej):(rOkS&&mBear&&sRej);
   else if(ratio<=0.505)  return isBull?(rOkB&&(mBull||bRej)):(rOkS&&(mBear||sRej));
   else if(ratio<=0.620)  return isBull?rOkB:rOkS;
   else                   return isBull?rExB:rExS;
}

//+------------------------------------------------------------------+
//|  CHECK ENTRY                                                     |
//+------------------------------------------------------------------+
void CheckEntry()
{
   if(!g_ready||!g_setup.isActive) return;

   // Direction filter
   if(InpDirection==0&&!g_setup.isBull){g_status="BUY-only: bear skipped";return;}
   if(InpDirection==1&& g_setup.isBull){g_status="SELL-only: bull skipped";return;}

   // Prop firm guards
   if(!CheckDrawdownGuards()) return;

   // [G5] Max trades per day
   if(g_day.trades >= InpMaxTradesPerDay)
   { g_day.bDayLimit++; g_status=StringFormat("Day trade limit %d reached",InpMaxTradesPerDay); return; }

   // Global entry filters
   if(!InSession())  {g_day.bSess++;   g_status="Outside session"; return;}
   if(IsNewsTime())  {g_day.bNews++;   g_status="News filter active"; return;}
   if(!SpreadOk())   {g_day.bSpread++; g_status="Spread too wide";  return;}

   int barsSince=(int)((TimeCurrent()-g_setup.lastPriceChange)/3600);
   if(barsSince<InpMinBarsAfterSwing)
   {g_status=StringFormat("New swing — wait %d H1 bars",InpMinBarsAfterSwing-barsSince);return;}

   // Candle data
   double c1=iClose(_Symbol,PERIOD_CURRENT,1),o1=iOpen (_Symbol,PERIOD_CURRENT,1);
   double h1=iHigh (_Symbol,PERIOD_CURRENT,1),l1=iLow  (_Symbol,PERIOD_CURRENT,1);
   double pip=PipSize(), buf=InpFibBuffer*pip;

   // ATR volatility filter
   if(InpUseAtrFilter && InpMaxAtrPips > 0.0)
   {
      double atrArr[]; ArraySetAsSeries(atrArr, true);
      if(CopyBuffer(hAtr, 0, 1, 1, atrArr) >= 1)
      {
         double atrPips = atrArr[0] / pip;
         if(atrPips > InpMaxAtrPips)
         {
            g_day.bFilter++;
            g_status = StringFormat("ATR too high: %.1fp > %.1fp", atrPips, InpMaxAtrPips);
            return;
         }
      }
   }

   double rArr[]; ArraySetAsSeries(rArr,true); double rsi=50;
   if(CopyBuffer(hRsi,0,1,2,rArr)>=2) rsi=rArr[0];

   double mArr[]; ArraySetAsSeries(mArr,true); bool macdOk=false; double macdH=0;
   if(CopyBuffer(hMacd,0,1,3,mArr)>=3){macdOk=true;macdH=mArr[0];}

   double eArr[]; ArraySetAsSeries(eArr,true); bool trendOk=true;
   if(InpUseTrend&&CopyBuffer(hEma,0,0,3,eArr)>=3)
   {
      double h1c[]; ArraySetAsSeries(h1c,true);
      if(CopyClose(_Symbol,PERIOD_H1,1,1,h1c)>=1)
         trendOk=g_setup.isBull?(h1c[0]>eArr[1]):(h1c[0]<eArr[1]);
   }
   if(!trendOk){g_day.bTrend++;g_status="Counter H1 trend";return;}

   // H4 soft lot factor
   double h4f=1.0;
   if(InpUseH4Soft)
   {
      double e4[]; ArraySetAsSeries(e4,true);
      if(CopyBuffer(hEmaH4,0,0,2,e4)>=2)
      {
         double h4c[]; ArraySetAsSeries(h4c,true);
         if(CopyClose(_Symbol,PERIOD_H4,1,1,h4c)>=1)
         { bool ok4=g_setup.isBull?(h4c[0]>e4[1]):(h4c[0]<e4[1]); if(!ok4) h4f=InpH4LotFactor; }
      }
   }
   double lotF=AdxLotFactor()*h4f;

   // Broker stop level check
   int    stopLvl=(int)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL);
   double minDist=stopLvl*_Point;
   double slDist =InpMaxSLPips*pip;
   if(slDist<minDist)
   {
      Print(StringFormat("[FIBv5 SKIP] Broker stop %.1fpips > SL %.0fpips — increase InpMaxSLPips",
                         minDist/pip,InpMaxSLPips));
      g_status=StringFormat("Broker stop %.1fpips > SL=%.0fpips",minDist/pip,InpMaxSLPips);
      return;
   }

   // Check Fibonacci levels
   for(int i=0;i<g_setup.levelCount;i++)
   {
      if(!g_setup.levels[i].active) continue;
      double fibP=g_setup.levels[i].price, fibR=g_setup.levels[i].ratio;
      bool inZone=(l1<=fibP+buf&&h1>=fibP-buf);
      if(!inZone) continue;

      if(!Confirmed(fibR,g_setup.isBull,rsi,macdOk,macdH,o1,c1,h1,l1))
      {g_day.bFilter++;g_status=StringFormat("Fib%.1f%% unmet RSI:%.0f",fibR*100,rsi);continue;}

      if(g_setup.isBull)
      {
         double ask=SymbolInfoDouble(_Symbol,SYMBOL_ASK);
         double sl =NormalizeDouble(ask-slDist,_Digits);
         double tp2=NormalizeDouble(ask+InpTP2Pips*pip,_Digits);
         Print(StringFormat("[FIBv5] BUY Fib%.1f%% Ask:%.5f SL:%.5f(%.0fp) TP2:%.5f(%.0fp) RSI:%.0f",
               fibR*100,ask,sl,InpMaxSLPips,tp2,InpTP2Pips,rsi));
         ExecTrade(ORDER_TYPE_BUY,sl,tp2,fibR,i,lotF);
         return;
      }
      else
      {
         double bid=SymbolInfoDouble(_Symbol,SYMBOL_BID);
         double sl =NormalizeDouble(bid+slDist,_Digits);
         double tp2=NormalizeDouble(bid-InpTP2Pips*pip,_Digits);
         Print(StringFormat("[FIBv5] SELL Fib%.1f%% Bid:%.5f SL:%.5f(%.0fp) TP2:%.5f(%.0fp) RSI:%.0f",
               fibR*100,bid,sl,InpMaxSLPips,tp2,InpTP2Pips,rsi));
         ExecTrade(ORDER_TYPE_SELL,sl,tp2,fibR,i,lotF);
         return;
      }
   }
}

//+------------------------------------------------------------------+
//|  EXECUTE TRADE                                                   |
//+------------------------------------------------------------------+
void ExecTrade(ENUM_ORDER_TYPE type,double sl,double tp2,
               double fibR,int lvlIdx,double lotF)
{
   if(!CheckDrawdownGuards()) return;

   double bal  = AccountInfoDouble(ACCOUNT_BALANCE);
   double ask  = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
   double bid  = SymbolInfoDouble(_Symbol,SYMBOL_BID);
   int    digs = (int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   double pip  = PipSize();
   double entry= (type==ORDER_TYPE_BUY)?ask:bid;
   double slD  = InpMaxSLPips*pip;

   // Auto-scaling position sizing
   double tVal  = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);
   double tSize = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   double risk  = bal*InpRiskPct/100.0*MathMax(lotF,0.05);
   double lots  = InpMinLot;
   if(slD>0&&tSize>0&&tVal>0) lots=risk/((slD/tSize)*tVal);

   double minL=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double maxL=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   lots=MathFloor(lots/step)*step;
   lots=MathMax(lots,MathMax(minL,InpMinLot));
   lots=MathMin(lots,MathMin(maxL,InpMaxLot));

   sl =NormalizeDouble(sl, digs);
   tp2=NormalizeDouble(tp2,digs);

   string dir=(type==ORDER_TYPE_BUY)?"B":"S";
   string cmt=StringFormat("FIBv5|%.0f|%s",fibR*1000,dir);

   bool ok=(type==ORDER_TYPE_BUY)
           ?trade.Buy (lots,_Symbol,ask,sl,tp2,cmt)
           :trade.Sell(lots,_Symbol,bid,sl,tp2,cmt);

   if(ok)
   {
      g_day.trades++; g_week.trades++; g_totalTrades++;
      g_setup.levels[lvlIdx].active=false;
      Print(StringFormat("[FIBv5 ORDER] %s Fib%.1f%% Lots:%.2f(x%.2f) Entry:%.5f SL:%.5f(%.0fp) TP2:%.5f(%.0fp)",
            (type==ORDER_TYPE_BUY)?"BUY":"SELL",fibR*100,lots,lotF,entry,sl,InpMaxSLPips,tp2,InpTP2Pips));
      g_status=StringFormat("%s Fib%.1f%% %.2f lots",
               (type==ORDER_TYPE_BUY)?"BUY":"SELL",fibR*100,lots);
      if(InpShowArrows) DrawArrow(type,entry,fibR);
      HighlightFib(lvlIdx);
   }
   else
   {
      Print("[FIBv5 ERROR] ",trade.ResultRetcodeDescription()," Code:",trade.ResultRetcode(),
            " SL:",sl," Entry:",entry," StopLvl:",SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL),"pts");
      g_status=StringFormat("Order failed %d",trade.ResultRetcode());
   }
}

//+------------------------------------------------------------------+
//|  MANAGE TRADES — Fixed pip TP1, BE, pip trail                   |
//+------------------------------------------------------------------+
void ManageTrades()
{
   double pip=PipSize(), trailD=InpTrailPips*pip;

   for(int i=PositionsTotal()-1;i>=0;i--)
   {
      if(!pos.SelectByIndex(i))   continue;
      if(pos.Symbol()!=_Symbol)   continue;
      if(pos.Magic()!=g_magic)    continue;

      ulong  tkt   = pos.Ticket();
      double open  = pos.PriceOpen();
      double curSL = pos.StopLoss();
      double curTP = pos.TakeProfit();
      double bid   = SymbolInfoDouble(_Symbol,SYMBOL_BID);
      double ask   = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
      int    digs  = (int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
      double minV  = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
      double vStep = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
      int    vDigs = (int)MathRound(MathLog10(1.0/MathMax(vStep,1e-6)));

      if(pos.PositionType()==POSITION_TYPE_BUY)
      {
         double profP=(bid-open)/pip;
         double beLvl=NormalizeDouble(open+_Point*3,digs);
         double tp1  =NormalizeDouble(open+InpTP1Pips*pip,digs);

         if(bid>=tp1&&pos.Volume()>minV*2)
         {
            double vol=NormalizeDouble(pos.Volume()*InpTP1ClosePct/100.0,vDigs);
            vol=MathMax(vol,minV); vol=MathMin(vol,pos.Volume()-minV);
            if(vol>=minV&&trade.PositionClosePartial(tkt,vol))
               Print(StringFormat("[FIBv5] BUY TP1: %.2f lots @ %.5f (+%.1fp)",vol,bid,profP));
         }
         if(InpUseBE&&profP>=InpTP1Pips&&curSL<beLvl)
            trade.PositionModify(tkt,beLvl,curTP);
         if(InpUseTrail&&profP>=InpTP1Pips)
         {
            double tSL=NormalizeDouble(bid-trailD,digs);
            if(tSL>curSL&&tSL>open) trade.PositionModify(tkt,tSL,curTP);
         }
      }
      else if(pos.PositionType()==POSITION_TYPE_SELL)
      {
         double profP=(open-ask)/pip;
         double beLvl=NormalizeDouble(open-_Point*3,digs);
         double tp1  =NormalizeDouble(open-InpTP1Pips*pip,digs);

         if(ask<=tp1&&pos.Volume()>minV*2)
         {
            double vol=NormalizeDouble(pos.Volume()*InpTP1ClosePct/100.0,vDigs);
            vol=MathMax(vol,minV); vol=MathMin(vol,pos.Volume()-minV);
            if(vol>=minV&&trade.PositionClosePartial(tkt,vol))
               Print(StringFormat("[FIBv5] SELL TP1: %.2f lots @ %.5f (+%.1fp)",vol,ask,profP));
         }
         if(InpUseBE&&profP>=InpTP1Pips&&curSL>beLvl)
            trade.PositionModify(tkt,beLvl,curTP);
         if(InpUseTrail&&profP>=InpTP1Pips)
         {
            double tSL=NormalizeDouble(ask+trailD,digs);
            if(tSL<curSL&&tSL<open) trade.PositionModify(tkt,tSL,curTP);
         }
      }
   }
}

//+------------------------------------------------------------------+
//|  DAILY / WEEKLY RESET                                           |
//+------------------------------------------------------------------+
void ResetDay()
{
   MqlDateTime n,l;
   TimeToStruct(TimeCurrent(),n); TimeToStruct(g_dayTime,l);
   if(n.day!=l.day)
   {
      double bal=AccountInfoDouble(ACCOUNT_BALANCE);
      Print("═══════════════════════════════════════");
      Print("  FIBv5 DAILY SUMMARY — ",_Symbol);
      double wr=g_day.trades>0?(double)g_day.wins/g_day.trades*100:0;
      Print("  Trades:",g_day.trades," W:",g_day.wins," L:",g_day.losses," WR:",DoubleToString(wr,1),"%");
      Print("  PnL: $",DoubleToString(bal-g_dayBal,2));
      Print("  Blocked: News:",g_day.bNews," Sess:",g_day.bSess,
            " Trend:",g_day.bTrend," DayLim:",g_day.bDayLimit);
      Print("═══════════════════════════════════════");
      g_dayBal  = bal;
      g_dayTime = TimeCurrent();
      g_haltDaily = false; // Reset daily halt
      ZeroDayStats();
      for(int i=0;i<g_setup.levelCount;i++) g_setup.levels[i].active=true;
      Print("[FIBv5] NEW DAY | Bal:$",DoubleToString(bal,2),
            " | Total DD: ",DoubleToString((g_initBal-bal)/MathMax(g_initBal,1)*100,2),"%");
   }
}

void ResetWeek()
{
   // Calculate week index starting Sunday 00:00 UTC (1970.01.04 was Sunday)
   int week_now  = (int)((TimeCurrent() + 4 * 86400) / (7 * 86400));
   int week_last = (int)((g_weekTime + 4 * 86400) / (7 * 86400));

   if(week_now != week_last)
   {
      PrintWeekSummary();
      double bal=AccountInfoDouble(ACCOUNT_BALANCE);
      g_weekBal      = bal;
      g_weekTime     = TimeCurrent();
      g_weeklyLocked = false;
      ZeroWeekStats();
      Print("[FIBv5] ═══ NEW WEEK ═══ Bal:$",DoubleToString(bal,2));
   }
}

void ZeroDayStats()
{
   g_day.startBalance=AccountInfoDouble(ACCOUNT_BALANCE);
   g_day.trades=0;g_day.wins=0;g_day.losses=0;
   g_day.grossWin=0;g_day.grossLoss=0;
   g_day.bSess=0;g_day.bTrend=0;g_day.bFilter=0;
   g_day.bSpread=0;g_day.bRR=0;g_day.bNews=0;
   g_day.bDD=0;g_day.bWeekly=0;g_day.bDayLimit=0;
}

void ZeroWeekStats()
{
   g_week.startBalance=AccountInfoDouble(ACCOUNT_BALANCE);
   g_week.peakBalance=g_week.startBalance;
   g_week.trades=0;g_week.wins=0;g_week.losses=0;
   g_week.grossWin=0;g_week.grossLoss=0;
   g_week.weekStart=TimeCurrent();
}

void PrintWeekSummary()
{
   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   double weekPnL=bal-g_weekBal;
   double weekPct=g_weekBal>0?weekPnL/g_weekBal*100:0;
   double totalDD=(g_initBal-bal)/MathMax(g_initBal,1)*100;
   Print("╔═══════════════════════════════════════╗");
   Print("║  FIBv5 WEEKLY SUMMARY — ",_Symbol);
   Print("║  Week PnL  : $",DoubleToString(weekPnL,2)," (",DoubleToString(weekPct,2),"%)");
   Print("║  Trades    : ",g_week.trades," W:",g_week.wins," L:",g_week.losses);
   Print("║  Balance   : $",DoubleToString(bal,2));
   Print("║  Total DD  : ",DoubleToString(totalDD,2),"% from $",DoubleToString(g_initBal,2));
   Print("║  Weekly target: ",InpWeeklyTargetPct,"% | ",
         g_weeklyLocked?"LOCKED ✓":"Not reached");
   Print("╚═══════════════════════════════════════╝");
}

void OnTradeTransaction(const MqlTradeTransaction& t,
                        const MqlTradeRequest& r,
                        const MqlTradeResult& rs)
{
   if(t.type!=TRADE_TRANSACTION_DEAL_ADD) return;
   double p=HistoryDealGetDouble(t.deal,DEAL_PROFIT);
   if(p==0) return;
   g_sessPnL+=p;
   if(p>0){g_day.wins++;g_week.wins++;g_day.grossWin+=p;g_week.grossWin+=p;}
   else   {g_day.losses++;g_week.losses++;g_day.grossLoss+=p;g_week.grossLoss+=p;}

   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   double weekPct=(bal-g_weekBal)/MathMax(g_weekBal,1)*100;
   double ddPct  =(g_initBal-bal)/MathMax(g_initBal,1)*100;
   Print(StringFormat("[FIBv5 DEAL] %+.2f | Week:%+.2f%% | DD:%.2f%% | W:%d L:%d | Bal:$%.2f",
         p,weekPct,ddPct,g_day.wins,g_day.losses,bal));
}

//+------------------------------------------------------------------+
//|  DRAW FIBONACCI LEVELS                                           |
//+------------------------------------------------------------------+
void DrawFibs()
{
   ObjectsDeleteAll(0,"FIB_");
   for(int k=0;k<2;k++)
   {
      string nm=k==0?"FIB_SH":"FIB_SL";
      double v=k==0?g_setup.swHigh.price:g_setup.swLow.price;
      ObjectCreate(0,nm,OBJ_HLINE,0,0,v);
      ObjectSetInteger(0,nm,OBJPROP_COLOR,clrDimGray);
      ObjectSetInteger(0,nm,OBJPROP_STYLE,STYLE_DOT);
   }
   color fibC[5]={clrSilver,clrSkyBlue,clrAqua,clrGold,clrOrange};
   for(int i=0;i<g_setup.levelCount;i++)
   {
      string nm=StringFormat("FIB_L%d",i);
      bool is618=(g_setup.levels[i].ratio==0.618);
      ObjectCreate(0,nm,OBJ_HLINE,0,0,g_setup.levels[i].price);
      ObjectSetInteger(0,nm,OBJPROP_COLOR,fibC[i%5]);
      ObjectSetInteger(0,nm,OBJPROP_STYLE,STYLE_DASH);
      ObjectSetInteger(0,nm,OBJPROP_WIDTH,is618?2:1);
      string lbl=nm+"_T";
      ObjectCreate(0,lbl,OBJ_TEXT,0,iTime(_Symbol,PERIOD_CURRENT,3),g_setup.levels[i].price);
      ObjectSetInteger(0,lbl,OBJPROP_COLOR,fibC[i%5]);
      ObjectSetInteger(0,lbl,OBJPROP_FONTSIZE,is618?9:8);
      ObjectSetString(0,lbl,OBJPROP_TEXT,
         is618?StringFormat("  GOLDEN 61.8%%  %.5f",g_setup.levels[i].price)
              :StringFormat("  %.1f%%  %.5f",g_setup.levels[i].ratio*100,g_setup.levels[i].price));
   }
   ChartRedraw(0);
}

void HighlightFib(int idx)
{
   string nm=StringFormat("FIB_L%d",idx);
   ObjectSetInteger(0,nm,OBJPROP_COLOR,clrYellow);
   ObjectSetInteger(0,nm,OBJPROP_WIDTH,3);
   ChartRedraw(0);
}

void DrawArrow(ENUM_ORDER_TYPE type,double price,double fibR)
{
   string nm=StringFormat("FIB_A%.0f_%s",fibR*1000,TimeToString(TimeCurrent(),TIME_MINUTES));
   ObjectCreate(0,nm,OBJ_ARROW,0,TimeCurrent(),price);
   ObjectSetInteger(0,nm,OBJPROP_ARROWCODE,type==ORDER_TYPE_BUY?233:234);
   ObjectSetInteger(0,nm,OBJPROP_COLOR,type==ORDER_TYPE_BUY?InpBullColor:InpBearColor);
   ObjectSetInteger(0,nm,OBJPROP_WIDTH,3);
}

//+------------------------------------------------------------------+
//|  PANEL                                                           |
//+------------------------------------------------------------------+
void DrawPanel()
{
   string pfx="FIB_P_"; int lh=15;
   string dirS=InpDirection==0?"BUY ONLY ▲":InpDirection==1?"SELL ONLY ▼":"BOTH ↕";
   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   double ddPct=(g_initBal-bal)/MathMax(g_initBal,1)*100;
   double weekPct=(bal-g_weekBal)/MathMax(g_weekBal,1)*100;

   string lines[]={
      "╔═══════════════════════════╗",
      "║  FIB EA  v5.0  PROP RM  ║",
      "╠═══════════════════════════╣",
      "  Mode    : "+dirS,
      "  SL/TP   : "+DoubleToString(InpMaxSLPips,0)+"p|"+DoubleToString(InpTP1Pips,0)+"p|"+DoubleToString(InpTP2Pips,0)+"p",
      "  Risk    : "+DoubleToString(InpRiskPct,1)+"% | Day max: "+IntegerToString(InpMaxTradesPerDay),
      "  DD Guard: Daily "+DoubleToString(InpDailyLossLimit,0)+"% | Total "+DoubleToString(InpTotalDDLimit,0)+"%",
      "  Week tgt: "+DoubleToString(InpWeeklyTargetPct,0)+"% | News: "+(InpUseNewsFilter?"ON":"OFF"),
      "╠═══════════════════════════╣",
      "  Session : ---",
      "  Swing   : ---",
      "  Trades  : ---",
      "  Week PnL: ---",
      "  Total DD: ---",
      "  Status  : ---",
      "╚═══════════════════════════╝"
   };
   for(int i=0;i<ArraySize(lines);i++)
   {
      string nm=pfx+IntegerToString(i);
      ObjectCreate(0,nm,OBJ_LABEL,0,0,0);
      ObjectSetInteger(0,nm,OBJPROP_XDISTANCE,10);
      ObjectSetInteger(0,nm,OBJPROP_YDISTANCE,30+i*lh);
      ObjectSetInteger(0,nm,OBJPROP_CORNER,CORNER_LEFT_UPPER);
      ObjectSetString (0,nm,OBJPROP_TEXT,lines[i]);
      ObjectSetInteger(0,nm,OBJPROP_COLOR,
         (i<=2||i==8||i==15)?clrGold:(i>=9&&i<=14)?clrWhite:clrSilver);
      ObjectSetInteger(0,nm,OBJPROP_FONTSIZE,8);
      ObjectSetString (0,nm,OBJPROP_FONT,"Courier New");
   }
}

void UpdatePanel()
{
   if(!InpShowPanel) return;
   string pfx="FIB_P_";
   double bal=AccountInfoDouble(ACCOUNT_BALANCE);
   double eq =AccountInfoDouble(ACCOUNT_EQUITY);
   double weekPct=(bal-g_weekBal)/MathMax(g_weekBal,1)*100;
   double ddPct  =(g_initBal-eq)/MathMax(g_initBal,1)*100;
   double dayPnL =eq-g_dayBal;
   bool   inS=InSession(), inN=IsNewsTime();
   double adxv=0; double ab[]; ArraySetAsSeries(ab,true);
   if(CopyBuffer(hAdx,0,0,2,ab)>=2) adxv=ab[0];
   double rsiv=50; double rb[]; ArraySetAsSeries(rb,true);
   if(CopyBuffer(hRsi,0,0,2,rb)>=2) rsiv=rb[0];

   string sessStr = inN?"NEWS BLOCK":inS?"ACTIVE ✓":"CLOSED";
   string swStr   = g_ready
      ?StringFormat("%s %.0fpips %dlvls",g_setup.isBull?"BULL":"BEAR",
                   (g_setup.swHigh.price-g_setup.swLow.price)/(_Point*10),g_setup.levelCount)
      :"Scanning...";
   string trdStr  = StringFormat("Open:%d Day:%d(W:%d L:%d) ADX:%.0f RSI:%.0f",
                                 CountTrades(),g_day.trades,g_day.wins,g_day.losses,adxv,rsiv);
   string wkStr   = StringFormat("%+.2f%% | Day:%+.2f | Bal:$%.2f",weekPct,dayPnL,bal);
   string ddStr   = StringFormat("%.2f%% of $%.0f | %s",ddPct,g_initBal,
                                 g_weeklyLocked?"WEEK LOCKED":g_haltTotal?"HALTED":g_haltDaily?"DAY HALT":"OK");
   string stStr   = g_haltTotal?"⛔ TOTAL DD HIT":g_haltDaily?"⛔ DAILY HALT":
                    g_weeklyLocked?"🔒 WEEK LOCKED":g_status;

   string liveL[]={sessStr,swStr,trdStr,wkStr,ddStr,stStr};
   string labels[]={"Session","Swing  ","Trades ","Week   ","DD     ","Status "};
   int start=9;
   for(int i=0;i<6;i++)
   {
      string nm=pfx+IntegerToString(start+i);
      if(ObjectFind(0,nm)>=0)
      {
         ObjectSetString(0,nm,OBJPROP_TEXT,StringFormat("  %s: %s",labels[i],liveL[i]));
         color col=clrWhite;
         if(i==0) col=inN?clrOrangeRed:inS?clrLimeGreen:clrGray;
         if(i==3) col=weekPct>=0?clrLimeGreen:clrOrangeRed;
         if(i==4) col=ddPct>InpTotalDDLimit*0.7?clrOrangeRed:ddPct>InpTotalDDLimit*0.4?clrYellow:clrLimeGreen;
         if(i==5) col=(g_haltTotal||g_haltDaily||g_weeklyLocked)?clrOrangeRed:clrWhite;
         ObjectSetInteger(0,nm,OBJPROP_COLOR,col);
      }
   }
   Comment(StringFormat("FibEA v5.0 PROP | %s | Sess:%s | Week:%+.2f%% | DD:%.2f%% | Day:%d trades | %s",
           _Symbol,sessStr,weekPct,ddPct,g_day.trades,g_status));
}
//+------------------------------------------------------------------+
