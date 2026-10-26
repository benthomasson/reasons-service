import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import {
  Card, CardBody, Label, Flex, FlexItem,
  EmptyState, EmptyStateBody, Button,
} from '@patternfly/react-core'
import { useTenant } from '../TenantContext'
import { listEntries, getEntry } from '../api'
import Markdown from './Markdown'
import type { EntryItem } from '../types'

export default function EntriesPage() {
  const { domain: routeDomain } = useParams()
  const { domainId, setDomainId, domains } = useTenant()
  const [entries, setEntries] = useState<EntryItem[]>([])
  const [detail, setDetail] = useState<(EntryItem & { content?: string }) | null>(null)

  const activeDomainId = routeDomain
    ? domains.find(d => d.name.toLowerCase() === routeDomain.toLowerCase() || d.id === routeDomain)?.id || domainId
    : domainId

  useEffect(() => {
    if (routeDomain && activeDomainId && activeDomainId !== domainId) {
      setDomainId(activeDomainId)
    }
  }, [routeDomain, activeDomainId, domainId, setDomainId])

  const load = useCallback(() => {
    if (!activeDomainId) return
    listEntries(activeDomainId)
      .then(d => setEntries(d.entries))
      .catch(() => {})
  }, [activeDomainId])

  useEffect(() => { load() }, [load])

  const openDetail = async (entryId: string) => {
    if (!activeDomainId) return
    try {
      const d = await getEntry(activeDomainId, entryId)
      setDetail(d)
      window.history.pushState({ entry: entryId }, '', window.location.pathname)
    } catch { /* */ }
  }

  useEffect(() => {
    const handler = () => setDetail(null)
    window.addEventListener('popstate', handler)
    return () => window.removeEventListener('popstate', handler)
  }, [])

  const formatDate = (iso: string) => {
    if (!iso) return ''
    return new Date(iso + 'Z').toLocaleString()
  }

  if (detail) {
    return (
      <div style={{ padding: '1rem', overflow: 'auto', height: '100%' }}>
        <Button variant="secondary" size="sm" onClick={() => { setDetail(null); window.history.back() }}
          style={{ marginBottom: '1rem' }}>
          Back
        </Button>
        <Card>
          <CardBody>
            <h3 style={{ marginBottom: '0.5rem' }}>{detail.title || detail.topic}</h3>
            <Flex gap={{ default: 'gapSm' }} style={{ marginBottom: '1rem' }}>
              <FlexItem><Label isCompact variant="outline">{detail.topic}</Label></FlexItem>
              <FlexItem style={{ fontSize: '0.75rem', opacity: 0.6 }}>{formatDate(detail.created_at)}</FlexItem>
            </Flex>
            {detail.content && <Markdown content={detail.content} wikitext />}
          </CardBody>
        </Card>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Flex style={{ padding: '0.5rem 1rem', borderBottom: '1px solid var(--pf-t--global--border--color--default)' }}
        alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
        <FlexItem><Label isCompact>{entries.length} entries</Label></FlexItem>
      </Flex>

      <div style={{ flex: 1, overflow: 'auto', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        {!activeDomainId && (
          <EmptyState><EmptyStateBody>Select a domain to view entries.</EmptyStateBody></EmptyState>
        )}
        {activeDomainId && entries.length === 0 && (
          <EmptyState><EmptyStateBody>No entries found.</EmptyStateBody></EmptyState>
        )}
        {entries.map(e => (
          <Card isCompact key={e.id} isClickable onClick={() => openDetail(e.id)} style={{ cursor: 'pointer' }}>
            <CardBody>
              <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.25rem' }}>
                {e.title || e.topic}
              </div>
              <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsCenter' }}>
                <FlexItem><Label isCompact variant="outline">{e.topic}</Label></FlexItem>
                <FlexItem style={{ fontSize: '0.75rem', opacity: 0.6 }}>{formatDate(e.created_at)}</FlexItem>
              </Flex>
            </CardBody>
          </Card>
        ))}
      </div>
    </div>
  )
}
