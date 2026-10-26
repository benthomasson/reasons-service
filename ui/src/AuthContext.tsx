import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'
import type { UserInfo } from './types'
import { getMe } from './api'

interface AuthState {
  user: UserInfo | null
  loading: boolean
  error: string | null
  refresh: () => void
}

const AuthContext = createContext<AuthState>({
  user: null,
  loading: true,
  error: null,
  refresh: () => {},
})

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(() => {
    setLoading(true)
    getMe()
      .then(setUser)
      .catch((e) => {
        setUser(null)
        setError(e.message === 'Unauthorized' ? null : e.message)
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { refresh() }, [refresh])

  return (
    <AuthContext.Provider value={{ user, loading, error, refresh }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
