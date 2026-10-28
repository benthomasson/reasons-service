import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  Button, Flex, FlexItem,
  EmptyState, EmptyStateBody, Spinner,
  ToggleGroup, ToggleGroupItem,
} from '@patternfly/react-core'
import { Message, MessageBar, MessageLoading } from '@patternfly/chatbot'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { useTenant } from '../TenantContext'
import { streamChat, listConversations, getConversation, deleteConversation, listPersonas } from '../api'
import type { ChatMessage } from '../types'
import type { Conversation, PersonaSummary } from '../api'

export default function ChatPage() {
  const { domain: routeDomain } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const { domainId, setDomainId, domains } = useTenant()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [streamBuf, setStreamBuf] = useState('')
  const [toolActivity, setToolActivity] = useState<string[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<(() => void) | null>(null)

  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const prefillConsumed = useRef(false)

  const [personas, setPersonas] = useState<PersonaSummary[]>([])
  const [activePersonaId, setActivePersonaId] = useState<string | null>(null)
  const [chatMode, setChatMode] = useState<'domain' | 'persona'>('domain')

  useEffect(() => {
    return () => { abortRef.current?.() }
  }, [])

  useEffect(() => {
    listPersonas().then(setPersonas).catch(() => {})
  }, [])

  const activeDomainId = routeDomain
    ? domains.find(d => d.name.toLowerCase() === routeDomain.toLowerCase() || d.id === routeDomain)?.id || domainId
    : domainId

  useEffect(() => {
    if (routeDomain && activeDomainId && activeDomainId !== domainId) {
      setDomainId(activeDomainId)
    }
  }, [routeDomain, activeDomainId, domainId, setDomainId])

  const loadConversations = useCallback(() => {
    if (chatMode === 'domain' && !activeDomainId) return
    if (chatMode === 'persona' && !activePersonaId) return
    const domainFilter = chatMode === 'domain' ? activeDomainId : undefined
    listConversations(domainFilter).then(convs => {
      if (chatMode === 'persona' && activePersonaId) {
        setConversations(convs.filter(c => c.persona_id === activePersonaId))
      } else {
        setConversations(convs)
      }
    }).catch(() => {})
  }, [activeDomainId, activePersonaId, chatMode])

  useEffect(() => { loadConversations() }, [loadConversations])

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(scrollToBottom, [messages, streamBuf, scrollToBottom])

  const openConversation = useCallback(async (convId: string) => {
    if (streaming) return
    try {
      const conv = await getConversation(convId)
      setActiveConversationId(convId)
      setMessages(conv.messages.map(m => ({ role: m.role as 'user' | 'assistant', content: m.content })))
      setStreamBuf('')
      setToolActivity([])
    } catch { /* */ }
  }, [streaming])

  const handleDeleteConversation = useCallback(async (convId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await deleteConversation(convId)
      if (activeConversationId === convId) {
        setActiveConversationId(null)
        setMessages([])
      }
      loadConversations()
    } catch { /* */ }
  }, [activeConversationId, loadConversations])

  const canSend = chatMode === 'domain' ? !!activeDomainId : !!activePersonaId

  const handleSend = useCallback(async (message: string) => {
    if (!message.trim() || !canSend || streaming) return

    const userMsg: ChatMessage = { role: 'user', content: message }
    setMessages(prev => [...prev, userMsg])
    setStreaming(true)
    setStreamBuf('')
    setToolActivity([])

    const history = messages.slice(-20).map(m => ({ role: m.role, content: m.content }))

    const body: Parameters<typeof streamChat>[0] = {
      message,
      conversation_id: activeConversationId || undefined,
      history,
    }
    if (chatMode === 'persona' && activePersonaId) {
      body.persona_id = activePersonaId
    } else if (activeDomainId) {
      body.domain_id = activeDomainId
    }

    const { response, abort } = streamChat(body)
    abortRef.current = abort

    try {
      const resp = await response
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}))
        setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${(err as { detail?: string }).detail || resp.statusText}` }])
        setStreaming(false)
        return
      }

      const reader = resp.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let fullResponse = ''
      let addedDone = false

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop()!

        for (const part of parts) {
          const lines = part.split('\n')
          let data = ''
          for (const line of lines) {
            if (line.startsWith('data: ')) data += (data ? '\n' : '') + line.slice(6)
          }
          if (!data) continue

          try {
            const evt = JSON.parse(data)
            const eventType = evt.type

            if (eventType === 'status') {
              if (evt.content) setToolActivity(prev => [...prev, evt.content])
            } else if (eventType === 'tool_call') {
              const label = evt.name === 'search_beliefs' ? `Searching: "${evt.args?.query || ''}"` : `${evt.name}: ${evt.args?.id || ''}`
              setToolActivity(prev => [...prev, label])
            } else if (eventType === 'token') {
              fullResponse += evt.content
              setStreamBuf(fullResponse)
            } else if (eventType === 'done') {
              addedDone = true
              setMessages(prev => [...prev, { role: 'assistant', content: fullResponse }])
              setStreamBuf('')
              if (evt.conversation_id) {
                setActiveConversationId(evt.conversation_id)
                loadConversations()
              }
            } else if (eventType === 'error') {
              setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${evt.content || 'Unknown error'}` }])
              setStreamBuf('')
            }
          } catch { /* ignore unparseable lines */ }
        }
      }

      if (fullResponse && !addedDone) {
        setMessages(prev => {
          const last = prev[prev.length - 1]
          if (last?.role !== 'assistant' || last.content !== fullResponse) {
            return [...prev, { role: 'assistant', content: fullResponse }]
          }
          return prev
        })
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${(e as Error).message}` }])
      }
    } finally {
      setStreaming(false)
      setStreamBuf('')
      abortRef.current = null
    }
  }, [activeDomainId, activePersonaId, chatMode, canSend, streaming, messages, activeConversationId, loadConversations])

  useEffect(() => {
    const prefill = searchParams.get('prefill')
    if (prefill && canSend && !streaming && !prefillConsumed.current) {
      prefillConsumed.current = true
      setSearchParams({}, { replace: true })
      handleSend(prefill)
    }
  }, [canSend, streaming, searchParams, setSearchParams, handleSend])

  const newChat = () => {
    setMessages([])
    setToolActivity([])
    setStreamBuf('')
    setActiveConversationId(null)
  }

  const reactMarkdownProps = { remarkPlugins: [remarkMath], rehypePlugins: [rehypeKatex] }

  const formatDate = (iso: string | null) => {
    if (!iso) return ''
    const d = new Date(iso)
    const now = new Date()
    if (d.toDateString() === now.toDateString()) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
  }

  const activePersona = personas.find(p => p.id === activePersonaId)
  const emptyMessage = chatMode === 'domain'
    ? (activeDomainId ? 'Ask a question to get answers grounded in justified beliefs.' : 'Select a domain to start chatting.')
    : (activePersonaId
        ? `Chatting with ${activePersona?.name || 'persona'} (${activePersona?.domains.map(d => d.name).join(', ')})`
        : 'Select a persona to start chatting.')

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      {sidebarOpen && (
        <div style={{
          width: 260, borderRight: '1px solid var(--pf-t--global--border--color--default)',
          display: 'flex', flexDirection: 'column', overflow: 'hidden',
        }}>
          <div style={{ padding: '0.5rem', borderBottom: '1px solid var(--pf-t--global--border--color--default)' }}>
            <Button variant="primary" size="sm" isBlock onClick={newChat}>New Chat</Button>
          </div>

          {personas.length > 0 && (
            <div style={{ padding: '0.5rem', borderBottom: '1px solid var(--pf-t--global--border--color--default)' }}>
              <ToggleGroup isCompact>
                <ToggleGroupItem
                  text="Domain"
                  isSelected={chatMode === 'domain'}
                  onChange={() => { setChatMode('domain'); newChat() }}
                />
                <ToggleGroupItem
                  text="Persona"
                  isSelected={chatMode === 'persona'}
                  onChange={() => { setChatMode('persona'); newChat() }}
                />
              </ToggleGroup>

              {chatMode === 'persona' && (
                <div style={{ marginTop: '0.5rem' }}>
                  {personas.map(p => (
                    <div
                      key={p.id}
                      onClick={() => { setActivePersonaId(p.id); newChat() }}
                      style={{
                        padding: '0.4rem 0.5rem', cursor: 'pointer', fontSize: '0.8rem',
                        borderRadius: 'var(--pf-t--global--border--radius--pill)',
                        marginBottom: '0.25rem',
                        background: p.id === activePersonaId ? 'var(--pf-t--global--background--color--brand--default)' : undefined,
                        color: p.id === activePersonaId ? 'var(--pf-t--global--text--color--on-brand--default)' : undefined,
                      }}
                    >
                      <div style={{ fontWeight: p.id === activePersonaId ? 600 : 400 }}>{p.name}</div>
                      <div style={{ fontSize: '0.7rem', opacity: 0.7 }}>
                        {p.domains.map(d => d.name).join(', ')}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <div style={{ flex: 1, overflowY: 'auto' }}>
            {conversations.length === 0 && (
              <div style={{ padding: '1rem', fontSize: '0.8rem', opacity: 0.6, textAlign: 'center' }}>
                No conversations yet
              </div>
            )}
            {conversations.map(c => (
              <div
                key={c.id}
                onClick={() => openConversation(c.id)}
                style={{
                  padding: '0.5rem 0.75rem', cursor: 'pointer', fontSize: '0.8rem',
                  borderBottom: '1px solid var(--pf-t--global--border--color--default)',
                  background: c.id === activeConversationId ? 'var(--pf-t--global--background--color--primary--default)' : undefined,
                  color: c.id === activeConversationId ? 'var(--pf-t--global--text--color--on-brand--default)' : undefined,
                }}
              >
                <div style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.25rem',
                }}>
                  <div style={{
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1,
                    fontWeight: c.id === activeConversationId ? 600 : 400,
                  }}>
                    {c.title || 'Untitled'}
                  </div>
                  <button
                    onClick={(e) => handleDeleteConversation(c.id, e)}
                    style={{
                      background: 'none', border: 'none', cursor: 'pointer', padding: '2px 4px',
                      fontSize: '0.7rem', opacity: 0.5, color: 'inherit',
                    }}
                    title="Delete"
                  >
                    &#x2715;
                  </button>
                </div>
                <div style={{ fontSize: '0.7rem', opacity: 0.6, marginTop: '2px' }}>
                  {formatDate(c.updated_at)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapMd' }}
          style={{ padding: '0.5rem 1rem', borderBottom: '1px solid var(--pf-t--global--border--color--default)' }}>
          <FlexItem>
            <Button variant="plain" size="sm" onClick={() => setSidebarOpen(!sidebarOpen)}>
              &#9776;
            </Button>
          </FlexItem>
          {!sidebarOpen && (
            <FlexItem>
              <Button variant="plain" size="sm" onClick={newChat}>New Chat</Button>
            </FlexItem>
          )}
          {chatMode === 'persona' && activePersona && (
            <FlexItem>
              <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>{activePersona.name}</span>
              <span style={{ fontSize: '0.75rem', opacity: 0.6, marginLeft: '0.5rem' }}>
                {activePersona.domains.map(d => d.name).join(', ')}
              </span>
            </FlexItem>
          )}
        </Flex>

        <div style={{ flex: 1, overflowY: 'auto', padding: '1rem' }}>
          {messages.length === 0 && !streaming && (
            <EmptyState>
              <EmptyStateBody>{emptyMessage}</EmptyStateBody>
            </EmptyState>
          )}

          {messages.map((msg, i) => (
            <Message key={i} role={msg.role === 'user' ? 'user' : 'bot'}
              name={msg.role === 'user' ? 'You' : (chatMode === 'persona' && activePersona ? activePersona.name : 'Assistant')}
              content={msg.content}
              reactMarkdownProps={reactMarkdownProps}
            />
          ))}

          {streaming && toolActivity.length > 0 && (
            <div style={{ padding: '0.5rem 1rem', fontSize: '0.8rem', opacity: 0.7 }}>
              {toolActivity.map((t, i) => <div key={i}>{t}</div>)}
            </div>
          )}

          {streaming && streamBuf && (
            <Message role="bot" name={chatMode === 'persona' && activePersona ? activePersona.name : 'Assistant'}
              content={streamBuf} reactMarkdownProps={reactMarkdownProps} />
          )}

          {streaming && !streamBuf && <MessageLoading />}

          <div ref={messagesEndRef} />
        </div>

        <div style={{ padding: '0.5rem 1rem', borderTop: '1px solid var(--pf-t--global--border--color--default)' }}>
          <MessageBar
            onSendMessage={(message) => handleSend(typeof message === 'string' ? message : '')}
            hasAttachButton={false}
            isSendButtonDisabled={streaming || !canSend}
          />
        </div>
      </div>
    </div>
  )
}
