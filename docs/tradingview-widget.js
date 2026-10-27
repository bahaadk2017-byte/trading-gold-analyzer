/**
 * TradingView Advanced Chart Widget Configuration
 * Public-facing context only. No private broker data.
 */
function loadTradingViewWidget() {
  const container = document.getElementById('tradingview_chart');
  if (!container) return;

  new TradingView.widget({
    "autosize": true,
    "symbol": "OANDA:XAUUSD",
    "interval": "5",
    "timezone": "Etc/UTC",
    "theme": "dark",
    "style": "1",
    "locale": "ar",
    "toolbar_bg": "#f1f3f6",
    "enable_publishing": false,
    "withdateranges": true,
    "hide_side_toolbar": false,
    "allow_symbol_change": true,
    "details": true,
    "hotlist": true,
    "calendar": true,
    "show_popup_button": true,
    "popup_width": "1000",
    "popup_height": "650",
    "container_id": "tradingview_chart"
  });
}

document.addEventListener('DOMContentLoaded', loadTradingViewWidget);
