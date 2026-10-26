/* FX Dashboard — Alpine.js application logic
   All data is fetched from /api/* endpoints (read-only).
   No order, no execute, no trade functions anywhere in this file.
*/
'use strict';

// ── Utilities ─────────────────────────────────────────────────────────────

function fmtUtc(iso) {
  if (!iso) return 'N/A';
  try {
    const d = new Date(iso);
    return d.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  } catch { return iso; }
}

function fmtConf(v) {
  if (v == null) return 'N/A';
  return (v * 100).toFixed(0) + '%';
}

function biasClass(bias) {
  if (!bias) return 'bias-na';
  return { up: 'bias-up', down: 'bias-down', flat: 'bias-flat' }[bias] ?? 'bias-na';
}

function biasLabel(bias) {
  if (!bias) return 'N/A';
  return { up: '▲ صاعد', down: '▼ هابط', flat: '— مسطّح' }[bias] ?? bias;
}

function biasArrow(bias) {
  return { up: '▲', down: '▼', flat: '—' }[bias] ?? '?';
}

function envBadgeClass(env) {
  return { LIVE: 'badge-live', DEMO: 'badge-demo', UNKNOWN: 'badge-unknown' }[env] ?? 'badge-unknown';
}

function alignLabel(a) {
  return {
    agreement: 'توافق ▸',
    disagreement: 'تعارض ◂',
    mixed: 'مختلط ~',
    unavailable: 'غير متاح',
  }[a] ?? a;
}

function fmtPips(value, digits = 1) {
  if (value == null || !Number.isFinite(Number(value))) return 'N/A';
  const number = Number(value);
  return (number > 0 ? '+' : '') + number.toFixed(digits) + ' نقطة';
}

function fmtMetric(value, digits = 2) {
  if (value == null || !Number.isFinite(Number(value))) return 'N/A';
  return Number(value).toFixed(digits);
}

// ── Main Alpine component ─────────────────────────────────────────────────

