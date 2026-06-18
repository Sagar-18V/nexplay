import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function Register() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ name: '', email: '', password: '', confirmPassword: '', webhookUrl: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handle = e => setForm(p => ({ ...p, [e.target.name]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    setError('')

    if (form.password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    if (form.password !== form.confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setLoading(true)
    try {
      await register(form.name, form.email, form.password, form.webhookUrl)
      navigate('/login')
    } catch (err) {
      setError(err.response?.data?.message || 'Registration failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-logo">Nex<span>Pay</span></div>

        <h1 className="auth-title">Create account</h1>
        <p className="auth-subtitle">Start accepting payments in minutes</p>

        {error && <p className="auth-error">{error}</p>}

        <form onSubmit={submit} className="auth-form">
          <div className="form-group">
            <label className="form-label" htmlFor="name">Business name</label>
            <input
              id="name" name="name" type="text"
              className="form-input"
              placeholder="Acme Inc."
              value={form.name}
              onChange={handle}
              required
              autoFocus
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="email">Email address</label>
            <input
              id="email" name="email" type="email"
              className="form-input"
              placeholder="you@business.com"
              value={form.email}
              onChange={handle}
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="password">Password</label>
            <input
              id="password" name="password" type="password"
              className="form-input"
              placeholder="Min. 8 characters"
              value={form.password}
              onChange={handle}
              minLength={8}
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="confirmPassword">Confirm password</label>
            <input
              id="confirmPassword" name="confirmPassword" type="password"
              className="form-input"
              placeholder="Re-enter your password"
              value={form.confirmPassword}
              onChange={handle}
              minLength={8}
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="webhookUrl">
              Webhook URL <span style={{ color: 'var(--dim)', fontWeight: 400 }}>(optional)</span>
            </label>
            <input
              id="webhookUrl" name="webhookUrl" type="url"
              className="form-input"
              placeholder="https://yoursite.com/webhooks/nexplay"
              value={form.webhookUrl}
              onChange={handle}
            />
          </div>

          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? 'Creating account…' : 'Create Account'}
          </button>
        </form>

        <p className="auth-link">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </div>
    </div>
  )
}
