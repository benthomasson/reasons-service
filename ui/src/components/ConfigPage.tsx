import {
  Card, CardBody, Flex, FlexItem,
  Select, SelectOption, MenuToggle, type MenuToggleElement,
  Content, Title,
} from '@patternfly/react-core'
import { useState } from 'react'
import { useAuth } from '../AuthContext'
import { useTenant } from '../TenantContext'

export default function ConfigPage() {
  const { user } = useAuth()
  const { tenantId, setTenantId, domainId, setDomainId, domains } = useTenant()
  const [tenantOpen, setTenantOpen] = useState(false)
  const [domainOpen, setDomainOpen] = useState(false)

  if (!user) return null

  return (
    <div style={{ padding: '1rem', overflow: 'auto', height: '100%', maxWidth: 600 }}>
      <Title headingLevel="h3" size="lg" style={{ marginBottom: '0.5rem' }}>Account</Title>
      <Card isCompact style={{ marginBottom: '1.5rem' }}>
        <CardBody>
          <Content component="p" style={{ fontSize: '0.85rem' }}>
            Identity: {user.identity}
          </Content>
          <Content component="p" style={{ fontSize: '0.85rem' }}>
            Role: {user.role}
          </Content>
          {user.display_name && (
            <Content component="p" style={{ fontSize: '0.85rem' }}>
              Display name: {user.display_name}
            </Content>
          )}
        </CardBody>
      </Card>

      <Title headingLevel="h3" size="lg" style={{ marginBottom: '0.5rem' }}>Tenant</Title>
      <div style={{ marginBottom: '1.5rem' }}>
        <Select isOpen={tenantOpen} selected={tenantId}
          onSelect={(_e, val) => { setTenantId(val as string); setTenantOpen(false) }}
          onOpenChange={setTenantOpen}
          toggle={(ref: React.Ref<MenuToggleElement>) => (
            <MenuToggle ref={ref} onClick={() => setTenantOpen(!tenantOpen)} isExpanded={tenantOpen}
              style={{ width: '100%' }}>
              {user.tenants.find(t => t.tenantId === tenantId)?.tenantName || 'Select tenant'}
            </MenuToggle>
          )}>
          {user.tenants.map(t => (
            <SelectOption key={t.tenantId} value={t.tenantId}>
              {t.tenantName} ({t.role})
            </SelectOption>
          ))}
        </Select>
        <Content component="p" style={{ fontSize: '0.75rem', opacity: 0.6, marginTop: 4 }}>
          Saved to browser localStorage
        </Content>
      </div>

      <Title headingLevel="h3" size="lg" style={{ marginBottom: '0.5rem' }}>Default Domain</Title>
      <div style={{ marginBottom: '1.5rem' }}>
        <Select isOpen={domainOpen} selected={domainId}
          onSelect={(_e, val) => { setDomainId(val as string); setDomainOpen(false) }}
          onOpenChange={setDomainOpen}
          toggle={(ref: React.Ref<MenuToggleElement>) => (
            <MenuToggle ref={ref} onClick={() => setDomainOpen(!domainOpen)} isExpanded={domainOpen}
              style={{ width: '100%' }}>
              {domains.find(d => d.id === domainId)?.name || 'Select domain'}
            </MenuToggle>
          )}>
          {domains.map(d => (
            <SelectOption key={d.id} value={d.id}>{d.name}</SelectOption>
          ))}
        </Select>
      </div>

      <Title headingLevel="h3" size="lg" style={{ marginBottom: '0.5rem' }}>Tenants</Title>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        {user.tenants.map(t => (
          <Card isCompact key={t.tenantId}>
            <CardBody>
              <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsCenter' }}>
                <FlexItem style={{ fontWeight: 600 }}>{t.tenantName}</FlexItem>
                <FlexItem style={{ fontSize: '0.8rem', opacity: 0.6 }}>{t.role}</FlexItem>
              </Flex>
            </CardBody>
          </Card>
        ))}
      </div>
    </div>
  )
}
