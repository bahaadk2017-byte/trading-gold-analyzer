/**
 * Gold Live Analyzer Frontend - Standalone Version
 * يعمل بالكامل بدون server - بيانات محلية
 */

const goldAnalyzer = () => {
  const analyzer = new GoldAnalyzer();

  return {
    // State
    currentPrice: 4020.5,
    analysis: {
      price_action: {},
      volume_profile: {},
      order_flow: {},
      levels: {},
      technicals: {},
    },
    signals: [],
    tradeHistory: [],
    error: null,
    loading: false,
    isLive: true,
    lastUpdate: new Date(),
    selectedPair: 'XAUUSD',
    availablePairs: ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY'],
    showChart: true,
    showTechnicals: true,
    showHistory: false,
    showStats: false,
    showSettings: false,
    alertSound: null,

    // Signal thresholds
    settings: {
      rsiOverbought: 70,
      rsiOversold: 30,
      minRiskReward: 1.5,
      minConfidence: 0.3,
      autoSound: true,
    },

    // Performance stats
    get stats() {
      if (this.tradeHistory.length === 0) {
        return { wins: 0, losses: 0, winRate: 0, avgProfit: 0, totalTrades: 0 };
      }
      const completed = this.tradeHistory.filter(t => t.status === 'COMPLETED' || t.status === 'ACTIVE');
      const wins = completed.filter(t => t.result === 'WIN').length;
      const losses = completed.filter(t => t.result === 'LOSS').length;
      const totalTrades = completed.length;
      const winRate = totalTrades > 0 ? (wins / totalTrades * 100).toFixed(1) : 0;
      const totalProfit = completed.reduce((sum, t) => sum + (t.profit || 0), 0);
      const avgProfit = totalTrades > 0 ? (totalProfit / totalTrades).toFixed(2) : 0;

      return { wins, losses, winRate, avgProfit, totalTrades };
    },

    // Computed
    get buyPercentage() {
      const buy = this.analysis.order_flow?.buying_pressure || 0;
      const sell = this.analysis.order_flow?.selling_pressure || 0;
      const total = buy + sell;
      return total > 0 ? (buy / total) * 100 : 50;
    },

    get sellPercentage() {
      return 100 - this.buyPercentage;
    },

    get lastUpdateText() {
      if (!this.lastUpdate) return 'لم يتم التحديث';
      const now = new Date();
      const diff = Math.floor((now - this.lastUpdate) / 1000);
      if (diff < 60) return `منذ ${diff} ثانية`;
      if (diff < 3600) return `منذ ${Math.floor(diff / 60)} دقيقة`;
      return this.lastUpdate.toLocaleTimeString('ar-SA');
    },

    // Methods
    async init() {
      console.log('🥇 Initializing Gold Analyzer (Standalone)');
      // Initialize audio context for alerts
      try {
        this.alertSound = new AudioContext();
      } catch (e) {
        console.log('Audio context not available');
      }
      this.loadHistory();
      await this.refresh();
      // Auto-refresh every 30 seconds
      setInterval(() => this.refresh(), 30000);
    },

    playAlert() {
      if (!this.alertSound) return;
      try {
        const ctx = this.alertSound;
        const oscillator = ctx.createOscillator();
        const gain = ctx.createGain();
        oscillator.connect(gain);
        gain.connect(ctx.destination);
        oscillator.frequency.value = 800;
        oscillator.type = 'sine';
        gain.gain.setValueAtTime(0.3, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.5);
        oscillator.start(ctx.currentTime);
        oscillator.stop(ctx.currentTime + 0.5);
      } catch (e) {
        console.log('Could not play alert:', e);
      }
    },

    addToHistory(signal) {
      const entry = {
        ...signal,
        timestamp: new Date().toLocaleTimeString('ar-SA'),
        id: Date.now(),
      };
      this.tradeHistory.unshift(entry);
      if (this.tradeHistory.length > 50) this.tradeHistory.pop();
      // Play alert on new signal
      if (signal.status === 'ACTIVE') {
        this.playAlert();
      }
      localStorage.setItem('goldTradeHistory', JSON.stringify(this.tradeHistory));
    },

    loadHistory() {
      try {
        const saved = localStorage.getItem('goldTradeHistory');
        if (saved) this.tradeHistory = JSON.parse(saved);
      } catch (e) {
        console.log('Could not load history:', e);
      }
    },

    async refresh() {
      this.loading = true;
      this.error = null;

      try {
        // توليد البيانات محلياً
        const analysisData = analyzer.generateAnalysis();

        // Detect new signals for alert
        const newSignals = analysisData.signals || [];
        const previousSignalCount = this.signals.length;

        // Update state
        this.currentPrice = analysisData.current_price || 0;
        this.analysis = {
          price_action: analysisData.price_action || {},
          volume_profile: analysisData.volume_profile || {},
          order_flow: analysisData.order_flow || {},
          levels: analysisData.levels || {},
          bars: analysisData.bars || [],
          technicals: analysisData.technicals || {},
        };
        this.signals = newSignals;
        this.lastUpdate = new Date();

        // Track new signals
        if (newSignals.length > previousSignalCount) {
          newSignals.forEach(signal => this.addToHistory(signal));
        }

        // Render chart
        await this.$nextTick();
        this.renderChart();

        console.log('✅ Analysis updated:', this.analysis);
      } catch (err) {
        this.error = err.message;
        console.error('❌ Error:', err);
      } finally {
        this.loading = false;
      }
    },

    exportData() {
      const data = {
        timestamp: new Date().toISOString(),
        current_price: this.currentPrice,
        analysis: this.analysis,
        signals: this.signals,
        trade_history: this.tradeHistory,
      };

      const json = JSON.stringify(data, null, 2);
      const blob = new Blob([json], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `gold-analysis-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      console.log('✅ تم تصدير البيانات');
    },

    renderChart() {
      const ctx = document.getElementById('goldChart');
      if (!ctx) return;

      const bars = this.analysis.bars || [];
      if (bars.length === 0) return;

      // Destroy existing chart safely
      if (window.goldChart && typeof window.goldChart.destroy === 'function') {
        window.goldChart.destroy();
      }

      // Prepare chart data
      const labels = bars.map((b, i) => `${i}`);
      const closeData = bars.map(b => b.c);
      const highData = bars.map(b => b.h);
      const lowData = bars.map(b => b.l);

      // Get support/resistance/vpoc levels for visualization
      const levels = this.analysis.levels || {};
      const resistance = levels.resistance || [];
      const support = levels.support || [];
      const avgPrice = closeData.reduce((a, b) => a + b, 0) / closeData.length;

      const datasets = [
        {
          label: 'Close',
          data: closeData,
          borderColor: '#FFD700',
          backgroundColor: 'rgba(255, 215, 0, 0.1)',
          borderWidth: 2,
          fill: false,
          tension: 0.4,
          pointRadius: 3,
          pointBackgroundColor: '#FFD700',
        },
        {
          label: 'High',
          data: highData,
          borderColor: '#90EE90',
          borderDash: [5, 5],
          borderWidth: 1,
          fill: false,
          tension: 0.4,
          pointRadius: 0,
        },
        {
          label: 'Low',
          data: lowData,
          borderColor: '#FF6B6B',
          borderDash: [5, 5],
          borderWidth: 1,
          fill: false,
          tension: 0.4,
          pointRadius: 0,
        },
      ];

      // Add resistance levels as horizontal lines
      resistance.forEach((level, i) => {
        datasets.push({
          label: `R${i + 1}: $${level.price}`,
          data: Array(closeData.length).fill(level.price),
          borderColor: 'rgba(63, 185, 80, 0.5)',
          borderWidth: 1,
          borderDash: [3, 3],
          fill: false,
          tension: 0,
          pointRadius: 0,
          showLine: true,
        });
      });

      // Add support levels as horizontal lines
      support.forEach((level, i) => {
        datasets.push({
          label: `S${i + 1}: $${level.price}`,
          data: Array(closeData.length).fill(level.price),
          borderColor: 'rgba(248, 81, 73, 0.5)',
          borderWidth: 1,
          borderDash: [3, 3],
          fill: false,
          tension: 0,
          pointRadius: 0,
          showLine: true,
        });
      });

      // Create new chart
      window.goldChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets,
        },
        options: {
          responsive: true,
          maintainAspectRatio: true,
          interaction: {
            mode: 'index',
            intersect: false,
          },
          plugins: {
            legend: {
              display: true,
              position: 'top',
              labels: {
                color: '#999',
                font: { size: 12 },
              },
            },
            tooltip: {
              backgroundColor: 'rgba(0, 0, 0, 0.8)',
              titleColor: '#FFD700',
              bodyColor: '#fff',
              borderColor: '#FFD700',
              borderWidth: 1,
            },
          },
          scales: {
            y: {
              type: 'linear',
              display: true,
              ticks: {
                color: '#999',
                callback: function(value) {
                  return '$' + value.toFixed(2);
                },
              },
              grid: {
                color: 'rgba(255, 215, 0, 0.1)',
                drawBorder: true,
              },
            },
            x: {
              ticks: {
                color: '#999',
              },
              grid: {
                color: 'rgba(255, 215, 0, 0.05)',
              },
            },
          },
        },
      });
    },
  };
};

// Initialize when page loads
document.addEventListener('DOMContentLoaded', () => {
  console.log('DOM ready, initializing analyzer');
});
