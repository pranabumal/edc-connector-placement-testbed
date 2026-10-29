import { NavLink } from 'react-router-dom'

const links = [
  { to: '/',              label: 'Dashboard',            icon: '⬛' },
  { to: '/assets',        label: 'Assets',               icon: '🗄' },
  { to: '/policies',      label: 'Policies',             icon: '🛡' },
  { to: '/contracts',     label: 'Contract Definitions', icon: '📄' },
  { to: '/transfers',     label: 'Transfer Processes',   icon: '→' },
  { to: '/access',        label: 'Access Requests',      icon: '🔐' },
  { to: '/aas',           label: 'AAS Viewer',           icon: '🔷' },
  null,
  { to: '/tests/tc1',     label: 'TC-1 Real-time Ctrl',  icon: '⚡' },
  { to: '/tests/tc2',     label: 'TC-2 Sensor Batch',    icon: '📡' },
  { to: '/tests/tc3',     label: 'TC-3 Video Stream',    icon: '🎥' },
  { to: '/tests/tc4',     label: 'TC-4 AAS via EDC',     icon: '🔷' },
  null,
  { to: '/reports',       label: 'Reports',              icon: '📊' },
]

export default function Sidebar() {
  return (
    <aside className="w-60 min-h-screen bg-slate-900 text-slate-300 flex flex-col shrink-0">
      <div className="px-5 py-5 border-b border-slate-700">
        <p className="text-xs font-semibold text-blue-400 uppercase tracking-widest">Provider</p>
        <p className="text-white font-bold text-lg leading-tight mt-0.5">Control Plane</p>
      </div>
      <nav className="flex-1 py-4 px-3 space-y-0.5">
        {links.map((link, i) =>
          link === null ? (
            <div key={i} className="my-3 border-t border-slate-700" />
          ) : (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors ` +
                (isActive
                  ? 'bg-blue-600 text-white font-medium'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-100')
              }
            >
              <span className="w-4 text-center text-base">{link.icon}</span>
              {link.label}
            </NavLink>
          )
        )}
      </nav>
      <div className="px-5 py-4 border-t border-slate-700 text-xs text-slate-500">
        EDC Dashboard v1.0 · TUNI
      </div>
    </aside>
  )
}
