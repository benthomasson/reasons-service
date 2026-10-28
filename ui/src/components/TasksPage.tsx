import { useState, useEffect, useCallback } from 'react'
import {
  Button, Flex, FlexItem,
  EmptyState, EmptyStateBody, Spinner,
  Label, Split, SplitItem,
  DescriptionList, DescriptionListGroup, DescriptionListTerm, DescriptionListDescription,
  Select, SelectOption, MenuToggle, type MenuToggleElement,
} from '@patternfly/react-core'
import { useTenant } from '../TenantContext'
import { listTasks, createTask, cancelTask } from '../api'
import type { TaskSummary } from '../api'

const STATUS_COLORS: Record<string, 'blue' | 'green' | 'red' | 'orange' | 'grey'> = {
  pending: 'blue',
  running: 'orange',
  completed: 'green',
  failed: 'red',
  cancelled: 'grey',
}

export default function TasksPage() {
  const { domainId } = useTenant()
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedTask, setSelectedTask] = useState<TaskSummary | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  const loadTasks = useCallback(() => {
    setLoading(true)
    listTasks(domainId || undefined)
      .then(setTasks)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [domainId])

  useEffect(() => { loadTasks() }, [loadTasks])

  // Auto-refresh when there are active tasks
  useEffect(() => {
    const hasActive = tasks.some(t => t.status === 'pending' || t.status === 'running')
    if (!hasActive) return
    const interval = setInterval(loadTasks, 3000)
    return () => clearInterval(interval)
  }, [tasks, loadTasks])

  const handleCreate = async (type: string, config: Record<string, unknown> = {}) => {
    if (!domainId) return
    await createTask({ domain_id: domainId, type, config })
    loadTasks()
  }

  const handleCancel = async (id: string) => {
    await cancelTask(id)
    loadTasks()
  }

  const formatDate = (iso: string | null) => {
    if (!iso) return '-'
    return new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }

  const formatDuration = (start: string | null, end: string | null) => {
    if (!start) return '-'
    const s = new Date(start).getTime()
    const e = end ? new Date(end).getTime() : Date.now()
    const sec = Math.round((e - s) / 1000)
    if (sec < 60) return `${sec}s`
    return `${Math.floor(sec / 60)}m ${sec % 60}s`
  }

  if (loading && tasks.length === 0) {
    return <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem' }}><Spinner size="lg" /></div>
  }

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      <div style={{
        width: 360, borderRight: '1px solid var(--pf-t--global--border--color--default)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
      }}>
        <div style={{ padding: '0.5rem', borderBottom: '1px solid var(--pf-t--global--border--color--default)' }}>
          <Flex>
            <FlexItem flex={{ default: 'flex_1' }}>
              <Select
                isOpen={createOpen}
                onOpenChange={setCreateOpen}
                onSelect={(_e, value) => {
                  setCreateOpen(false)
                  if (value === 'document_forge') handleCreate('document_forge', { model: 'openai:gpt-5.6-luna', rounds: 1 })
                  else if (value === 'derive_review_repair') handleCreate('derive_review_repair', { model: 'openai:gpt-5.6-luna', rounds: 3 })
                  else if (value === 'echo') handleCreate('echo', { message: 'Test task', steps: 5, delay: 2 })
                }}
                toggle={(ref: React.Ref<MenuToggleElement>) => (
                  <MenuToggle ref={ref} onClick={() => setCreateOpen(!createOpen)} isExpanded={createOpen}
                    isDisabled={!domainId} isFullWidth variant="primary">
                    Run Task
                  </MenuToggle>
                )}
              >
                <SelectOption value="document_forge">Document Forge</SelectOption>
                <SelectOption value="derive_review_repair">Derive / Review / Repair</SelectOption>
                <SelectOption value="echo">Echo (test)</SelectOption>
              </Select>
            </FlexItem>
            <FlexItem>
              <Button variant="plain" size="sm" onClick={loadTasks}>Refresh</Button>
            </FlexItem>
          </Flex>
        </div>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          {tasks.length === 0 && (
            <EmptyState>
              <EmptyStateBody>No tasks yet. Select a domain and run a test task.</EmptyStateBody>
            </EmptyState>
          )}
          {tasks.map(t => (
            <div
              key={t.id}
              onClick={() => setSelectedTask(t)}
              style={{
                padding: '0.5rem 0.75rem', cursor: 'pointer', fontSize: '0.8rem',
                borderBottom: '1px solid var(--pf-t--global--border--color--default)',
                background: selectedTask?.id === t.id ? 'var(--pf-t--global--color--brand--default)' : undefined,
                color: selectedTask?.id === t.id ? 'var(--pf-t--global--text--color--inverse)' : undefined,
              }}
            >
              <Split hasGutter>
                <SplitItem isFilled>
                  <div style={{ fontWeight: selectedTask?.id === t.id ? 600 : 400 }}>
                    {t.type}
                  </div>
                  <div style={{ fontSize: '0.7rem', opacity: 0.7, marginTop: '2px' }}>
                    {t.id.slice(0, 8)} &middot; {formatDate(t.created_at)}
                  </div>
                </SplitItem>
                <SplitItem>
                  <Label color={STATUS_COLORS[t.status] || 'grey'} isCompact>{t.status}</Label>
                </SplitItem>
              </Split>
              {t.status === 'running' && t.progress && (t.progress as { step?: number; total?: number }).step != null && (
                <div style={{ marginTop: '4px' }}>
                  <div style={{
                    height: 4, borderRadius: 2,
                    background: 'var(--pf-t--global--border--color--default)',
                  }}>
                    <div style={{
                      height: '100%', borderRadius: 2,
                      background: 'var(--pf-t--global--color--brand--default)',
                      width: `${((t.progress as { step: number; total: number }).step / (t.progress as { step: number; total: number }).total) * 100}%`,
                      transition: 'width 0.3s',
                    }} />
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div style={{ flex: 1, padding: '1rem', overflowY: 'auto' }}>
        {!selectedTask ? (
          <EmptyState>
            <EmptyStateBody>Select a task to view details</EmptyStateBody>
          </EmptyState>
        ) : (
          <div>
            <Flex justifyContent={{ default: 'justifyContentSpaceBetween' }} alignItems={{ default: 'alignItemsCenter' }}
              style={{ marginBottom: '1rem' }}>
              <FlexItem>
                <span style={{ fontSize: '1.1rem', fontWeight: 600 }}>{selectedTask.type}</span>
                <Label color={STATUS_COLORS[selectedTask.status] || 'grey'} style={{ marginLeft: '0.5rem' }}>
                  {selectedTask.status}
                </Label>
              </FlexItem>
              {(selectedTask.status === 'pending' || selectedTask.status === 'running') && (
                <FlexItem>
                  <Button variant="danger" size="sm" onClick={() => handleCancel(selectedTask.id)}>Cancel</Button>
                </FlexItem>
              )}
            </Flex>

            <DescriptionList isHorizontal>
              <DescriptionListGroup>
                <DescriptionListTerm>ID</DescriptionListTerm>
                <DescriptionListDescription style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
                  {selectedTask.id}
                </DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Domain</DescriptionListTerm>
                <DescriptionListDescription style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
                  {selectedTask.domain_id}
                </DescriptionListDescription>
              </DescriptionListGroup>
              {selectedTask.job_name && (
                <DescriptionListGroup>
                  <DescriptionListTerm>Job</DescriptionListTerm>
                  <DescriptionListDescription>{selectedTask.job_name}</DescriptionListDescription>
                </DescriptionListGroup>
              )}
              <DescriptionListGroup>
                <DescriptionListTerm>Created</DescriptionListTerm>
                <DescriptionListDescription>{formatDate(selectedTask.created_at)}</DescriptionListDescription>
              </DescriptionListGroup>
              <DescriptionListGroup>
                <DescriptionListTerm>Duration</DescriptionListTerm>
                <DescriptionListDescription>
                  {formatDuration(selectedTask.started_at, selectedTask.completed_at)}
                </DescriptionListDescription>
              </DescriptionListGroup>
            </DescriptionList>

            {selectedTask.config && Object.keys(selectedTask.config).length > 0 && (
              <div style={{ marginTop: '1rem' }}>
                <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem' }}>Config</h4>
                <pre style={{
                  fontSize: '0.75rem', padding: '0.5rem',
                  background: 'var(--pf-t--global--background--color--secondary--default)',
                  borderRadius: 'var(--pf-t--global--border--radius--small)',
                  overflow: 'auto',
                }}>
                  {JSON.stringify(selectedTask.config, null, 2)}
                </pre>
              </div>
            )}

            {selectedTask.progress && Object.keys(selectedTask.progress).length > 0 && (
              <div style={{ marginTop: '1rem' }}>
                <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem' }}>Progress</h4>
                <pre style={{
                  fontSize: '0.75rem', padding: '0.5rem',
                  background: 'var(--pf-t--global--background--color--secondary--default)',
                  borderRadius: 'var(--pf-t--global--border--radius--small)',
                  overflow: 'auto',
                }}>
                  {JSON.stringify(selectedTask.progress, null, 2)}
                </pre>
              </div>
            )}

            {selectedTask.result && (
              <div style={{ marginTop: '1rem' }}>
                <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem' }}>Result</h4>
                <pre style={{
                  fontSize: '0.75rem', padding: '0.5rem',
                  background: 'var(--pf-t--global--background--color--secondary--default)',
                  borderRadius: 'var(--pf-t--global--border--radius--small)',
                  overflow: 'auto',
                }}>
                  {JSON.stringify(selectedTask.result, null, 2)}
                </pre>
              </div>
            )}

            {selectedTask.error && (
              <div style={{ marginTop: '1rem' }}>
                <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--pf-t--global--color--status--danger--default)' }}>Error</h4>
                <pre style={{
                  fontSize: '0.75rem', padding: '0.5rem',
                  background: 'var(--pf-t--global--background--color--danger--default)',
                  borderRadius: 'var(--pf-t--global--border--radius--small)',
                  overflow: 'auto',
                }}>
                  {selectedTask.error}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
