import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Button, Card, CardBody, Flex, FlexItem, Label,
  EmptyState, EmptyStateBody,
  Tabs, Tab, TabTitleText,
} from '@patternfly/react-core'
import { useTenant } from '../TenantContext'
import { listSources, getSource, listEntries, getEntry, listSummaries, getSummary, uploadDocuments } from '../api'
import Markdown from './Markdown'
import type { SourceEntry, EntryItem, SummaryItem } from '../types'

type ActiveTab = 'sources' | 'summaries' | 'entries' | 'upload'

export default function DocumentsPage() {
  const { domainId, domains } = useTenant()
  const [activeTab, setActiveTab] = useState<ActiveTab>('upload')

  // Sources state
  const [sources, setSources] = useState<SourceEntry[]>([])
  const [sourceDetail, setSourceDetail] = useState<(SourceEntry & { content?: string; description?: string }) | null>(null)

  // Summaries state
  const [summaries, setSummaries] = useState<SummaryItem[]>([])
  const [summaryDetail, setSummaryDetail] = useState<(SummaryItem & { content?: string; sources?: { slug: string; title?: string }[] }) | null>(null)

  // Entries state
  const [entries, setEntries] = useState<EntryItem[]>([])
  const [entryDetail, setEntryDetail] = useState<(EntryItem & { content?: string }) | null>(null)

  // Upload state
  const [files, setFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  const domain = domains.find(d => d.id === domainId)

  const loadSources = useCallback(() => {
    if (!domainId) return
    listSources(domainId).then(d => setSources(d.sources)).catch(() => {})
  }, [domainId])

  const loadSummaries = useCallback(() => {
    if (!domainId) return
    listSummaries(domainId).then(d => setSummaries(d.summaries)).catch(() => {})
  }, [domainId])

  const loadEntries = useCallback(() => {
    if (!domainId) return
    listEntries(domainId).then(d => setEntries(d.entries)).catch(() => {})
  }, [domainId])

  useEffect(() => {
    if (activeTab === 'sources') loadSources()
    else if (activeTab === 'summaries') loadSummaries()
    else if (activeTab === 'entries') loadEntries()
  }, [activeTab, loadSources, loadSummaries, loadEntries])

  // Clear details on tab change
  useEffect(() => {
    setSourceDetail(null)
    setSummaryDetail(null)
    setEntryDetail(null)
  }, [activeTab])

  const openSource = async (slug: string) => {
    if (!domainId) return
    try {
      const d = await getSource(domainId, slug)
      setSourceDetail(d)
    } catch { /* */ }
  }

  const openSummary = async (id: string) => {
    if (!domainId) return
    try {
      const d = await getSummary(domainId, id)
      setSummaryDetail(d)
    } catch { /* */ }
  }

  const openEntry = async (id: string) => {
    if (!domainId) return
    try {
      const d = await getEntry(domainId, id)
      setEntryDetail(d)
    } catch { /* */ }
  }

  const handleUpload = async () => {
    if (!files.length || !domainId) return
    setUploading(true)
    try {
      const result = await uploadDocuments(domainId, files)
      setUploadResult(`Uploaded ${result.imported} document(s)`)
      setFiles([])
      loadSources()
    } catch (e) {
      setUploadResult(`Error: ${(e as Error).message}`)
    }
    setUploading(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const dropped = Array.from(e.dataTransfer.files)
    setFiles(prev => [...prev, ...dropped])
  }

  const formatDate = (iso?: string | null) => {
    if (!iso) return ''
    return new Date(iso).toLocaleString()
  }

  if (!domainId) {
    return (
      <div style={{ padding: '1rem', height: '100%' }}>
        <EmptyState><EmptyStateBody>Select a domain to view documents.</EmptyStateBody></EmptyState>
      </div>
    )
  }

  // Detail views
  if (sourceDetail) {
    return (
      <div style={{ padding: '1rem', overflow: 'auto', height: '100%' }}>
        <Button variant="secondary" size="sm" onClick={() => setSourceDetail(null)} style={{ marginBottom: '1rem' }}>Back</Button>
        <Card>
          <CardBody>
            <h3 style={{ marginBottom: '0.5rem' }}>{sourceDetail.title || sourceDetail.slug}</h3>
            <Flex gap={{ default: 'gapSm' }} style={{ marginBottom: '1rem' }} flexWrap={{ default: 'wrap' }}>
              <FlexItem><Label isCompact variant="outline">{sourceDetail.slug}</Label></FlexItem>
              {sourceDetail.author && <FlexItem><Label isCompact>{sourceDetail.author}</Label></FlexItem>}
              {sourceDetail.content_type && <FlexItem><Label isCompact variant="outline">{sourceDetail.content_type}</Label></FlexItem>}
              {sourceDetail.word_count && <FlexItem style={{ fontSize: '0.75rem', opacity: 0.6 }}>{sourceDetail.word_count} words</FlexItem>}
            </Flex>
            {sourceDetail.url && <p style={{ fontSize: '0.85rem', marginBottom: '0.5rem' }}><a href={sourceDetail.url} target="_blank" rel="noreferrer">{sourceDetail.url}</a></p>}
            {sourceDetail.description && <p style={{ fontSize: '0.85rem', marginTop: '0.5rem', marginBottom: '0.5rem' }}>{sourceDetail.description}</p>}
            {sourceDetail.content && <Markdown content={sourceDetail.content} />}
          </CardBody>
        </Card>
      </div>
    )
  }

  if (summaryDetail) {
    return (
      <div style={{ padding: '1rem', overflow: 'auto', height: '100%' }}>
        <Button variant="secondary" size="sm" onClick={() => setSummaryDetail(null)} style={{ marginBottom: '1rem' }}>Back</Button>
        <Card>
          <CardBody>
            <h3 style={{ marginBottom: '0.5rem' }}>{summaryDetail.title || summaryDetail.topic}</h3>
            <Flex gap={{ default: 'gapSm' }} style={{ marginBottom: '1rem' }}>
              <FlexItem><Label isCompact variant="outline">{summaryDetail.topic}</Label></FlexItem>
              <FlexItem style={{ fontSize: '0.75rem', opacity: 0.6 }}>{formatDate(summaryDetail.created_at)}</FlexItem>
            </Flex>
            {summaryDetail.content && <Markdown content={summaryDetail.content} />}
            {summaryDetail.sources && summaryDetail.sources.length > 0 && (
              <div style={{ marginTop: '1rem' }}>
                <strong style={{ fontSize: '0.85rem' }}>Sources:</strong>
                {summaryDetail.sources.map((src: { slug: string; title?: string }) => (
                  <div key={src.slug} style={{ fontSize: '0.85rem', cursor: 'pointer', color: 'var(--pf-t--global--color--brand--default)' }}
                    onClick={() => { setSummaryDetail(null); setActiveTab('sources'); setTimeout(() => openSource(src.slug), 100) }}>
                    {src.title || src.slug}
                  </div>
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    )
  }

  if (entryDetail) {
    return (
      <div style={{ padding: '1rem', overflow: 'auto', height: '100%' }}>
        <Button variant="secondary" size="sm" onClick={() => setEntryDetail(null)} style={{ marginBottom: '1rem' }}>Back</Button>
        <Card>
          <CardBody>
            <h3 style={{ marginBottom: '0.5rem' }}>{entryDetail.title || entryDetail.topic}</h3>
            <Flex gap={{ default: 'gapSm' }} style={{ marginBottom: '1rem' }}>
              <FlexItem><Label isCompact variant="outline">{entryDetail.topic}</Label></FlexItem>
              <FlexItem style={{ fontSize: '0.75rem', opacity: 0.6 }}>{formatDate(entryDetail.created_at)}</FlexItem>
            </Flex>
            {entryDetail.content && <Markdown content={entryDetail.content} wikitext />}
          </CardBody>
        </Card>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Tabs activeKey={activeTab} onSelect={(_e, key) => setActiveTab(key as ActiveTab)}
        style={{ borderBottom: '1px solid var(--pf-t--global--border--color--default)' }}>
        <Tab eventKey="upload" title={<TabTitleText>Upload</TabTitleText>} />
        <Tab eventKey="sources" title={<TabTitleText>Sources ({sources.length})</TabTitleText>} />
        <Tab eventKey="summaries" title={<TabTitleText>Summaries ({summaries.length})</TabTitleText>} />
        <Tab eventKey="entries" title={<TabTitleText>Entries ({entries.length})</TabTitleText>} />
      </Tabs>

      <div style={{ flex: 1, overflow: 'auto', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        {activeTab === 'sources' && (
          <>
            {sources.length === 0 && <EmptyState><EmptyStateBody>No sources found.</EmptyStateBody></EmptyState>}
            {sources.map(s => (
              <Card isCompact key={s.slug} isClickable onClick={() => openSource(s.slug)} style={{ cursor: 'pointer' }}>
                <CardBody>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.25rem' }}>
                    {s.title || s.slug}
                  </div>
                  <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsCenter' }}>
                    <FlexItem><Label isCompact variant="outline">{s.slug}</Label></FlexItem>
                    {s.word_count && <FlexItem style={{ fontSize: '0.75rem', opacity: 0.6 }}>{s.word_count} words</FlexItem>}
                    {s.content_type && <FlexItem><Label isCompact>{s.content_type}</Label></FlexItem>}
                  </Flex>
                </CardBody>
              </Card>
            ))}
          </>
        )}

        {activeTab === 'summaries' && (
          <>
            {summaries.length === 0 && <EmptyState><EmptyStateBody>No summaries found.</EmptyStateBody></EmptyState>}
            {summaries.map(s => (
              <Card isCompact key={s.id} isClickable onClick={() => openSummary(s.id)} style={{ cursor: 'pointer' }}>
                <CardBody>
                  <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.25rem' }}>
                    {s.title || s.topic}
                  </div>
                  <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsCenter' }}>
                    <FlexItem><Label isCompact variant="outline">{s.topic}</Label></FlexItem>
                    <FlexItem style={{ fontSize: '0.75rem', opacity: 0.6 }}>{formatDate(s.created_at)}</FlexItem>
                    {s.source_slugs && s.source_slugs.length > 0 && (
                      <FlexItem style={{ fontSize: '0.75rem', opacity: 0.6 }}>{s.source_slugs.length} source(s)</FlexItem>
                    )}
                  </Flex>
                </CardBody>
              </Card>
            ))}
          </>
        )}

        {activeTab === 'entries' && (
          <>
            {entries.length === 0 && <EmptyState><EmptyStateBody>No entries found.</EmptyStateBody></EmptyState>}
            {entries.map(e => (
              <Card isCompact key={e.id} isClickable onClick={() => openEntry(e.id)} style={{ cursor: 'pointer' }}>
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
          </>
        )}

        {activeTab === 'upload' && (
          <div style={{ maxWidth: 700 }}>
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              style={{
                border: `2px dashed ${dragOver ? 'var(--pf-t--global--color--brand--default)' : 'var(--pf-t--global--border--color--default)'}`,
                borderRadius: 8, padding: '2rem', textAlign: 'center', cursor: 'pointer',
                marginBottom: '1rem', transition: 'border-color 0.2s',
              }}
            >
              <p>Drop files here or click to browse</p>
              <p style={{ fontSize: '0.8rem', opacity: 0.6 }}>Markdown, text, PDF, VTT</p>
              <input ref={fileInputRef} type="file" multiple accept=".md,.txt,.pdf,.vtt"
                style={{ display: 'none' }}
                onChange={(e) => setFiles(prev => [...prev, ...Array.from(e.target.files || [])])} />
            </div>

            {files.length > 0 && (
              <Card isCompact style={{ marginBottom: '1rem' }}>
                <CardBody>
                  <div style={{ marginBottom: '0.5rem' }}>
                    {files.map((f, i) => (
                      <div key={i} style={{ fontSize: '0.85rem' }}>{f.name} ({(f.size / 1024).toFixed(1)} KB)</div>
                    ))}
                  </div>
                  <Flex gap={{ default: 'gapSm' }}>
                    <Button variant="primary" size="sm" onClick={handleUpload} isDisabled={uploading}>
                      {uploading ? 'Uploading...' : 'Upload'}
                    </Button>
                    <Button variant="link" size="sm" onClick={() => setFiles([])}>Clear</Button>
                  </Flex>
                </CardBody>
              </Card>
            )}

            {uploadResult && (
              <Label isCompact color={uploadResult.startsWith('Error') ? 'red' : 'green'} style={{ marginBottom: '1rem' }}>
                {uploadResult}
              </Label>
            )}

            <Card isCompact>
              <CardBody>
                <p style={{ fontSize: '0.85rem' }}>
                  Import source documents into the domain. Supported formats: Markdown, plain text, PDF, VTT.
                </p>
                <p style={{ fontSize: '0.75rem', opacity: 0.6, marginTop: '0.25rem' }}>
                  Domain: {domain?.name || domainId}
                </p>
              </CardBody>
            </Card>
          </div>
        )}
      </div>
    </div>
  )
}
