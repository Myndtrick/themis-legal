"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";

interface ExchangeRate {
  date: string;
  currency: string;
  rate: number;
  multiplier: number;
  source: string;
}

interface InterestRate {
  date: string;
  rate_type: string;
  tenor: string;
  rate: number;
  source: string;
}

const TENOR_ORDER = ["ON", "1W", "1M", "3M", "6M", "12M"];
const FX_DEFAULT_LIMIT = 30;
const IR_DEFAULT_LIMIT = 60;

export default function RatesPage() {
  const [fxRates, setFxRates] = useState<ExchangeRate[]>([]);
  const [interestRates, setInterestRates] = useState<InterestRate[]>([]);
  const [fxCurrency, setFxCurrency] = useState<string>("EUR");
  const [irRateType, setIrRateType] = useState<string>("ROBOR");
  const [irTenor, setIrTenor] = useState<string>("3M");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadFx = useCallback(async (currency: string) => {
    const params = new URLSearchParams({
      currency,
      limit: String(FX_DEFAULT_LIMIT),
    });
    return apiFetch<ExchangeRate[]>(`/api/rates/exchange?${params}`);
  }, []);

  const loadInterest = useCallback(async (rateType: string, tenor: string) => {
    const params = new URLSearchParams({
      rate_type: rateType,
      tenor,
      limit: String(IR_DEFAULT_LIMIT),
    });
    return apiFetch<InterestRate[]>(`/api/rates/interest?${params}`);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      // Awaiting first puts the subsequent setState calls outside the effect's
      // synchronous body — keeps react-hooks/set-state-in-effect happy.
      await Promise.resolve();
      if (cancelled) return;
      setLoading(true);
      setError(null);
      try {
        const [fx, ir] = await Promise.all([
          loadFx(fxCurrency),
          loadInterest(irRateType, irTenor),
        ]);
        if (cancelled) return;
        setFxRates(fx);
        setInterestRates(ir);
      } catch (e) {
        if (cancelled) return;
        setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fxCurrency, irRateType, irTenor, loadFx, loadInterest]);

  const fxLatest = fxRates[0];
  const irLatest = interestRates[0];

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Rates</h1>
        <p className="mt-2 text-gray-600">
          BNR exchange rates, ROBOR, and EURIBOR. Updated daily by the AICC scheduler.
        </p>
      </div>

      {error && (
        <div className="mb-6 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        <FxCard
          rates={fxRates}
          latest={fxLatest}
          currency={fxCurrency}
          onCurrencyChange={setFxCurrency}
          loading={loading}
        />
        <InterestCard
          rates={interestRates}
          latest={irLatest}
          rateType={irRateType}
          tenor={irTenor}
          onRateTypeChange={setIrRateType}
          onTenorChange={setIrTenor}
          loading={loading}
        />
      </div>
    </div>
  );
}

const FX_CURRENCIES = [
  "EUR", "USD", "GBP", "CHF", "JPY", "CNY", "AUD", "CAD",
  "HUF", "PLN", "CZK", "SEK", "DKK", "NOK", "TRY", "INR",
  "BRL", "ZAR", "AED", "EGP", "KRW", "MXN", "RUB", "RSD",
  "SGD", "THB", "BGN", "MDL", "UAH", "HRK", "ISK", "ILS", "XAU",
];

function FxCard({
  rates,
  latest,
  currency,
  onCurrencyChange,
  loading,
}: {
  rates: ExchangeRate[];
  latest: ExchangeRate | undefined;
  currency: string;
  onCurrencyChange: (c: string) => void;
  loading: boolean;
}) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white shadow-sm">
      <header className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Exchange rates</h2>
          <p className="text-xs text-gray-500">Source: BNR (RON per 1 unit, except where multiplier &gt; 1)</p>
        </div>
        <select
          value={currency}
          onChange={(e) => onCurrencyChange(e.target.value)}
          className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        >
          {FX_CURRENCIES.map((c) => (
            <option key={c} value={c}>{c}/RON</option>
          ))}
        </select>
      </header>

      {latest && (
        <div className="px-5 py-4 border-b border-gray-100">
          <div className="text-xs uppercase tracking-wide text-gray-500">Latest</div>
          <div className="mt-1 flex items-baseline gap-3">
            <span className="text-3xl font-bold text-gray-900 tabular-nums">
              {formatRate(latest.rate, latest.multiplier)}
            </span>
            <span className="text-sm text-gray-500">RON / {latest.multiplier > 1 ? `${latest.multiplier} ${latest.currency}` : latest.currency}</span>
            <span className="ml-auto text-sm text-gray-500">{latest.date}</span>
          </div>
        </div>
      )}

      <RatesTable
        loading={loading}
        empty={!loading && rates.length === 0}
        emptyText={`No ${currency} rates yet.`}
      >
        {rates.map((r) => (
          <tr key={`${r.date}-${r.currency}`} className="border-t border-gray-100 hover:bg-gray-50">
            <td className="px-5 py-2 text-sm text-gray-900">{r.date}</td>
            <td className="px-5 py-2 text-right text-sm font-medium text-gray-900 tabular-nums">
              {formatRate(r.rate, r.multiplier)}
            </td>
            <td className="px-5 py-2 text-right text-xs text-gray-500">
              {r.multiplier > 1 ? `× ${r.multiplier}` : ""}
            </td>
          </tr>
        ))}
      </RatesTable>
    </section>
  );
}

