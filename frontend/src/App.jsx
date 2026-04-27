import { useState, useCallback } from 'react'
import { usePolling } from './hooks/usePolling'
import BalanceCard from './components/BalanceCard'
import PayoutForm from './components/PayoutForm'
import PayoutHistory from './components/PayoutHistory'
import LedgerTable from './components/LedgerTable'

// In dev, call Django directly (CORS is open). In prod (Docker/nginx), use relative path.
const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api/v1'

async function apiFetch(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export default function App() {
  // ── Merchants ──────────────────────────────────────────────────
  const [merchants, setMerchants] = useState([])
  const [merchantsLoaded, setMerchantsLoaded] = useState(false)
  const [selectedMerchantId, setSelectedMerchantId] = useState(null)

  // ── Dashboard data ─────────────────────────────────────────────
  const [balance, setBalance] = useState(null)
  const [payouts, setPayouts] = useState([])
  const [payoutTotal, setPayoutTotal] = useState(0)
  const [ledger, setLedger] = useState([])
  const [ledgerTotal, setLedgerTotal] = useState(0)

  // ── Loading / error state ──────────────────────────────────────
  const [loadingBalance, setLoadingBalance] = useState(false)
  const [loadingPayouts, setLoadingPayouts] = useState(false)
  const [loadingLedger, setLoadingLedger] = useState(false)
  const [error, setError] = useState(null)

  // ── Load merchant list once on mount ──────────────────────────
  const fetchMerchants = useCallback(async () => {
    try {
      const data = await apiFetch(`${API}/merchants/`)
      setMerchants(data.results || [])
      if (!selectedMerchantId && data.results?.length) {
        setSelectedMerchantId(data.results[0].id)
      }
      setMerchantsLoaded(true)
    } catch (err) {
      setError('Cannot reach the backend API. Is the Django server running?')
    }
  }, [selectedMerchantId])

  usePolling(fetchMerchants, 30000) // re-check merchants every 30s

  const selectedMerchant = merchants.find((m) => m.id === selectedMerchantId)

  // ── Poll dashboard data every 3 seconds ───────────────────────
  const fetchDashboard = useCallback(async () => {
    if (!selectedMerchantId) return

    setLoadingBalance(true)
    setLoadingPayouts(true)
    setLoadingLedger(true)

    try {
      const [bal, pouts, led] = await Promise.all([
        apiFetch(`${API}/balance/?merchant_id=${selectedMerchantId}`),
        apiFetch(`${API}/payouts/?merchant_id=${selectedMerchantId}&limit=50`),
        apiFetch(`${API}/ledger/?merchant_id=${selectedMerchantId}&limit=100`),
      ])
      setBalance(bal)
      setPayouts(pouts.results || [])
      setPayoutTotal(pouts.count || 0)
      setLedger(led.results || [])
      setLedgerTotal(led.count || 0)
      setError(null)
    } catch (err) {
      setError('Failed to fetch data. Retrying…')
    } finally {
      setLoadingBalance(false)
      setLoadingPayouts(false)
      setLoadingLedger(false)
    }
  }, [selectedMerchantId])

  usePolling(fetchDashboard, 3000, !!selectedMerchantId)

  // ── Render ─────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-950">
      {/* ── Header ──────────────────────────────────────────────── */}
      <header className="border-b border-gray-800 bg-gray-900/50 backdrop-blur sticky top-0 z-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 bg-indigo-600 rounded-lg flex items-center justify-center">
              <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <span className="font-semibold text-white">Payout Engine</span>
            <span className="text-gray-600 text-xs hidden sm:inline">· Fintech-grade payout infrastructure</span>
          </div>

          {/* Merchant selector */}
          {merchants.length > 0 && (
            <select
              value={selectedMerchantId || ''}
              onChange={(e) => setSelectedMerchantId(e.target.value)}
              className="select-field text-sm max-w-[220px]"
            >
              {merchants.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          )}
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {/* Error banner */}
        {error && (
          <div className="bg-red-950 border border-red-800 text-red-300 rounded-lg px-4 py-3 text-sm flex items-center gap-2">
            <svg className="w-4 h-4 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
            {error}
          </div>
        )}

        {/* Not loaded yet */}
        {!merchantsLoaded && !error && (
          <div className="flex items-center justify-center py-20">
            <svg className="animate-spin h-8 w-8 text-indigo-500" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
          </div>
        )}

        {merchantsLoaded && !selectedMerchant && (
          <div className="card text-center py-10 text-gray-500">
            <p className="text-lg">No merchants found.</p>
            <p className="text-sm mt-1">
              Run <code className="font-mono text-indigo-400">python manage.py shell &lt; scripts/seed.py</code> to seed test data.
            </p>
          </div>
        )}

        {selectedMerchant && (
          <>
            {/* Merchant info strip */}
            <div className="flex items-center gap-3 text-sm">
              <div className="w-8 h-8 rounded-full bg-indigo-800 flex items-center justify-center text-indigo-200 font-bold">
                {selectedMerchant.name[0]}
              </div>
              <div>
                <p className="text-gray-200 font-medium">{selectedMerchant.name}</p>
                <p className="text-gray-500 text-xs font-mono">{selectedMerchant.id}</p>
              </div>
              <div className="ml-auto flex items-center gap-1.5 text-xs text-emerald-400">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Live · polling every 3s
              </div>
            </div>

            {/* Balance */}
            <BalanceCard balance={balance} loading={loadingBalance} />

            {/* Two-column: Form + Payout History */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="lg:col-span-1">
                <PayoutForm
                  merchant={selectedMerchant}
                  onSuccess={fetchDashboard}
                />
              </div>
              <div className="lg:col-span-2">
                <PayoutHistory
                  payouts={payouts}
                  loading={loadingPayouts}
                  total={payoutTotal}
                />
              </div>
            </div>

            {/* Ledger */}
            <LedgerTable entries={ledger} loading={loadingLedger} total={ledgerTotal} />
          </>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-800 mt-12 py-4 text-center text-xs text-gray-600">
        Payout Engine · All amounts in paise · No floats · SELECT FOR UPDATE · Idempotent
      </footer>
    </div>
  )
}
