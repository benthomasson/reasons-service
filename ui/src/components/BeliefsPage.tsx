import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams } from 'react-router-dom'
import {
  SearchInput, Button, Label, Flex, FlexItem,
  Card, CardBody, EmptyState, EmptyStateBody,
  ToggleGroup, ToggleGroupItem,
  Select, SelectOption, MenuToggle, type MenuToggleElement,
} from '@patternfly/react-core'
import { useTenant } from '../TenantContext'
import { listBeliefs, getBeliefDetail, searchBeliefs, listIssues } from '../api'
import Markdown from './Markdown'
import type { Belief, BeliefDetail } from '../types'

const TRUTH_FILTERS = ['All', 'IN', 'OUT', 'Gated', 'Blocker'] as const
const SORT_OPTIONS = [
  { value: 'default', label: 'Default' },
  { value: 'newest', label: 'Newest' },
  { value: 'oldest', label: 'Oldest' },
  { value: 'updated', label: 'Recently updated' },
  { value: 'deepest', label: 'Deepest' },
  { value: 'shallowest', label: 'Shallowest' },
]

export default function BeliefsPage() {
  const { domain: routeDomain } = useParams()
  const { domainId, setDomainId, domains } = useTenant()
  const [beliefs, setBeliefs] = useState<Belief[]>([])
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [truthFilter, setTruthFilter] = useState('All')
  const [sort, setSort] = useState('default')
  const [sortOpen, setSortOpen] = useState(false)
  const [detail, setDetail] = useState<BeliefDetail | null>(null)
  const searchTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  const activeDomainId = routeDomain
    ? domains.find(d => d.name.toLowerCase() === routeDomain.toLowerCase() || d.id === routeDomain)?.id || domainId
    : domainId

  useEffect(() => {
    if (routeDomain && activeDomainId && activeDomainId !== domainId) {
      setDomainId(activeDomainId)
    }
  }, [routeDomain, activeDomainId, domainId, setDomainId])

  const searchRef = useRef(search)
  searchRef.current = search

  const load = useCallback(async (offset = 0) => {
    if (!activeDomainId) return
    try {
      if (searchRef.current) {
        const data = await searchBeliefs(activeDomainId, searchRef.current)
        setBeliefs(data.results)
        setTotal(data.results.length)
      } else if (truthFilter === 'Gated' || truthFilter === 'Blocker') {
        const issues = await listIssues(activeDomainId)
        let items: Belief[]
        if (truthFilter === 'Gated') {
          const blockers = issues.gated?.blockers || {}
          items = Object.entries(blockers).flatMap(([blockerId, b]) =>
            b.gated.map(g => ({ ...g, truth_value: 'OUT', source: `gated by: ${blockerId}` }))
          )
        } else {
          items = (issues.negative?.candidates || []).map(c => ({ ...c, truth_value: 'IN' }))
        }
        setBeliefs(items)
        setTotal(items.length)
      } else {
        const data = await listBeliefs(activeDomainId, {
          status: truthFilter !== 'All' ? truthFilter : undefined,
          sort: sort !== 'default' ? sort : undefined,
          offset,
          limit: 50,
        })
        if (offset === 0) {
          setBeliefs(data.beliefs)
        } else {
          setBeliefs(prev => [...prev, ...data.beliefs])
        }
        setTotal(data.total)
      }
    } catch { /* */ }
  }, [activeDomainId, truthFilter, sort])

  useEffect(() => { load() }, [load])

  const handleSearch = (value: string) => {
    setSearch(value)
    clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => load(), 300)
  }

  const openDetail = async (nodeId: string) => {
    if (!activeDomainId) return
    try {
      const d = await getBeliefDetail(activeDomainId, nodeId)
      setDetail(d)
      window.history.pushState({ belief: nodeId }, '', window.location.pathname)
    } catch { /* */ }
  }

  useEffect(() => {
    const handler = () => setDetail(null)
    window.addEventListener('popstate', handler)
    return () => window.removeEventListener('popstate', handler)
  }, [])

  const truthColor = (tv: string) => {
    if (tv === 'IN') return 'green'
    if (tv === 'OUT') return 'red'
    return 'yellow'
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
            <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsCenter' }} style={{ marginBottom: '0.75rem' }}>
              <FlexItem><Label color={truthColor(detail.truth_value)}>{detail.truth_value}</Label></FlexItem>
              <FlexItem><Label variant="outline">{detail.type}</Label></FlexItem>
              <FlexItem><Label variant="outline">depth {detail.depth}</Label></FlexItem>
            </Flex>
            <code style={{ fontSize: '0.8rem', display: 'block', marginBottom: '0.5rem' }}>{detail.id}</code>
            <Markdown content={detail.text} />
            {detail.source && (
              <div style={{ marginTop: '0.75rem', fontSize: '0.8rem', opacity: 0.7 }}>
                Source: {detail.source}
              </div>
            )}

            {detail.justifications.length > 0 && (
              <div style={{ marginTop: '1.5rem' }}>
                <h4 style={{ marginBottom: '0.5rem' }}>Justifications</h4>
                {detail.justifications.map((j, i) => (
                  <Card isCompact key={i} style={{ marginBottom: '0.5rem' }}>
                    <CardBody>
                      <Flex gap={{ default: 'gapSm' }} style={{ marginBottom: '0.25rem' }}>
                        <Label isCompact variant="outline">{j.type}</Label>
                        <span style={{ fontSize: '0.85rem' }}>{j.label}</span>
                      </Flex>
                      {j.antecedents.length > 0 && (
                        <div style={{ marginLeft: '1rem', fontSize: '0.85rem' }}>
                          <strong>Antecedents:</strong>
                          {j.antecedents.map(a => (
                            <div key={a.id} style={{ cursor: 'pointer', padding: '2px 0' }}
                              onClick={() => openDetail(a.id)}>
                              <Label isCompact color={truthColor(a.truth_value)}>{a.truth_value}</Label>{' '}
                              <code style={{ fontSize: '0.75rem' }}>{a.id}</code> — {(a.text || '').slice(0, 80)}
                            </div>
                          ))}
                        </div>
                      )}
                      {j.outlist.length > 0 && (
                        <div style={{ marginLeft: '1rem', fontSize: '0.85rem', marginTop: '0.25rem' }}>
                          <strong>Out-list:</strong>
                          {j.outlist.map(o => (
                            <div key={o.id} style={{ cursor: 'pointer', padding: '2px 0' }}
                              onClick={() => openDetail(o.id)}>
                              <Label isCompact color={truthColor(o.truth_value)}>{o.truth_value}</Label>{' '}
                              <code style={{ fontSize: '0.75rem' }}>{o.id}</code> — {(o.text || '').slice(0, 80)}
                            </div>
                          ))}
                        </div>
                      )}
                    </CardBody>
                  </Card>
                ))}
              </div>
            )}

            {detail.dependents.length > 0 && (
              <div style={{ marginTop: '1.5rem' }}>
                <h4 style={{ marginBottom: '0.5rem' }}>Dependents</h4>
                {detail.dependents.map(d => (
                  <div key={d.id} style={{ cursor: 'pointer', padding: '4px 0', fontSize: '0.85rem' }}
                    onClick={() => openDetail(d.id)}>
                    <Label isCompact color={truthColor(d.truth_value)}>{d.truth_value}</Label>{' '}
                    <code style={{ fontSize: '0.75rem' }}>{d.id}</code> — {(d.text || '').slice(0, 80)}
                  </div>
                ))}
              </div>
            )}

            {detail.metadata && Object.keys(detail.metadata).length > 0 && (
              <div style={{ marginTop: '1.5rem' }}>
                <h4 style={{ marginBottom: '0.5rem' }}>Metadata</h4>
                <pre style={{ fontSize: '0.75rem', whiteSpace: 'pre-wrap' }}>
                  {JSON.stringify(detail.metadata, null, 2)}
                </pre>
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Flex style={{ padding: '0.5rem 1rem', borderBottom: '1px solid var(--pf-t--global--border--color--default)' }}
        alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapSm' }} flexWrap={{ default: 'wrap' }}>
        <FlexItem grow={{ default: 'grow' }} style={{ maxWidth: 300 }}>
          <SearchInput placeholder="Search beliefs..." value={search}
            onChange={(_e, v) => handleSearch(v)}
            onClear={() => { setSearch(''); load() }} />
        </FlexItem>
        <FlexItem>
          <ToggleGroup>
            {TRUTH_FILTERS.map(f => (
              <ToggleGroupItem key={f} text={f} isSelected={truthFilter === f}
                onChange={() => setTruthFilter(f)} />
            ))}
          </ToggleGroup>
        </FlexItem>
        <FlexItem>
          <Select isOpen={sortOpen} selected={sort}
            onSelect={(_e, val) => { setSort(val as string); setSortOpen(false) }}
            onOpenChange={setSortOpen}
            toggle={(ref: React.Ref<MenuToggleElement>) => (
              <MenuToggle ref={ref} onClick={() => setSortOpen(!sortOpen)} isExpanded={sortOpen}>
                {SORT_OPTIONS.find(o => o.value === sort)?.label || 'Sort'}
              </MenuToggle>
            )}>
            {SORT_OPTIONS.map(o => (
              <SelectOption key={o.value} value={o.value}>{o.label}</SelectOption>
            ))}
          </Select>
        </FlexItem>
        <FlexItem>
          <Label isCompact>{beliefs.length} / {total}</Label>
        </FlexItem>
      </Flex>

      <div style={{ flex: 1, overflow: 'auto', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        {beliefs.length === 0 && (
          <EmptyState><EmptyStateBody>No beliefs found.</EmptyStateBody></EmptyState>
        )}
        {beliefs.map(b => (
          <Card isCompact key={b.id} isClickable onClick={() => openDetail(b.id)} style={{ cursor: 'pointer' }}>
            <CardBody>
              <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsCenter' }} style={{ marginBottom: '0.25rem' }}>
                <FlexItem><Label isCompact color={truthColor(b.truth_value)}>{b.truth_value}</Label></FlexItem>
                <FlexItem><Label isCompact variant="outline">{b.type}</Label></FlexItem>
                <FlexItem><Label isCompact variant="outline">d{b.depth}</Label></FlexItem>
                <FlexItem style={{ flex: 1 }}>
                  <code style={{ fontSize: '0.75rem' }}>{b.id.length > 40 ? b.id.slice(0, 40) + '...' : b.id}</code>
                </FlexItem>
              </Flex>
              <div style={{ fontSize: '0.85rem' }}>{(b.text || '').slice(0, 200)}{(b.text || '').length > 200 ? '...' : ''}</div>
            </CardBody>
          </Card>
        ))}
        {beliefs.length < total && (
          <Button variant="secondary" onClick={() => load(beliefs.length)} style={{ alignSelf: 'center', marginTop: 8 }}>
            Load more ({total - beliefs.length} remaining)
          </Button>
        )}
      </div>
    </div>
  )
}
