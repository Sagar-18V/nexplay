import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import Layout from './components/Layout'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import Transactions from './pages/Transactions'
import Routing from './pages/Routing'
import Reconciliation from './pages/Reconciliation'

function PrivateRoute({ children, roles }) {
  const { merchant, loading } = useAuth()
  if (loading) return (
    <div className="loading-screen">
      <div className="loading-spinner" />
      Loading…
    </div>
  )
  if (!merchant) return <Navigate to="/login" />
  // optional role gate: if `roles` is provided, the merchant's role must match
  if (roles && !roles.includes(merchant.role)) {
    return <Navigate to="/dashboard" replace />
  }
  return <Layout>{children}</Layout>
}

function PublicRoute({ children }) {
  const { merchant, loading } = useAuth()
  if (loading) return null
  return merchant ? <Navigate to="/dashboard" /> : children
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login"          element={<PublicRoute><Login /></PublicRoute>} />
          <Route path="/register"       element={<PublicRoute><Register /></PublicRoute>} />
          <Route path="/dashboard"      element={<PrivateRoute><Dashboard /></PrivateRoute>} />
          <Route path="/transactions"   element={<PrivateRoute><Transactions /></PrivateRoute>} />
          <Route path="/routing"        element={<PrivateRoute><Routing /></PrivateRoute>} />
          <Route path="/reconciliation" element={<PrivateRoute><Reconciliation /></PrivateRoute>} />
          <Route path="*"               element={<Navigate to="/dashboard" />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}