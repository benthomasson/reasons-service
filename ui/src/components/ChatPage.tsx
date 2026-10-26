import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  Button, Checkbox, Flex, FlexItem,
  EmptyState, EmptyStateBody, Spinner,
} from '@patternfly/react-core'
import { Message, MessageBar, MessageLoading } from '@patternfly/chatbot'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { useTenant } from '../TenantContext'
import { streamChat } from '../api'
import type { ChatMessage } from '../types'

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

  useEffect(() => {
    return () => { abortRef.current?.() }
  }, [])

  const activeDomainId = routeDomain
    ? domains.find(d => d.name.toLowerCase() === routeDomain.toLowerCase() || d.id === routeDomain)?.id || domainId
    : domainId

  useEffect(() => {
    if (routeDomain && activeDomainId && activeDomainId !== domainId) {
      setDomainId(activeDomainId)
    }
  }, [routeDomain, activeDomainId, domainId, setDomainId])

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(scrollToBottom, [messages, streamBuf, scrollToBottom])

  const handleSend = useCallback(async (message: string) => {
    if (!message.trim() || !activeDomainId || streaming) return

    const userMsg: ChatMessage = { role: 'user', content: message }
    setMessages(prev => [...prev, userMsg])
    setStreaming(true)
    setStreamBuf('')
    setToolActivity([])

    const history = messages.slice(-20).map(m => ({ role: m.role, content: m.content }))

    const { response, abort } = streamChat({
      domain_id: activeDomainId,
      message,
      history,
    })
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
          let event = 'message'
          let data = ''
          for (const line of lines) {
            if (line.startsWith('event: ')) event = line.slice(7)
            else if (line.startsWith('data: ')) data += line.slice(6)
          }

          if (event === 'status') {
            try {
              const text = JSON.parse(data).text
              if (text) setToolActivity(prev => [...prev, text])
            } catch { /* */ }
          } else if (event === 'tool_call') {
            try {
              const tc = JSON.parse(data)
              const label = tc.name === 'search_beliefs' ? `Searching: "${tc.arguments?.query || ''}"` : `${tc.name}: ${tc.arguments?.id || ''}`
              setToolActivity(prev => [...prev, label])
            } catch { /* */ }
          } else if (event === 'token') {
            try {
              const tokenData = JSON.parse(data)
              fullResponse += tokenData.content
              setStreamBuf(fullResponse)
            } catch { /* */ }
          } else if (event === 'done') {
            addedDone = true
            setMessages(prev => [...prev, { role: 'assistant', content: fullResponse }])
            setStreamBuf('')
          } else if (event === 'error') {
            try {
              setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${JSON.parse(data).message}` }])
            } catch { /* */ }
            setStreamBuf('')
          }
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
  }, [activeDomainId, streaming, messages])

  useEffect(() => {
    const prefill = searchParams.get('prefill')
    if (prefill && activeDomainId && !streaming) {
      setSearchParams({}, { replace: true })
      handleSend(prefill)
    }
  }, [activeDomainId]) // eslint-disable-line react-hooks/exhaustive-deps

  const newChat = () => {
    setMessages([])
    setToolActivity([])
    setStreamBuf('')
  }

  const reactMarkdownProps = { remarkPlugins: [remarkMath], rehypePlugins: [rehypeKatex] }

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gapMd' }}
          style={{ padding: '0.5rem 1rem', borderBottom: '1px solid var(--pf-t--global--border--color--default)' }}>
          <FlexItem>
            <Button variant="plain" size="sm" onClick={newChat}>New Chat</Button>
          </FlexItem>
        </Flex>

        <div style={{ flex: 1, overflowY: 'auto', padding: '1rem' }}>
          {messages.length === 0 && !streaming && (
            <EmptyState>
              <EmptyStateBody>
                {activeDomainId
                  ? 'Ask a question to get answers grounded in justified beliefs.'
                  : 'Select a domain to start chatting.'}
              </EmptyStateBody>
            </EmptyState>
          )}

          {messages.map((msg, i) => (
            <Message key={i} role={msg.role === 'user' ? 'user' : 'bot'}
              name={msg.role === 'user' ? 'You' : 'Assistant'}
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
            <Message role="bot" name="Assistant" content={streamBuf} reactMarkdownProps={reactMarkdownProps} />
          )}

          {streaming && !streamBuf && <MessageLoading />}

          <div ref={messagesEndRef} />
        </div>

        <div style={{ padding: '0.5rem 1rem', borderTop: '1px solid var(--pf-t--global--border--color--default)' }}>
          <MessageBar
            onSendMessage={(message) => handleSend(typeof message === 'string' ? message : '')}
            hasAttachButton={false}
            isSendButtonDisabled={streaming || !activeDomainId}
          />
        </div>
      </div>
    </div>
  )
}
