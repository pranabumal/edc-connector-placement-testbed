import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

type SubValues = Record<string, string>

const SM_META: Record<string, { tc: string; title: string; subtitle: string }> = {
  tc1: { tc: 'TC-1', title: 'ControlSignal',  subtitle: 'Real-time control at ~50 Hz'          },
  tc2: { tc: 'TC-2', title: 'SensorData',     subtitle: '1 kHz vibration accelerometer batch'  },
  tc3: { tc: 'TC-3', title: 'VideoStream',    subtitle: '640×480 frames at 24 fps'              },
}

function SubmodelCard({ tcKey, values }: { tcKey: string; values: SubValues | null }) {
  const m = SM_META[tcKey]
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4 flex flex-col">
      <div className="flex items-start gap-2 mb-3">
        <span className="text-xs font-bold text-violet-600 bg-violet-50 px-2 py-0.5 rounded-full shrink-0">{m.tc}</span>
        <div>
          <p className="text-sm font-semibold text-slate-800 leading-tight">{m.title}</p>
          <p className="text-xs text-slate-400">{m.subtitle}</p>
        </div>
      </div>
      {values ? (
        <table className="w-full text-xs flex-1">
          <tbody className="divide-y divide-slate-50">
            {Object.entries(values).map(([k, v]) => (
              <tr key={k}>
                <td className="py-1 pr-3 text-slate-400 font-mono w-2/5 truncate">{k}</td>
                <td className="py-1 font-mono text-slate-700 break-all">
                  {String(v).length > 32 ? String(v).slice(0, 30) + '…' : v}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-xs text-slate-400 italic mt-2">No data — BaSyx not running</p>
      )}
    </div>
  )
}

export default function AASViewer() {
  const [connected, setConnected]   = useState<boolean | null>(null)
  const [values, setValues]         = useState<{ tc1: SubValues | null; tc2: SubValues | null; tc3: SubValues | null }>({ tc1: null, tc2: null, tc3: null })
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)

  useEffect(() => {
    let active = true
    const tick = async () => {
      try {
        const h = await api.aas.health()
        if (!active) return
        const ok = (h as any).status === 'ok'
        setConnected(ok)
        if (ok) {
          const [v1, v2, v3] = await Promise.all([
            api.aas.submodelValues('tc1').catch(() => null),
            api.aas.submodelValues('tc2').catch(() => null),
            api.aas.submodelValues('tc3').catch(() => null),
          ])
          if (!active) return
          setValues({ tc1: v1 as SubValues | null, tc2: v2 as SubValues | null, tc3: v3 as SubValues | null })
          setLastUpdate(new Date())
        }
      } catch {
        if (active) setConnected(false)
      }
    }
    tick()
    const id = setInterval(tick, 2000)
    return () => { active = false; clearInterval(id) }
  }, [])

  const connChip = connected === null
    ? <span className="px-2.5 py-0.5 rounded-full text-xs bg-slate-100 text-slate-400">checking…</span>
    : connected
    ? <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-700">Connected</span>
    : <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-600">Offline</span>

  return (
    <div className="p-8 max-w-6xl space-y-6">

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">BaSyx AAS Viewer</h1>
          <p className="text-slate-500 text-sm">Live digital twin submodel values — Ilmatar Industrial Crane (read-only)</p>
        </div>
        {connChip}
      </div>

      {/* BaSyx offline banner */}
      {connected === false && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
          <p className="font-semibold mb-1">BaSyx AAS is not running.</p>
          <p className="text-xs mb-2">The Provider must start it with the basyx profile:</p>
          <code className="block font-mono text-xs bg-amber-100 px-3 py-2 rounded">
            docker compose -f docker/docker-compose.yaml --profile basyx up --build
          </code>
        </div>
      )}

      {lastUpdate && (
        <p className="text-xs text-slate-400">
          Last refreshed at {lastUpdate.toLocaleTimeString()} — auto-updates every 2 s
        </p>
      )}

      {/* Submodel cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {(['tc1', 'tc2', 'tc3'] as const).map(tc => (
          <SubmodelCard key={tc} tcKey={tc} values={values[tc]} />
        ))}
      </div>

      {/* TC-4 info */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-violet-600 bg-violet-50 px-2 py-0.5 rounded-full">TC-4</span>
          <p className="text-sm font-semibold text-slate-700">AAS-backed Transfer Test</p>
        </div>
        <p className="text-xs text-slate-500 leading-relaxed">
          TC-4 transfers the ControlSignal submodel from BaSyx through the EDC dataspace to the receiver.
          Compare its latency with TC-1 (same data, raw simulator) to quantify the AAS mediation overhead —
          useful for edge deployment feasibility analysis.
        </p>
        <p className="text-xs text-slate-400">
          Prerequisite: the Provider must have registered <code className="font-mono bg-slate-100 px-1 rounded">asset-tc4-aas</code> via the AAS Viewer page.
        </p>
        <Link to="/tests/tc4" className="inline-block text-sm text-violet-600 hover:underline">
          Go to TC-4 test →
        </Link>
      </div>

    </div>
  )
}