function InterestCard({
  rates,
  latest,
  rateType,
  tenor,
  onRateTypeChange,
  onTenorChange,
  loading,
}: {
  rates: InterestRate[];
  latest: InterestRate | undefined;
  rateType: string;
  tenor: string;
  onRateTypeChange: (r: string) => void;
  onTenorChange: (t: string) => void;
  loading: boolean;
}) {
  // EURIBOR's source doesn't publish ON; ROBOR does.
  const tenorsAvailable = useMemo(
    () => (rateType === "ROBOR" ? TENOR_ORDER : TENOR_ORDER.filter((t) => t !== "ON")),
    [rateType],
  );

  // If rate_type changes such that the current tenor is unavailable, fall back.
  useEffect(() => {
    if (!tenorsAvailable.includes(tenor)) {
      onTenorChange(tenorsAvailable[2] ?? tenorsAvailable[0]);
    }
  }, [tenor, tenorsAvailable, onTenorChange]);

  return (
    <section className="rounded-lg border border-gray-200 bg-white shadow-sm">
      <header className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Interest rates</h2>
          <p className="text-xs text-gray-500">
            ROBOR (curs-valutar-bnr.ro) · EURIBOR (euribor-rates.eu)
          </p>
        </div>
        <div className="flex gap-2">
          <select
            value={rateType}
            onChange={(e) => onRateTypeChange(e.target.value)}
            className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            <option value="ROBOR">ROBOR</option>
            <option value="EURIBOR">EURIBOR</option>
          </select>
          <select
            value={tenor}
            onChange={(e) => onTenorChange(e.target.value)}
            className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            {tenorsAvailable.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
      </header>

      {latest && (
        <div className="px-5 py-4 border-b border-gray-100">
          <div className="text-xs uppercase tracking-wide text-gray-500">Latest</div>
          <div className="mt-1 flex items-baseline gap-3">
            <span className="text-3xl font-bold text-gray-900 tabular-nums">
              {latest.rate.toFixed(3)}%
            </span>
            <span className="text-sm text-gray-500">{latest.rate_type} {latest.tenor}</span>
            <span className="ml-auto text-sm text-gray-500">{latest.date}</span>
          </div>
        </div>
      )}

      <RatesTable
        loading={loading}
        empty={!loading && rates.length === 0}
        emptyText={`No ${rateType} ${tenor} rates yet.`}
      >
        {rates.map((r) => (
          <tr key={`${r.date}-${r.rate_type}-${r.tenor}`} className="border-t border-gray-100 hover:bg-gray-50">
            <td className="px-5 py-2 text-sm text-gray-900">{r.date}</td>
            <td className="px-5 py-2 text-right text-sm font-medium text-gray-900 tabular-nums">
              {r.rate.toFixed(3)}%
            </td>
            <td className="px-5 py-2 text-right text-xs text-gray-500">{r.tenor}</td>
          </tr>
        ))}
      </RatesTable>
    </section>
  );
}

function RatesTable({
  children,
  loading,
  empty,
  emptyText,
}: {
  children: React.ReactNode;
  loading: boolean;
  empty: boolean;
  emptyText: string;
}) {
  if (loading) {
    return <div className="px-5 py-10 text-center text-sm text-gray-500">Loading…</div>;
  }
  if (empty) {
    return <div className="px-5 py-10 text-center text-sm text-gray-500">{emptyText}</div>;
  }
  return (
    <div className="max-h-[420px] overflow-y-auto">
      <table className="w-full">
        <thead className="bg-gray-50 sticky top-0">
          <tr>
            <th className="px-5 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Date</th>
            <th className="px-5 py-2 text-right text-xs font-medium uppercase tracking-wide text-gray-500">Rate</th>
            <th className="px-5 py-2 text-right text-xs font-medium uppercase tracking-wide text-gray-500"></th>
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function formatRate(rate: number, _multiplier: number): string {
  // BNR multipliers (HUF, JPY, KRW, etc.) mean "rate is for N units of foreign currency".
  // Show the rate as published; the badge already says "× N".
  void _multiplier;
  return rate.toLocaleString("en-US", {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  });
}
