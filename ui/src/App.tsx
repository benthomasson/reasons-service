import { Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'
import {
  Masthead, MastheadMain, MastheadBrand, MastheadContent,
  Page, PageSection,
  Nav, NavItem, NavList,
  Toolbar, ToolbarContent, ToolbarItem,
  Select, SelectOption, MenuToggle, type MenuToggleElement,
  Button, Spinner,
} from '@patternfly/react-core'
import { useState, useRef } from 'react'

import { AuthProvider, useAuth } from './AuthContext'
import { TenantProvider, useTenant } from './TenantContext'
import ChatPage from './components/ChatPage'
import BeliefsPage from './components/BeliefsPage'
import ProposalsPage from './components/ProposalsPage'
import DocumentsPage from './components/DocumentsPage'
import DomainsPage from './components/DomainsPage'
import ConfigPage from './components/ConfigPage'

function AppContent() {
  const { user, loading } = useAuth()
  const { tenantId, setTenantId, domainId, setDomainId, domains } = useTenant()
  const navigate = useNavigate()
  const location = useLocation()
  const [tenantOpen, setTenantOpen] = useState(false)
  const [domainOpen, setDomainOpen] = useState(false)
  const tenantRef = useRef<HTMLDivElement>(null)
  const domainRef = useRef<HTMLDivElement>(null)

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spinner size="xl" />
      </div>
    )
  }

  if (!user) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', height: '100vh', gap: '1rem' }}>
        <h1>Reasons Service</h1>
        <p>Domain knowledge bases powered by epistemic reasoning</p>
        <Button component="a" href="/login">Sign in with Google</Button>
      </div>
    )
  }

  const activePath = '/' + (location.pathname.split('/')[1] || 'chat')

  const navItems = [
    { path: '/chat', label: 'Chat' },
    { path: '/beliefs', label: 'Beliefs' },
    { path: '/proposals', label: 'Proposals' },
    { path: '/documents', label: 'Documents' },
    { path: '/domains', label: 'Domains' },
    { path: '/config', label: 'Config' },
  ]

  const masthead = (
    <Masthead>
      <MastheadMain>
        <MastheadBrand data-codemods>Reasons</MastheadBrand>
      </MastheadMain>
      <MastheadContent>
        <Toolbar>
          <ToolbarContent>
            {user.tenants.length > 1 && (
              <ToolbarItem>
                <div ref={tenantRef}>
                  <Select isOpen={tenantOpen} selected={tenantId}
                    onSelect={(_e, value) => { setTenantId(value as string); setTenantOpen(false) }}
                    onOpenChange={setTenantOpen}
                    toggle={(ref: React.Ref<MenuToggleElement>) => (
                      <MenuToggle ref={ref} onClick={() => setTenantOpen(!tenantOpen)} isExpanded={tenantOpen}>
                        {user.tenants.find(t => t.tenantId === tenantId)?.tenantName || 'Select tenant'}
                      </MenuToggle>
                    )}>
                    {user.tenants.map(t => (
                      <SelectOption key={t.tenantId} value={t.tenantId}>{t.tenantName}</SelectOption>
                    ))}
                  </Select>
                </div>
              </ToolbarItem>
            )}
            <ToolbarItem>
              <div ref={domainRef}>
                <Select isOpen={domainOpen} selected={domainId}
                  onSelect={(_e, value) => { setDomainId(value as string); setDomainOpen(false) }}
                  onOpenChange={setDomainOpen}
                  toggle={(ref: React.Ref<MenuToggleElement>) => (
                    <MenuToggle ref={ref} onClick={() => setDomainOpen(!domainOpen)} isExpanded={domainOpen}>
                      {domains.find(d => d.id === domainId)?.name || 'Select domain'}
                    </MenuToggle>
                  )}>
                  {domains.map(d => (
                    <SelectOption key={d.id} value={d.id}>{d.name}</SelectOption>
                  ))}
                </Select>
              </div>
            </ToolbarItem>
            <ToolbarItem align={{ default: 'alignEnd' }}>
              <span style={{ fontSize: '0.8rem' }}>{user.display_name || user.identity}</span>
            </ToolbarItem>
            <ToolbarItem>
              <Button variant="link" size="sm" component="a" href="/logout">Sign out</Button>
            </ToolbarItem>
          </ToolbarContent>
        </Toolbar>
      </MastheadContent>
    </Masthead>
  )

  const nav = (
    <Nav onSelect={(_e, result) => navigate(result.itemId as string)} variant="horizontal">
      <NavList>
        {navItems.map(item => (
          <NavItem key={item.path} itemId={item.path} isActive={activePath === item.path}>
            {item.label}
          </NavItem>
        ))}
      </NavList>
    </Nav>
  )

  return (
    <Page masthead={masthead} style={{ height: '100vh' }}>
      <PageSection padding={{ default: 'noPadding' }}>
        {nav}
      </PageSection>
      <PageSection isFilled padding={{ default: 'noPadding' }} style={{ overflow: 'hidden' }}>
        <Routes>
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/chat/:domain" element={<ChatPage />} />
          <Route path="/beliefs" element={<BeliefsPage />} />
          <Route path="/beliefs/:domain" element={<BeliefsPage />} />
          <Route path="/proposals" element={<ProposalsPage />} />
          <Route path="/proposals/:domain" element={<ProposalsPage />} />
          <Route path="/entries" element={<Navigate to="/documents" replace />} />
          <Route path="/entries/:domain" element={<Navigate to="/documents" replace />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/domains" element={<DomainsPage />} />
          <Route path="/domains/:domainId" element={<DomainsPage />} />
          <Route path="/config" element={<ConfigPage />} />
          <Route path="*" element={<Navigate to="/chat" replace />} />
        </Routes>
      </PageSection>
    </Page>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <TenantProvider>
        <AppContent />
      </TenantProvider>
    </AuthProvider>
  )
}