document.addEventListener('alpine:init', () => {
  Alpine.data('dashboard', () => ({
    // state
    tab: 'pairs',          // pairs | gates | agents | news | history | deliberations
    loading: true,
    error: null,
    systemStatus: null,
    latestRun: null,
    runList: [],
    agents: [],
    news: null,
    newsLoading: false,
    selectedPair: null,
    detailRun: null,
    pairContext: null,
    contextLoading: false,
    backtestPairs: [],
    selectedBacktest: null,
    backtestsLoading: false,
    backtestError: null,
    equityChart: null,
    deliberations: [],
    selectedDeliberation: null,
    deliberationsLoading: false,
    deliberationsError: null,

    // computed helpers exposed to template
    fmtUtc,
    fmtConf,
    fmtPips,
    fmtMetric,
    biasClass,
    biasLabel,
    biasArrow,
    envBadgeClass,
    alignLabel,

    async init() {
      await this.refresh();
    },

    async refresh() {
      this.loading = true;
      this.error = null;
      try {
        const [sys, run, runs] = await Promise.all([
          fetch('/api/system').then(r => r.json()),
          fetch('/api/runs/latest').then(r => r.ok ? r.json() : null),
          fetch('/api/runs?limit=20').then(r => r.json()),
        ]);
        this.systemStatus = sys;
        this.latestRun = run;
        this.runList = runs.runs ?? [];
        if (this.selectedPair && run) {
          // refresh detail if pair still selected
          this.detailRun = run;
        }
      } catch (e) {
        this.error = 'خطأ في الاتصال بالخادم: ' + e.message;
      } finally {
        this.loading = false;
      }
    },

    async loadAgents() {
      if (this.agents.length) return;
      const data = await fetch('/api/agents').then(r => r.json());
      this.agents = data.agents ?? [];
    },

    async loadNews() {
      if (this.news) return;
      this.newsLoading = true;
      try {
        const pairs = (this.latestRun?.results ?? [])
          .map(r => r.pair).filter(Boolean).join(',');
        const url = pairs ? `/api/news/pairs?pairs=${encodeURIComponent(pairs)}` : '/api/news';
        this.news = await fetch(url).then(r => r.json());
      } catch (e) {
        this.news = { error: e.message };
      } finally {
        this.newsLoading = false;
      }
    },

    async loadBacktests() {
      if (this.backtestPairs.length || this.backtestsLoading) return;
      this.backtestsLoading = true;
      this.backtestError = null;
      try {
        const response = await fetch('/api/backtests');
        if (!response.ok) throw new Error('تعذّر تحميل نتائج الاختبار');
        const data = await response.json();
        this.backtestPairs = data.pair_summary ?? [];
        if (this.backtestPairs.length) await this.selectBacktest(this.backtestPairs[0]);
      } catch (e) {
        this.backtestError = e.message;
      } finally {
        this.backtestsLoading = false;
      }
    },

    async selectBacktest(summary) {
      if (!summary?.record_id) return;
      this.backtestError = null;
      try {
        const response = await fetch(`/api/backtests/${encodeURIComponent(summary.record_id)}`);
        if (!response.ok) throw new Error('تعذّر تحميل منحنى الأداء');
        this.selectedBacktest = await response.json();
        this.$nextTick(() => this.renderEquityChart());
      } catch (e) {
        this.backtestError = e.message;
      }
    },

    renderEquityChart() {
      const canvas = this.$refs.equityChart;
      const curve = this.selectedBacktest?.equity_curve ?? [];
      if (!canvas || !curve.length || typeof Chart === 'undefined') return;
      const styles = getComputedStyle(document.documentElement);
      const series = styles.getPropertyValue('--chart-series').trim();
      const area = styles.getPropertyValue('--chart-area').trim();
      const muted = styles.getPropertyValue('--text-muted').trim();
      const grid = styles.getPropertyValue('--border').trim();
      this.equityChart?.destroy();
      this.equityChart = new Chart(canvas, {
        type: 'line',
        data: {
          labels: curve.map(point => fmtUtc(point.t).slice(0, 10)),
          datasets: [{
            label: 'صافي النقاط التراكمي',
            data: curve.map(point => point.equity),
            borderColor: series,
            backgroundColor: area,
            borderWidth: 2,
            fill: true,
            pointRadius: 0,
            pointHoverRadius: 5,
            pointHitRadius: 16,
            tension: 0.15,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { display: false },
            tooltip: {
              rtl: true,
              callbacks: {
                title: items => fmtUtc(curve[items[0].dataIndex]?.t),
                label: item => `صافي تراكمي: ${fmtPips(item.parsed.y)}`,
                afterLabel: item => {
                  const trade = curve[item.dataIndex];
                  return `الصفقة: ${fmtPips(trade?.net)} · ${trade?.direction ?? 'N/A'} · ${trade?.exit_reason ?? 'N/A'}`;
                },
              },
            },
          },
          scales: {
            x: { grid: { color: grid }, ticks: { color: muted, maxTicksLimit: 7 } },
            y: { grid: { color: grid }, ticks: { color: muted, callback: value => `${value}p` } },
          },
        },
      });
    },

    onTabChange(tab) {
      this.tab = tab;
      if (tab === 'agents') this.loadAgents();
      if (tab === 'news') this.loadNews();
      if (tab === 'backtests') this.loadBacktests();
      if (tab === 'deliberations') this.loadDeliberations();
    },

    async loadDeliberations() {
      if (this.deliberations.length || this.deliberationsLoading) return;
      this.deliberationsLoading = true;
      this.deliberationsError = null;
      this.selectedDeliberation = null;
      try {
        const response = await fetch('/api/deliberations?limit=50');
        if (!response.ok) throw new Error('تعذّر تحميل المداولات');
        const data = await response.json();
        this.deliberations = data.runs ?? [];
      } catch (e) {
        this.deliberationsError = e.message;
        this.deliberations = [];
      } finally {
        this.deliberationsLoading = false;
      }
    },

    async selectDeliberation(recordId) {
      if (!recordId) {
        this.selectedDeliberation = null;
        return;
      }
      try {
        const response = await fetch(`/api/deliberations/${encodeURIComponent(recordId)}`);
        if (!response.ok) throw new Error('تعذّر تحميل تفاصيل المداولة');
        this.selectedDeliberation = await response.json();
      } catch (e) {
        this.deliberationsError = e.message;
        this.selectedDeliberation = null;
      }
    },

    async selectPair(pair) {
      this.selectedPair = this.selectedPair === pair ? null : pair;
      this.detailRun = this.latestRun;
      this.pairContext = null;
      if (!this.selectedPair) return;
      this.contextLoading = true;
      try {
        const response = await fetch(`/api/contexts/${encodeURIComponent(this.selectedPair)}`);
        this.pairContext = response.ok ? await response.json() : null;
      } catch {
        this.pairContext = null;
      } finally {
        this.contextLoading = false;
      }
    },

    pairResult(pair) {
      return (this.latestRun?.results ?? []).find(r => r.pair === pair) ?? null;
    },

    get analysedPairs() {
      return (this.latestRun?.results ?? []).filter(r => r.decision === 'ANALYSED');
    },

    get noTradePairs() {
      return (this.latestRun?.results ?? []).filter(r => r.decision === 'NO_TRADE');
    },

    get allPairs() {
      return this.latestRun?.results ?? [];
    },

    get selectedResult() {
      if (!this.selectedPair || !this.detailRun) return null;
      return (this.detailRun.results ?? []).find(r => r.pair === this.selectedPair) ?? null;
    },

    get selectedTimeframes() {
      const r = this.selectedResult;
      if (!r?.timeframes) return [];
      return ['M15', 'H1', 'H4', 'D1'].map(tf => ({
        tf,
        ...(r.timeframes[tf] ?? { bias: null }),
      }));
    },

    get selectedGates() {
      const r = this.selectedResult;
      if (!r) return [];
      const blocked = new Set(
        (r.gates_blocked ?? []).map(g => g.split(':')[0].trim())
      );
      const ALL_GATES = [
        'clock_resolved', 'freshness', 'symbol_tradable', 'symbol_consistency',
        'completeness', 'no_unexplained_gaps', 'bar_resolution', 'margin_known',
        'source_approved', 'quote_executable',
      ];
      return ALL_GATES.map(name => ({
        name,
        passed: !blocked.has(name),
        detail: (r.gates_blocked ?? []).find(g => g.startsWith(name))?.split(': ').slice(1).join(': ') ?? '',
      }));
    },

    get hasTradingView() {
      return this.selectedResult?.tradingview?.status === 'available';
    },

    get hasKronos() {
      return this.selectedResult?.kronos?.status === 'available';
    },

    formatOffset(h) {
      if (h == null) return 'N/A';
      return (h >= 0 ? '+' : '') + h.toFixed(1) + 'h';
    },

    runEnv(run) {
      if (run.environment) return run.environment;
      if (run.account?.is_real_account === true) return 'LIVE';
      if (run.account?.is_real_account === false) return 'DEMO';
      return 'UNKNOWN';
    },

    // Gate names in Arabic for display
    gateAr(name) {
      const MAP = {
        clock_resolved:       'ساعة السيرفر',
        freshness:            'حداثة البيانات',
        symbol_tradable:      'رمز قابل للتداول',
        symbol_consistency:   'تطابق الرموز',
        completeness:         'اكتمال الشموع',
        no_unexplained_gaps:  'فجوات غير مفسّرة',
        bar_resolution:       'دقة الشموع',
        margin_known:         'الهامش محسوب',
        source_approved:      'مصدر معتمد',
        quote_executable:     'سعر قابل للتنفيذ',
      };
      return MAP[name] ?? name;
    },
  }));
});
