import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Button, Card, CardBody, CardHeader, CardTitle, CardFooter,
  Label, Flex, FlexItem,
  EmptyState, EmptyStateBody,
} from '@patternfly/react-core'
import { useTenant } from '../TenantContext'
import { useAuth } from '../AuthContext'
import { listDomains, getDomainOverview } from '../api'
import Markdown from './Markdown'
import type { Domain, DomainOverview } from '../types'

export default function DomainsPage() {
  const { domainId: routeDomainId } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const { setDomainId, reloadDomains } = useTenant()
  const [allDomains, setAllDomains] = useState<Domain[]>([])
  const [overview, setOverview] = useState<DomainOverview | null>(null)

  const load = useCallback(() => {
    listDomains().then(setAllDomains).catch(() => {})
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (routeDomainId) {
      getDomainOverview(routeDomainId).then(setOverview).catch(() => {})
    } else {
      setOverview(null)
    }
  }, [routeDomainId])

  const isAdmin = user?.role === 'admin' || user?.role === 'tenant_admin'

  if (routeDomainId) {
    const domain = allDomains.find(d => d.id === routeDomainId)
    return (
      <div style={{ padding: '1rem', overflow: 'auto', height: '100%' }}>
        <Button variant="secondary" size="sm" onClick={() => navigate('/domains')} style={{ marginBottom: '1rem' }}>
          Back
        </Button>
        <Card>
          <CardBody>
            <h2>{domain?.name || routeDomainId}</h2>
            <p style={{ opacity: 0.7 }}>{domain?.description}</p>
            {overview && (
              <Flex gap={{ default: 'gapMd' }} style={{ marginTop: '1rem' }}>
                <FlexItem>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{overview.stats.source_count ?? 0}</div>
                    <div style={{ fontSize: '0.8rem', opacity: 0.6 }}>Sources</div>
                  </div>
                </FlexItem>
                <FlexItem>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{overview.stats.entry_count ?? 0}</div>
                    <div style={{ fontSize: '0.8rem', opacity: 0.6 }}>Entries</div>
                  </div>
                </FlexItem>
                <FlexItem>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{overview.stats.belief_count ?? 0}</div>
                    <div style={{ fontSize: '0.8rem', opacity: 0.6 }}>Beliefs</div>
                  </div>
                </FlexItem>
              </Flex>
            )}

            <Flex gap={{ default: 'gapSm' }} style={{ marginTop: '1rem' }}>
              <Button variant="primary" size="sm"
                onClick={() => { setDomainId(routeDomainId); navigate('/beliefs') }}>
                Browse Beliefs
              </Button>
              <Button variant="secondary" size="sm"
                onClick={() => { setDomainId(routeDomainId); navigate('/chat') }}>
                Chat
              </Button>
              <Button variant="secondary" size="sm"
                onClick={() => { setDomainId(routeDomainId); navigate('/entries') }}>
                Entries
              </Button>
            </Flex>

            {overview?.topics && overview.topics.length > 0 && (
              <div style={{ marginTop: '1.5rem' }}>
                <h3 style={{ marginBottom: '0.5rem' }}>Topics</h3>
                <Flex gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
                  {overview.topics.map(t => (
                    <FlexItem key={t.id}>
                      <Label isCompact variant="outline">{t.name} ({t.belief_count})</Label>
                    </FlexItem>
                  ))}
                </Flex>
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    )
  }

  return (
    <div style={{ padding: '1rem', overflow: 'auto', height: '100%' }}>
      {allDomains.length === 0 && (
        <EmptyState><EmptyStateBody>No domains found.</EmptyStateBody></EmptyState>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '1rem' }}>
        {allDomains.map(d => (
          <Card isCompact key={d.id}>
            <CardHeader><CardTitle>{d.name}</CardTitle></CardHeader>
            <CardBody>
              <p style={{ fontSize: '0.85rem', opacity: 0.7, marginBottom: '0.5rem' }}>{d.description}</p>
            </CardBody>
            <CardFooter>
              <Flex gap={{ default: 'gapSm' }}>
                <Button variant="link" size="sm" onClick={() => navigate(`/domains/${d.id}`)}>Open</Button>
              </Flex>
            </CardFooter>
          </Card>
        ))}
      </div>
    </div>
  )
}
