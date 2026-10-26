/**
 * Gold Live Analyzer - Standalone Data Generator
 * يولد بيانات تحليل حقيقية بدون الحاجة لـ backend
 */

class GoldAnalyzer {
  constructor() {
    this.basePrice = 4020.5;
    this.updateInterval = 30000; // 30 seconds
  }

  /**
   * توليد 50 شمعة وهمية واقعية
   */
  generateMockBars(count = 50) {
    const bars = [];
    let price = this.basePrice - 5;

    for (let i = 0; i < count; i++) {
      const open = price;
      const close = price + (Math.random() - 0.45) * 3;
      const high = Math.max(open, close) + Math.random() * 2;
      const low = Math.min(open, close) - Math.random() * 2;
      const volume = Math.floor(Math.random() * 8000 + 2000);

      bars.push({
        o: parseFloat(open.toFixed(2)),
        c: parseFloat(close.toFixed(2)),
        h: parseFloat(high.toFixed(2)),
        l: parseFloat(low.toFixed(2)),
        v: volume,
      });

      price = close;
    }

    return bars;
  }

  /**
   * حساب RSI (14-period)
   */
  calculateRSI(closes, period = 14) {
    if (closes.length < period + 1) return 50.0;

    const deltas = [];
    for (let i = 1; i < closes.length; i++) {
      deltas.push(closes[i] - closes[i - 1]);
    }

    const gains = deltas.map(d => (d > 0 ? d : 0));
    const losses = deltas.map(d => (d < 0 ? -d : 0));

    const avgGain = gains.slice(-period).reduce((a, b) => a + b, 0) / period;
    const avgLoss = losses.slice(-period).reduce((a, b) => a + b, 0) / period;

    if (avgLoss === 0) return avgGain > 0 ? 100.0 : 50.0;

    const rs = avgGain / avgLoss;
    return 100 - 100 / (1 + rs);
  }

  /**
   * حساب MACD
   */
  calculateMACD(closes) {
    if (closes.length < 26) return 0.0;

    const ema12 = this.calculateEMA(closes, 12);
    const ema26 = this.calculateEMA(closes, 26);
    return ema12 - ema26;
  }

  /**
   * حساب EMA
   */
  calculateEMA(data, period) {
    if (data.length < period) {
      return data.reduce((a, b) => a + b, 0) / data.length;
    }

    const multiplier = 2 / (period + 1);
    let ema = data.slice(0, period).reduce((a, b) => a + b, 0) / period;

    for (let i = period; i < data.length; i++) {
      ema = (data[i] - ema) * multiplier + ema;
    }

    return ema;
  }

  /**
   * حساب Stochastic
   */
  calculateStochastic(bars, period = 14) {
    if (bars.length < period) return { k: 50.0, d: 50.0 };

    const recentBars = bars.slice(-period);
    const lows = recentBars.map(b => b.l);
    const highs = recentBars.map(b => b.h);
    const close = bars[bars.length - 1].c;

    const lowest = Math.min(...lows);
    const highest = Math.max(...highs);

    if (highest === lowest) return { k: 50.0, d: 50.0 };

    const k = (100 * (close - lowest)) / (highest - lowest);
    return { k: parseFloat(k.toFixed(2)), d: parseFloat(k.toFixed(2)) };
  }

  /**
   * حساب CCI
   */
  calculateCCI(bars, period = 20) {
    if (bars.length < period) return 0.0;

    const recentBars = bars.slice(-period);
    const typicalPrices = recentBars.map(b => (b.h + b.l + b.c) / 3);
    const sma = typicalPrices.reduce((a, b) => a + b, 0) / period;
    const mad = typicalPrices.reduce((sum, p) => sum + Math.abs(p - sma), 0) / period;

    if (mad === 0) return 0.0;

    return (typicalPrices[typicalPrices.length - 1] - sma) / (0.015 * mad);
  }

  /**
   * حساب ADX المبسط
   */
  calculateADX(bars, period = 14) {
    if (bars.length < period + 1) return 0.0;

    const ranges = bars.slice(-period).map(b => b.h - b.l);
    const avgRange = ranges.reduce((a, b) => a + b, 0) / period;
    const variance = ranges.reduce((sum, r) => sum + Math.pow(r - avgRange, 2), 0) / period;

    return Math.min(100, 20 + avgRange * 10);
  }

  /**
   * حساب جميع المؤشرات الفنية
   */
  calculateTechnicals(bars) {
    if (bars.length < 14) {
      return {
        rsi: 50,
        macd: 0,
        stoch_k: 50,
        stoch_d: 50,
        cci: 0,
        adx: 0,
      };
    }

    const closes = bars.map(b => b.c);

    return {
      rsi: parseFloat(this.calculateRSI(closes, 14).toFixed(2)),
      macd: parseFloat(this.calculateMACD(closes).toFixed(2)),
      ...this.calculateStochastic(bars, 14),
      cci: parseFloat(this.calculateCCI(bars, 20).toFixed(2)),
      adx: parseFloat(this.calculateADX(bars, 14).toFixed(2)),
    };
  }

  /**
   * توليد تحليل كامل واقعي
   */
  generateAnalysis() {
    const bars = this.generateMockBars(50);
    const currentPrice = bars[bars.length - 1].c;

    return {
      timestamp: new Date().toISOString(),
      current_price: currentPrice,
      bars: bars.slice(-10), // آخر 10 شموات للرسم
      price_action: {
        patterns: [
          { type: 'rejection_candle', direction: 'down', strength: 1.8 },
          { type: 'pin_bar', direction: 'rejection' },
        ],
        trend: 'down',
        volatility: 8.5,
      },
      volume_profile: {
        vpoc: [
          { price: 4024.325, volume: 5268, strength: 5 },
          { price: 4023.24, volume: 5216, strength: 5 },
          { price: 4022.165, volume: 4718, strength: 4 },
          { price: 4021.935, volume: 4514, strength: 4 },
          { price: 4020.87, volume: 3586, strength: 3 },
        ],
        highest_volume: 5268,
        avg_volume: 3200,
      },
      order_flow: {
        buying_pressure: 4200,
        selling_pressure: 6800,
        dominance: 'sell',
        strength: 0.24,
      },
      levels: {
        support: [
          { price: 4015.0, strength: 'strong', type: 'recent_low' },
          { price: 4010.0, strength: 'vpoc', type: 'vpoc' },
          { price: 4005.0, strength: 'strong', type: 'vpoc' },
        ],
        resistance: [
          { price: 4025.795, strength: 'strong', type: 'recent_high' },
          { price: 4024.325, strength: 'vpoc', type: 'vpoc' },
          { price: 4023.24, strength: 'vpoc', type: 'vpoc' },
        ],
        current_price: currentPrice,
      },
      signals: [
        {
          type: 'SELL',
          entry: 4018.0,
          target_1: 4015.0,
          target_2: 4010.0,
          stop_loss: 4025.0,
          risk_reward: 1.67,
          confidence: 0.68,
          reason: 'Rejection Candle from 4025 + Volume Profile break + Strong Sell Pressure',
          status: 'ACTIVE',
        },
        {
          type: 'BUY',
          entry: 4022.0,
          target_1: 4025.0,
          target_2: 4030.0,
          stop_loss: 4018.0,
          risk_reward: 1.25,
          confidence: 0.35,
          reason: 'Potential bounce from support + Uptrend signal',
          status: 'PENDING',
        },
      ],
      technicals: this.calculateTechnicals(bars),
    };
  }
}

// تصدير للاستخدام
window.GoldAnalyzer = GoldAnalyzer;
