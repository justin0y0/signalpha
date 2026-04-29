export type CalendarEvent = {
  ticker: string
  company_name?: string | null
  earnings_date: string
  report_time?: string | null
  sector?: string | null
  market_cap?: number | null
  confidence_score?: number | null
  direction?: string | null
  expected_move_pct?: number | null
  has_prediction: boolean
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
}

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
  win_rate: number
  avg_win_pct: number
  avg_loss_pct: number
  profit_factor: number
  mae: number | null
  rmse: number | null
  confusion_matrix: number[][]
  equity_curve: { date: string; equity: number; drawdown: number }[]
  direction_stats: { direction: string; signals: number; hits: number; hit_rate: number; avg_return_pct: number }[]
}[]
}

export type PerformanceResponse = {
  model_version?: string | null
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
