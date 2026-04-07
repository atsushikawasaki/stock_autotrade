/** Normalized price row used by all indicators and strategies */
export type PriceRow = {
  date: string;    // YYYY-MM-DD
  open: number;
  high: number | null;
  low: number | null;
  close: number;
  volume: number;
};
