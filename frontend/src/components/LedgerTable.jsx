/**
 * LedgerTable — scrollable, color-coded immutable ledger entries.
 *
 * Props:
 *   entries   — array from GET /api/v1/ledger/
 *   loading   — boolean
 *   total     — total count
 */

const ENTRY_COLORS = {
  payment_received:  'text-emerald-400',
  payout_release:    'text-emerald-300',
  adjustment_credit: 'text-emerald-300',
  payout_hold:       'text-amber-400',
  payout_completed:  'text-red-400',
  fee_debit:         'text-red-300',
  adjustment_debit:  'text-red-300',
}

const ENTRY_LABELS = {
  payment_received:  'Payment In',
  payout_hold:       'Hold',
  payout_release:    'Release',
  payout_completed:  'Payout Out',
  fee_debit:         'Fee',
  adjustment_credit: 'Adj Credit',
  adjustment_debit:  'Adj Debit',
}

function fmt(dateStr) {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  return d.toLocaleString('en-IN', {
    month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false,
  })
}

function SkeletonRow() {
  return (
    <tr className="border-b border-gray-800">
      {[1, 2, 3, 4].map((i) => (
        <td key={i} className="px-4 py-2.5">
          <div className="h-3 bg-gray-800 rounded animate-pulse" />
        </td>
      ))}
    </tr>
  )
}

export default function LedgerTable({ entries, loading, total }) {
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          Ledger
        </h2>
        {total !== undefined && (
          <span className="text-xs text-gray-500">{total} entries</span>
        )}
      </div>

      <div className="overflow-x-auto -mx-5 max-h-80 overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-gray-900 z-10">
            <tr className="border-b border-gray-800">
              {['Type', 'Amount', 'Description', 'When'].map((h) => (
                <th
                  key={h}
                  className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && !entries?.length ? (
              [1, 2, 3, 4, 5].map((i) => <SkeletonRow key={i} />)
            ) : entries?.length ? (
              entries.map((e) => {
                const isCredit = e.direction === 'credit'
                const amtColor = ENTRY_COLORS[e.entry_type] || (isCredit ? 'text-emerald-400' : 'text-red-400')
                return (
                  <tr
                    key={e.id}
                    className="border-b border-gray-800/60 hover:bg-gray-800/20 transition-colors"
                  >
                    <td className="px-4 py-2.5 whitespace-nowrap">
                      <span className="text-xs font-medium text-gray-400 bg-gray-800 px-2 py-0.5 rounded">
                        {ENTRY_LABELS[e.entry_type] || e.entry_type}
                      </span>
                    </td>
                    <td className={`px-4 py-2.5 font-mono whitespace-nowrap font-semibold ${amtColor}`}>
                      {isCredit ? '+' : '−'}
                      {e.amount_inr}
                    </td>
                    <td className="px-4 py-2.5 text-gray-400 text-xs max-w-[200px] truncate">
                      {e.description || '—'}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-500 whitespace-nowrap">
                      {fmt(e.created_at)}
                    </td>
                  </tr>
                )
              })
            ) : (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-gray-600 text-sm">
                  No ledger entries yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
