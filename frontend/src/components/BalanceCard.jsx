/**
 * BalanceCard — displays available, held, and total balance for a merchant.
 *
 * Props:
 *   balance  — { available_balance_inr, held_balance_inr, total_balance_inr,
 *                available_balance_paise, held_balance_paise, total_balance_paise }
 *   loading  — boolean
 */
export default function BalanceCard({ balance, loading }) {
  if (loading && !balance) {
    return (
      <div className="grid grid-cols-3 gap-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="card animate-pulse">
            <div className="h-3 bg-gray-700 rounded w-24 mb-3" />
            <div className="h-7 bg-gray-700 rounded w-32" />
          </div>
        ))}
      </div>
    )
  }

  if (!balance) return null

  const panels = [
    {
      label: 'Available Balance',
      inr: balance.available_balance_inr,
      paise: balance.available_balance_paise,
      color: 'text-emerald-400',
      border: 'border-emerald-800',
      sub: 'Ready to withdraw',
    },
    {
      label: 'Held Balance',
      inr: balance.held_balance_inr,
      paise: balance.held_balance_paise,
      color: 'text-amber-400',
      border: 'border-amber-800',
      sub: 'Pending / processing payouts',
    },
    {
      label: 'Total Balance',
      inr: balance.total_balance_inr,
      paise: balance.total_balance_paise,
      color: 'text-gray-100',
      border: 'border-gray-700',
      sub: 'Available + held',
    },
  ]

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      {panels.map((p) => (
        <div key={p.label} className={`card border ${p.border}`}>
          <p className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">
            {p.label}
          </p>
          <p className={`text-2xl font-bold font-mono ${p.color}`}>{p.inr}</p>
          <p className="text-xs text-gray-500 mt-1">
            {p.paise.toLocaleString('en-IN')} paise · {p.sub}
          </p>
        </div>
      ))}
    </div>
  )
}
