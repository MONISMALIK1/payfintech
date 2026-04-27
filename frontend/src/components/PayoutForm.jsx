import { useState } from 'react'

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api/v1'

/**
 * PayoutForm — submits a new payout request.
 *
 * Props:
 *   merchant       — { id, bank_accounts: [{ id, account_number_masked, ifsc_code, is_primary }] }
 *   onSuccess      — called after a successful payout creation
 */
export default function PayoutForm({ merchant, onSuccess }) {
  const [amountInr, setAmountInr] = useState('')
  const [bankAccountId, setBankAccountId] = useState(
    () => merchant?.bank_accounts?.find((b) => b.is_primary)?.id || merchant?.bank_accounts?.[0]?.id || ''
  )
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)   // { ok: bool, data: {} }

  const accounts = merchant?.bank_accounts || []

  async function handleSubmit(e) {
    e.preventDefault()
    setResult(null)

    const parsedInr = parseFloat(amountInr)
    if (!parsedInr || parsedInr <= 0) {
      setResult({ ok: false, data: { message: 'Enter a valid amount in ₹.' } })
      return
    }

    // Convert ₹ to paise as integer — no floats in the payload
    const amountPaise = Math.round(parsedInr * 100)

    // Generate a fresh UUID idempotency key for this submission
    const idempotencyKey = crypto.randomUUID()

    setSubmitting(true)
    try {
      const res = await fetch(`${API}/payouts/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
          'X-Merchant-Id': merchant.id,
        },
        body: JSON.stringify({
          amount_paise: amountPaise,
          bank_account_id: bankAccountId,
        }),
      })

      const data = await res.json()

      if (res.status === 201 || res.status === 200) {
        setResult({ ok: true, data })
        setAmountInr('')
        onSuccess?.()
      } else {
        setResult({ ok: false, data })
      }
    } catch (err) {
      setResult({ ok: false, data: { message: 'Network error. Please try again.' } })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="card">
      <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-4">
        Request Payout
      </h2>

      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Amount */}
        <div>
          <label className="block text-xs text-gray-400 mb-1" htmlFor="amount">
            Amount (₹)
          </label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 font-mono">₹</span>
            <input
              id="amount"
              type="number"
              min="1"
              step="0.01"
              placeholder="500.00"
              value={amountInr}
              onChange={(e) => setAmountInr(e.target.value)}
              className="input-field pl-7"
              required
            />
          </div>
          {amountInr && parseFloat(amountInr) > 0 && (
            <p className="text-xs text-gray-500 mt-1 font-mono">
              = {Math.round(parseFloat(amountInr) * 100).toLocaleString('en-IN')} paise
            </p>
          )}
        </div>

        {/* Bank Account */}
        <div>
          <label className="block text-xs text-gray-400 mb-1" htmlFor="bank-account">
            Bank Account
          </label>
          <select
            id="bank-account"
            value={bankAccountId}
            onChange={(e) => setBankAccountId(e.target.value)}
            className="select-field"
            required
          >
            {accounts.map((ba) => (
              <option key={ba.id} value={ba.id}>
                {ba.account_number_masked} · {ba.ifsc_code}
                {ba.is_primary ? ' (primary)' : ''}
                {ba.is_verified ? ' ✓' : ''}
              </option>
            ))}
          </select>
        </div>

        {/* Submit */}
        <button type="submit" disabled={submitting} className="btn-primary w-full">
          {submitting ? (
            <span className="flex items-center justify-center gap-2">
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              Processing…
            </span>
          ) : (
            'Request Payout'
          )}
        </button>
      </form>

      {/* Result */}
      {result && (
        <div
          className={`mt-4 p-3 rounded-lg text-sm font-mono border ${
            result.ok
              ? 'bg-emerald-950 border-emerald-800 text-emerald-300'
              : 'bg-red-950 border-red-800 text-red-300'
          }`}
        >
          {result.ok ? (
            <div>
              <p className="font-semibold text-emerald-400 mb-1">✓ Payout queued</p>
              <p>ID: <span className="text-gray-300">{result.data.id}</span></p>
              <p>Amount: <span className="text-gray-300">{result.data.amount_inr}</span></p>
              <p>Status: <span className="text-gray-300">{result.data.status}</span></p>
            </div>
          ) : (
            <div>
              <p className="font-semibold text-red-400 mb-1">
                {result.data.error || 'Error'}
              </p>
              <p>{result.data.message}</p>
              {result.data.available_paise !== undefined && (
                <p className="text-gray-400 mt-1">
                  Available: ₹{(result.data.available_paise / 100).toFixed(2)}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
