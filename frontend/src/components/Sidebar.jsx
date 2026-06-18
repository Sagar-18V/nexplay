import { NavLink } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const NAV = [
  { to: '/dashboard',      label: 'Dashboard',       icon: '▦' },
  { to: '/transactions',   label: 'Transactions',     icon: '⇄' },
  { to: '/routing',        label: 'Routing Engine',   icon: '⊕' },
  { to: '/reconciliation', label: 'Reconciliation',   icon: '⊞' },
]

export default function Sidebar() {
  const { merchant, logout } = useAuth()

  const initials = merchant?.name
    ? merchant.name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2)
    : 'M'

  return (
    <aside className="sidebar">
      {/* Logo */}
      <div className="sidebar-logo">
        <div className="logo-icon">⚡</div>
        <span className="logo-text">Nex<span>Pay</span></span>
      </div>

      {/* Navigation */}
      <nav className="sidebar-nav">
        <div className="sidebar-section-label">Menu</div>
        {NAV.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
          >
            <span className="nav-icon">{icon}</span>
            <span className="nav-label">{label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="sidebar-footer">
        {merchant && (
          <div className="merchant-info">
            <div className="merchant-avatar">{initials}</div>
            <div style={{ overflow: 'hidden' }}>
              <div className="merchant-name">{merchant.name}</div>
              <div className="merchant-email">{merchant.email}</div>
            </div>
          </div>
        )}
        <button className="logout-btn" onClick={logout}>
          <span>↩</span> Sign Out
        </button>
      </div>
    </aside>
  )
}
