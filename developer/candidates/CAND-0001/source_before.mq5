//+------------------------------------------------------------------+
//|                                                    TestEA.mq5    |
//|                     AI EA Research Lab                           |
//+------------------------------------------------------------------+
#property version   "1.00"
#property strict

input int FastMAPeriod = 10;
input int SlowMAPeriod = 20;
input double LotSize = 0.01;

int fastMAHandle;
int slowMAHandle;

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   fastMAHandle = iMA(
      _Symbol,
      PERIOD_CURRENT,
      FastMAPeriod,
      0,
      MODE_SMA,
      PRICE_CLOSE
   );

   slowMAHandle = iMA(
      _Symbol,
      PERIOD_CURRENT,
      SlowMAPeriod,
      0,
      MODE_SMA,
      PRICE_CLOSE
   );

   if(fastMAHandle == INVALID_HANDLE ||
      slowMAHandle == INVALID_HANDLE)
   {
      Print("Failed to create indicator handles.");
      return INIT_FAILED;
   }

   Print("TestEA initialized successfully.");

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(fastMAHandle != INVALID_HANDLE)
      IndicatorRelease(fastMAHandle);

   if(slowMAHandle != INVALID_HANDLE)
      IndicatorRelease(slowMAHandle);
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // Intentionally simple for pipeline testing.
   // Trading logic will be added later.
}