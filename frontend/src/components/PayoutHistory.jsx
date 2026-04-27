/**
 * PayoutHistory — scrollable table of payout records.
 *
 * Props:
 *   payouts   — array from GET /api/v1/payouts/
 *   loading   — boolean
 *   total     — total count (for display)
 */

const STATUS_BADGE = {
  pending:    'badge badge-pending',
  processing: 'badge badge-processing',
  completed:  'badge badge-completed',
  failed:     'badge badge-failed',
}

const STATUS_DOT = {
  pending:    'bg-gray-400',
  processing: 'bg-blue-400 animate-pulse',
  completed:  'bg-emerald-400',
  failed:     'bg-red-400',
}

function StatusBadge({ status }) {
  return (
    <span className={STATUS_BADGE[status] || 'badge badge-pending'}>
      <span className={`w-1.5 h-1.5 rounded-full ${STATUS_DOT[status] || 'bg-gray-400'}`} />
      {status}
    </span>
  )
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
      {[1, 2, 3, 4, 5].map((i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-3 bg-gray-800 rounded animate-pulse" />
        </td>
      ))}
    </tr>
  )
}

export default function PayoutHistory({ payouts, loading, total }) {
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          Payout History
        </h2>
        {total !== undefined && (
          <span className="text-xs text-gray-500">{total} total</span>
        )}
      </div>

      <div className="overflow-x-auto -mx-5">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800">
              {['Status', 'Amount', 'Bank Account', 'Attempts', 'Created', 'Completed / Failed'].map((h) => (
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
            {loading && !payouts?.length ? (
              [1, 2, 3].map((i) => <SkeletonRow key={i} />)
            ) : payouts?.length ? (
              payouts.map((p) => (
                <tr
                  key={p.id}
                  className="border-b border-gray-800/60 hover:bg-gray-800/30 transition-colors"
                >
                  <td className="px-4 py-3 whitespace-nowrap">
                    <StatusBadge status={p.status} />
                  </td>
                  <td className="px-4 py-3 font-mono whitespace-nowrap text-gray-200">
                    {p.amount_inr}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap font-mono text-xs text-gray-400">
                    {p.bank_account?.account_number_masked || '—'}
                    <span className="ml-1 text-gray-600">{p.bank_account?.ifsc_code}</span>
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-center text-gray-400">
                    {p.attempt_count}
                    {p.status === 'failed' && p.failure_reason && (
                      <span
                        className="ml-1 cursor-help text-red-500"
                        title={p.failure_reason}
                      >
                        ⚠
                      </span>
                    )}
                    {p.bank_reference_id && (
                      <span className="ml-1 text-xs text-gray-600 font-mono" title={p.bank_reference_id}>
                        ✓
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-xs text-gray-500">
                    {fmt(p.created_at)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-xs text-gray-500">
                    {p.completed_at ? fmt(p.completed_at) : p.failed_at ? fmt(p.failed_at) : '—'}
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-600 text-sm">
                  No payouts yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
