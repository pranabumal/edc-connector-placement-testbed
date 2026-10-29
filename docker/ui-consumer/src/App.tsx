import { Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Dashboard    from './pages/Dashboard'
import Catalog      from './pages/Catalog'
import Negotiations from './pages/Negotiations'
import Agreements   from './pages/Agreements'
import Transfers    from './pages/Transfers'
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
          <Route path="/"             element={<Dashboard />} />
          <Route path="/catalog"      element={<Catalog />} />
          <Route path="/negotiations" element={<Negotiations />} />
          <Route path="/agreements"   element={<Agreements />} />
          <Route path="/transfers"    element={<Transfers />} />
          <Route path="/aas"          element={<AASViewer />} />
          <Route path="/tests/:tc"           element={<TestRunner />} />
          <Route path="/tests/runs/:run_id" element={<RunDetail />} />
          <Route path="/reports"            element={<Reports />} />
        </Routes>
      </main>
    </div>
  )
}
