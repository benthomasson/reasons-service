import { useState, useRef } from 'react'
import {
  Button, Card, CardBody, Flex, FlexItem, Label,
  EmptyState, EmptyStateBody,
} from '@patternfly/react-core'
import { useTenant } from '../TenantContext'
import { uploadDocuments } from '../api'

export default function DocumentsPage() {
  const { domainId, domains } = useTenant()
  const [files, setFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  const domain = domains.find(d => d.id === domainId)

  const handleUpload = async () => {
    if (!files.length || !domainId) return
    setUploading(true)
    try {
      const result = await uploadDocuments(domainId, files)
      setUploadResult(`Uploaded ${result.imported} document(s)`)
      setFiles([])
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

  if (!domainId) {
    return (
      <div style={{ padding: '1rem', height: '100%' }}>
        <EmptyState><EmptyStateBody>Select a domain to manage documents.</EmptyStateBody></EmptyState>
      </div>
    )
  }

  return (
    <div style={{ padding: '1rem', overflow: 'auto', height: '100%', maxWidth: 700 }}>
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
  )
}
