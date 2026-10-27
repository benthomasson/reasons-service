import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'
import type { Domain } from './types'
import { useAuth } from './AuthContext'
import { listDomains } from './api'

interface TenantState {
  tenantId: string
  setTenantId: (id: string) => void
  domainId: string
  setDomainId: (id: string) => void
  domains: Domain[]
  reloadDomains: () => void
}

const TenantContext = createContext<TenantState>({
  tenantId: '',
  setTenantId: () => {},
  domainId: '',
  setDomainId: () => {},
  domains: [],
  reloadDomains: () => {},
})

export function TenantProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [tenantId, setTenantIdState] = useState(() => localStorage.getItem('reasons:tenant') || '')
  const [domainId, setDomainIdState] = useState(() => localStorage.getItem('reasons:domain') || '')
  const [domains, setDomains] = useState<Domain[]>([])

  const setTenantId = useCallback((id: string) => {
    setTenantIdState(id)
    localStorage.setItem('reasons:tenant', id)
    setDomainIdState('')
    localStorage.removeItem('reasons:domain')
  }, [])

  const setDomainId = useCallback((id: string) => {
    setDomainIdState(id)
    localStorage.setItem('reasons:domain', id)
  }, [])

  const reloadDomains = useCallback(() => {
    if (!user) return
    listDomains().then(setDomains).catch(() => {})
  }, [user])

  useEffect(() => {
    if (user && user.tenants.length > 0 && !tenantId) {
      setTenantId(user.tenants[0].tenantId)
    }
  }, [user, tenantId, setTenantId])

  useEffect(() => { reloadDomains() }, [reloadDomains])

  return (
    <TenantContext.Provider value={{ tenantId, setTenantId, domainId, setDomainId, domains, reloadDomains }}>
      {children}
    </TenantContext.Provider>
  )
}

export function useTenant() {
  return useContext(TenantContext)
}
