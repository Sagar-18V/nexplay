import { createContext, useContext, useState, useEffect } from 'react'
import api from '../lib/axios'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [merchant, setMerchant] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('accessToken')
    if (token) {
      api.get('/auth/me')
        .then(res => setMerchant(res.data.data))
        .catch(() => localStorage.removeItem('accessToken'))
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [])

  async function login(email, password) {
    const res = await api.post('/auth/login', { email, password })
    localStorage.setItem('accessToken', res.data.data.accessToken)
    setMerchant(res.data.data.merchant)
    return res.data.data
  }

  async function register(name, email, password, webhookUrl) {
    const res = await api.post('/auth/register', { name, email, password, webhookUrl })
    return res.data.data
  }

  async function logout() {
    try {
      // revoke the refresh token server-side (httpOnly cookie sent automatically)
      await api.post('/auth/logout')
    } catch {
      // ignore network/expiry errors — we still clear client state below
    }
    localStorage.removeItem('accessToken')
    setMerchant(null)
    window.location.href = '/login'
  }

  return (
    <AuthContext.Provider value={{ merchant, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}