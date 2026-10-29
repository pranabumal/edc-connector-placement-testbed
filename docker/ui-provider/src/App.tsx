import { Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Dashboard    from './pages/Dashboard'
import Assets       from './pages/Assets'
import Policies     from './pages/Policies'
import ContractDefs from './pages/ContractDefs'
import Transfers    from './pages/Transfers'
import AccessRequests from './pages/AccessRequests'
import AASViewer    from './pages/AASViewer'
import TestRunner   from './pages/TestRunner'
import RunDetail    from './pages/RunDetail'
import Reports      from './pages/Reports'

export default function App() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/"           element={<Dashboard />} />
          <Route path="/assets"     element={<Assets />} />
          <Route path="/policies"   element={<Policies />} />
          <Route path="/contracts"  element={<ContractDefs />} />
          <Route path="/transfers"  element={<Transfers />} />
          <Route path="/access"     element={<AccessRequests />} />
          <Route path="/aas"        element={<AASViewer />} />
          <Route path="/tests/:tc"           element={<TestRunner />} />
          <Route path="/tests/runs/:run_id" element={<RunDetail />} />
          <Route path="/reports"            element={<Reports />} />
        </Routes>
      </main>
    </div>
  )
}
