const STATE_COLORS: Record<string, string> = {
  FINALIZED:  'bg-emerald-100 text-emerald-800',
  COMPLETED:  'bg-emerald-100 text-emerald-800',
  STARTED:    'bg-blue-100 text-blue-800',
  REQUESTING: 'bg-sky-100 text-sky-800',
  OFFERED:    'bg-sky-100 text-sky-800',
  ACCEPTED:   'bg-sky-100 text-sky-800',
  AGREED:     'bg-violet-100 text-violet-800',
  VERIFIED:   'bg-violet-100 text-violet-800',
  TERMINATED: 'bg-red-100 text-red-800',
  completed:  'bg-emerald-100 text-emerald-800',
  failed:     'bg-red-100 text-red-800',
  pending:    'bg-slate-100 text-slate-600',
  running:    'bg-blue-100 text-blue-800',
}

export default function StatusBadge({ state }: { state: string }) {
  const cls = STATE_COLORS[state] ?? 'bg-slate-100 text-slate-600'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${cls}`}>
      {state}
    </span>
  )
}
