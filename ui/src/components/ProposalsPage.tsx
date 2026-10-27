import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import {
  Button, Card, CardBody, Label, Flex, FlexItem,
  TextInput, TextArea,
  EmptyState, EmptyStateBody,
  ToggleGroup, ToggleGroupItem,
} from '@patternfly/react-core'
import { useTenant } from '../TenantContext'
import { listProposals, createProposal, reviewProposal } from '../api'
import type { Proposal } from '../types'

export default function ProposalsPage() {
  const { domain: routeDomain } = useParams()
  const { domainId, setDomainId, domains } = useTenant()
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [statusFilter, setStatusFilter] = useState('pending')
  const [showForm, setShowForm] = useState(false)
  const [formNodeId, setFormNodeId] = useState('')
  const [formText, setFormText] = useState('')
  const [formType, setFormType] = useState('observation')

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
    listProposals(activeDomainId, statusFilter !== 'all' ? statusFilter : undefined)
      .then(d => setProposals(d.proposals))
      .catch(() => {})
  }, [activeDomainId, statusFilter])

  useEffect(() => { load() }, [load])

  const handleCreate = async () => {
    if (!formNodeId.trim() || !formText.trim() || !activeDomainId) return
    try {
      await createProposal(activeDomainId, {
        node_id: formNodeId,
        text: formText,
        type: formType,
      })
      setFormNodeId('')
      setFormText('')
      setShowForm(false)
      load()
    } catch { /* */ }
  }

  const handleReview = async (proposalId: string, status: string) => {
    if (!activeDomainId) return
    try {
      await reviewProposal(activeDomainId, proposalId, { status })
      load()
    } catch { /* */ }
  }

  const statusColor = (s: string) => {
    if (s === 'approved') return 'green'
    if (s === 'rejected') return 'red'
    return 'yellow'
  }

  const formatDate = (iso: string) => {
    if (!iso) return ''
    return new Date(iso + 'Z').toLocaleString()
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Flex style={{ padding: '0.5rem 1rem', borderBottom: '1px solid var(--pf-t--global--border--color--default)' }}
        alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }}>
        <FlexItem>
          <ToggleGroup>
            {['all', 'pending', 'approved', 'rejected'].map(s => (
              <ToggleGroupItem key={s} text={s.charAt(0).toUpperCase() + s.slice(1)}
                isSelected={statusFilter === s} onChange={() => setStatusFilter(s)} />
            ))}
          </ToggleGroup>
        </FlexItem>
        <FlexItem><Label isCompact>{proposals.length} proposals</Label></FlexItem>
        <FlexItem align={{ default: 'alignRight' }}>
          {activeDomainId && (
            <Button variant="primary" size="sm" onClick={() => setShowForm(!showForm)}>
              {showForm ? 'Cancel' : '+ Propose'}
            </Button>
          )}
        </FlexItem>
      </Flex>

      <div style={{ flex: 1, overflow: 'auto', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {showForm && (
          <Card isCompact>
            <CardBody>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                <TextInput value={formNodeId} onChange={(_e, v) => setFormNodeId(v)}
                  placeholder="Belief ID (e.g. my-belief-id)" />
                <TextArea value={formText} onChange={(_e, v) => setFormText(v)}
                  placeholder="Belief text..." rows={3} />
                <ToggleGroup>
                  {['observation', 'inference', 'assumption'].map(t => (
                    <ToggleGroupItem key={t} text={t.charAt(0).toUpperCase() + t.slice(1)}
                      isSelected={formType === t} onChange={() => setFormType(t)} />
                  ))}
                </ToggleGroup>
                <Button variant="primary" size="sm" onClick={handleCreate}
                  isDisabled={!formNodeId.trim() || !formText.trim()}>
                  Submit Proposal
                </Button>
              </div>
            </CardBody>
          </Card>
        )}

        {proposals.length === 0 && (
          <EmptyState><EmptyStateBody>No proposals found.</EmptyStateBody></EmptyState>
        )}

        {proposals.map(p => (
          <Card isCompact key={p.id}>
            <CardBody>
              <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsCenter' }} style={{ marginBottom: '0.25rem' }}>
                <FlexItem><Label isCompact color={statusColor(p.status)}>{p.status}</Label></FlexItem>
                <FlexItem><Label isCompact variant="outline">{p.type}</Label></FlexItem>
                <FlexItem><code style={{ fontSize: '0.75rem' }}>{p.node_id}</code></FlexItem>
              </Flex>
              <div style={{ fontSize: '0.85rem', marginBottom: '0.5rem' }}>{p.text}</div>
              <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsCenter' }}>
                <FlexItem style={{ fontSize: '0.75rem', opacity: 0.6 }}>
                  by {p.proposed_by} · {formatDate(p.created_at)}
                </FlexItem>
                {p.status === 'pending' && (
                  <FlexItem align={{ default: 'alignRight' }}>
                    <Flex gap={{ default: 'gapSm' }}>
                      <Button variant="link" size="sm" onClick={() => handleReview(p.id, 'approved')}>Approve</Button>
                      <Button variant="link" size="sm" isDanger onClick={() => handleReview(p.id, 'rejected')}>Reject</Button>
                    </Flex>
                  </FlexItem>
                )}
              </Flex>
              {p.review_notes && (
                <div style={{ marginTop: '0.25rem', fontSize: '0.8rem', fontStyle: 'italic', opacity: 0.7 }}>
                  Review: {p.review_notes}
                </div>
              )}
            </CardBody>
          </Card>
        ))}
      </div>
    </div>
  )
}
