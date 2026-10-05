export type CalendarEvent = {
  ticker: string
  company_name?: string | null
  earnings_date: string
  report_time?: string | null
  sector?: string | null
  market_cap?: number | null
  confidence_score?: number | null
  direction?: string | null
  direction_prob_up?: number | null
  direction_prob_flat?: number | null
  direction_prob_down?: number | null
  flat_band?: number | null
  /** P(this report moves the stock more than its own band) — the breakout model. */
  prob_move?: number | null
  /** Where prob_move sits against the out-of-sample deciles. */
  move_tier?: 'breakout' | 'elevated' | 'normal' | null
  expected_move_pct?: number | null
  /** ATM straddle / spot — the move options are pricing for this report. */
  implied_move_pct?: number | null
  has_prediction: boolean
}

export type BreakoutMetrics = {
  n: number
  auc: number
  base_rate: number
  top_decile: { n: number; move_rate: number; z: number }
  bottom_decile: { n: number; quiet_rate: number; quiet_base: number }
  threshold_top_decile: number
  threshold_top_quintile: number
  deciles: { decile: number; n: number; mean_p: number; move_rate: number }[]
  features: number
  first_oos_date: string
  fitted_at: string
}

/** Live capability figures from /model/headline — every number the copy quotes. */
export type Headline = {
  three_class: { n: number; accuracy: number | null; flat_baseline: number | null; distribution: Record<string, number> }
  direction: Record<'UP' | 'FLAT' | 'DOWN', { n: number; precision: number | null; base_rate: number | null }>
  breakout: BreakoutMetrics | null
  universe: { tickers: number; events: number; scored_events: number; features?: number }
}

export type CalendarResponse = {
  items: CalendarEvent[]
  total: number
}

export type DriverContribution = {
  feature: string
  value?: number | null
  contribution: number
  direction: string
}

export type HistoricalReaction = {
  earnings_date: string
  reaction_pct?: number | null
  beat_miss?: string | null
}

export type SimilarCase = {
  ticker: string
  earnings_date: string
  sector?: string | null
  similarity: number
  actual_t1_return?: number | null
  actual_t5_return?: number | null
  actual_t20_return?: number | null
}

export type PredictionResponse = {
  ticker: string
  company_name?: string | null
  earnings_date: string
  report_time?: string | null
  sector?: string | null
  model_version?: string | null
  direction_probabilities: { up: number; flat: number; down: number }
  predicted_direction: string
  confidence_score: number
  expected_move: {
    point_estimate_pct?: number | null
    low_pct?: number | null
    high_pct?: number | null
    historical_avg_pct?: number | null
  }
  convergence_band: {
    lower?: number | null
    upper?: number | null
    current_price?: number | null
    horizon_days: number
  }
  data_completeness: number
  warnings: { field: string; message: string; severity: string }[]
  key_drivers: DriverContribution[]
  historical_reactions: HistoricalReaction[]
  similar_cases: SimilarCase[]
  feature_snapshot: Record<string, unknown>
  prob_move?: number | null
  move_tier?: 'breakout' | 'elevated' | 'normal' | null
  breakout_base_rate?: number | null
  /** The stock's usual move — median absolute reaction on earlier reports. */
  flat_band?: number | null
  /** ATM straddle / spot from the latest options snapshot. */
  implied_move_pct?: number | null
}

export type EquityPoint = { date: string; equity: number; drawdown: number }

export type BacktestResponse = {
  total_samples: number
  total_trades: number
  accuracy: number
  precision_weighted: number
  recall_weighted: number
  f1_weighted: number
  sharpe_ratio: number
  sortino_ratio: number
  max_drawdown: number
  total_return: number
  cagr: number
  win_rate: number
  avg_win_pct: number
  avg_loss_pct: number
  profit_factor: number
  mae: number | null
  rmse: number | null
  confusion_matrix: number[][]
  equity_curve: EquityPoint[]
  direction_stats: { direction: string; signals: number; hits: number; hit_rate: number; avg_return_pct: number }[]
  benchmark_return: number
  benchmark_curve: EquityPoint[]
  alpha: number
  beta: number
  time_underwater_pct: number
  monthly_returns: { month: string; return_pct: number; trades: number }[]
  sector_attribution: { sector: string; return_pct: number; trades: number; win_rate: number }[]
  trade_list: {
    date: string; ticker: string; sector: string; signal: string; actual: string
    confidence: number; actual_return_pct: number; pnl_dollars: number; win: boolean
  }[]
}

export type ConfidenceTier = {
  threshold: number
  n_samples: number
  accuracy: number
  n_directional: number
  directional_accuracy: number
}

export type PerformanceResponse = {
  model_version?: string | null
  confidence_tiers?: ConfidenceTier[]
  by_sector: {
    sector: string
    accuracy?: number | null
    precision_weighted?: number | null
    recall_weighted?: number | null
    f1_weighted?: number | null
    mae?: number | null
    rmse?: number | null
    sharpe_ratio?: number | null
    recorded_at: string
  }[]
  confusion_matrix: number[][]
  feature_importance: { feature: string; importance: number }[]
}
