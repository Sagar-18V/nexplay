import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/v1',
  withCredentials: true,
})

// attach access token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('accessToken')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// auto refresh on 401
api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config
    const isLoginRequest = original?.url?.endsWith('/auth/login')

    if (error.response?.status === 401 && !isLoginRequest && !original._retry) {
      original._retry = true
      try {
        const res = await axios.post('/v1/auth/refresh', {}, { withCredentials: true })
        const newToken = res.data.data.accessToken
        localStorage.setItem('accessToken', newToken)
        original.headers.Authorization = `Bearer ${newToken}`
        return api(original)
      } catch {
        localStorage.removeItem('accessToken')
        window.location.href = '/login'
      }
    }

    return Promise.reject(error)
  }
)

export default api