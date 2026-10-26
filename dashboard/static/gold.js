/**
 * Gold Live Analyzer Frontend
 * Real-time analysis with live chart updates
 */

const goldAnalyzer = () => ({
  // State
  currentPrice: 0,
  analysis: {
    price_action: {},
    volume_profile: {},
    order_flow: {},
    levels: {},
  },
  signals: [],
  error: null,
  loading: false,
  isLive: true,
  lastUpdate: new Date(),

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
    console.log('🥇 Initializing Gold Analyzer');
    await this.refresh();
    // Auto-refresh every 30 seconds
    setInterval(() => this.refresh(), 30000);
  },

  async refresh() {
    this.loading = true;
    this.error = null;

    try {
      // Fetch analysis
      const analysisRes = await fetch('/api/gold/analysis');
      if (!analysisRes.ok) throw new Error('Failed to fetch analysis');
      const analysisData = await analysisRes.json();

      // Fetch signals
      const signalsRes = await fetch('/api/gold/signals');
      if (!signalsRes.ok) throw new Error('Failed to fetch signals');
      const signalsData = await signalsRes.json();

      // Update state
      this.currentPrice = analysisData.current_price || 0;
      this.analysis = {
        price_action: analysisData.price_action || {},
        volume_profile: analysisData.volume_profile || {},
        order_flow: analysisData.order_flow || {},
        levels: analysisData.levels || {},
        bars: analysisData.bars || [],
      };
      this.signals = signalsData.signals || [];
      this.lastUpdate = new Date();

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

    // Create new chart
    window.goldChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
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
            showLine: true,
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
            showLine: true,
          },
        ],
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
});

// Initialize when page loads
document.addEventListener('DOMContentLoaded', () => {
  console.log('DOM ready, initializing analyzer');
});
