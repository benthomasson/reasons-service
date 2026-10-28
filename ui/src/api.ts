import type {
  UserInfo, Domain, Belief, BeliefDetail, Proposal,
  ChatMessage, EntryItem, SourceEntry, SummaryItem, Topic, DomainOverview,
  Tenant, TenantMember,
} from './types'

function headers(json = false): Record<string, string> {
  const h: Record<string, string> = {}
  if (json) h['Content-Type'] = 'application/json'
  return h
}

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    ...init,
    credentials: 'same-origin',
    headers: { ...headers(!!init?.body && !(init.body instanceof FormData)), ...init?.headers },
  })
  if (resp.status === 401) {
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`
    throw new Error('Unauthorized')
  }
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}))
    throw new Error((data as { detail?: string }).detail || resp.statusText)
  }
  return resp.json()
}

// --- Auth ---

export async function getMe(): Promise<UserInfo> {
  return fetchJSON('/api/auth/me')
}

// --- Tenants ---

export async function listTenants(): Promise<Tenant[]> {
  const data = await fetchJSON<{ items: Tenant[] }>('/api/tenants')
  return data.items
}

export async function listTenantMembers(tenantId: string): Promise<TenantMember[]> {
  const data = await fetchJSON<{ items: TenantMember[] }>(`/api/tenants/${tenantId}/members`)
  return data.items
}

// --- Domains ---

export async function listDomains(): Promise<Domain[]> {
  const data = await fetchJSON<{ items: Domain[] }>('/api/domains')
  return data.items
}

export async function getDomain(domainId: string): Promise<Domain> {
  return fetchJSON(`/api/domains/${domainId}`)
}

export async function createDomain(body: { name: string; description?: string; tenant_id?: string }): Promise<Domain> {
  return fetchJSON('/api/domains', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

// --- Beliefs ---

export async function listBeliefs(
  domainId: string,
  params?: { status?: string; sort?: string; offset?: number; limit?: number },
): Promise<{ beliefs: Belief[]; total: number }> {
  const q = new URLSearchParams()
  if (params?.status) q.set('status', params.status)
  if (params?.sort) q.set('sort', params.sort)
  if (params?.offset) q.set('offset', String(params.offset))
  if (params?.limit) q.set('limit', String(params.limit))
  const qs = q.toString()
  const data = await fetchJSON<{ items: Belief[]; total: number }>(`/api/domains/${domainId}/beliefs${qs ? '?' + qs : ''}`)
  return { beliefs: data.items, total: data.total }
}

export async function listIssues(domainId: string): Promise<{
  gated: { blockers: Record<string, { text: string; gated: { id: string; text: string }[] }>; gated_count: number };
  negative: { candidates: { id: string; text: string }[]; candidate_count: number };
}> {
  return fetchJSON(`/api/domains/${domainId}/issues`)
}

export async function getBeliefDetail(domainId: string, nodeId: string): Promise<BeliefDetail> {
  return fetchJSON(`/api/domains/${domainId}/beliefs/${nodeId}`)
}

export async function explainBelief(domainId: string, nodeId: string): Promise<{ explanation: string }> {
  return fetchJSON(`/api/domains/${domainId}/beliefs/${nodeId}/explain`)
}

export async function searchBeliefs(domainId: string, query: string): Promise<{ results: Belief[] }> {
  const data = await fetchJSON<{ beliefs: Belief[] }>(`/api/domains/${domainId}/search?q=${encodeURIComponent(query)}`)
  return { results: data.beliefs }
}

// --- Proposals ---

export async function listProposals(domainId: string, status?: string): Promise<{ proposals: Proposal[] }> {
  const q = status ? `?status=${status}` : ''
  const data = await fetchJSON<{ items: Proposal[] }>(`/api/domains/${domainId}/beliefs/proposed${q}`)
  return { proposals: data.items }
}

export async function createProposal(
  domainId: string,
  body: { node_id: string; text: string; type: string; justification_label?: string; antecedents?: string[] },
): Promise<Proposal> {
  return fetchJSON(`/api/domains/${domainId}/beliefs/propose`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function reviewProposal(
  domainId: string,
  proposalId: string,
  body: { status: string; review_notes?: string },
): Promise<Proposal> {
  return fetchJSON(`/api/domains/${domainId}/beliefs/proposed/${proposalId}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

// --- Sources ---

export async function listSources(domainId: string): Promise<{ sources: SourceEntry[] }> {
  const data = await fetchJSON<{ items: SourceEntry[] }>(`/api/domains/${domainId}/sources`)
  return { sources: data.items }
}

export async function getSource(domainId: string, slug: string): Promise<SourceEntry & { content?: string; description?: string; added_by?: string; license?: string; entry_count?: number }> {
  return fetchJSON(`/api/domains/${domainId}/sources/${slug}`)
}

// --- Entries ---

export async function listEntries(domainId: string): Promise<{ entries: EntryItem[] }> {
  const data = await fetchJSON<{ items: EntryItem[] }>(`/api/domains/${domainId}/entries`)
  return { entries: data.items }
}

export async function getEntry(domainId: string, entryId: string): Promise<EntryItem & { content?: string }> {
  return fetchJSON(`/api/domains/${domainId}/entries/${entryId}`)
}

// --- Summaries ---

export async function listSummaries(domainId: string): Promise<{ summaries: SummaryItem[]; total: number }> {
  const data = await fetchJSON<{ items: SummaryItem[]; total: number }>(`/api/domains/${domainId}/summaries`)
  return { summaries: data.items, total: data.total }
}

export async function getSummary(domainId: string, summaryId: string): Promise<SummaryItem & { content?: string; sources?: { slug: string; url?: string; word_count?: number; title?: string }[] }> {
  return fetchJSON(`/api/domains/${domainId}/summaries/${summaryId}`)
}

// --- Topics ---

export async function listTopics(domainId: string): Promise<{ topics: Topic[] }> {
  const data = await fetchJSON<{ items: Topic[] }>(`/api/domains/${domainId}/topics`)
  return { topics: data.items }
}

// --- Chat ---

export function streamChat(
  body: { domain_id?: string; persona_id?: string; message: string; conversation_id?: string; history?: { role: string; content: string }[] },
): { response: Promise<Response>; abort: () => void } {
  const controller = new AbortController()
  const response = fetch('/api/chat', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: controller.signal,
  })
  return { response, abort: () => controller.abort() }
}

export interface Conversation {
  id: string
  domain_id: string
  persona_id: string | null
  title: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ConversationDetail {
  id: string
  domain_id: string
  title: string | null
  messages: { role: string; content: string; created_at: string | null }[]
}

export async function listConversations(domainId?: string): Promise<Conversation[]> {
  const q = domainId ? `?domain_id=${domainId}` : ''
  const data = await fetchJSON<{ items: Conversation[] }>(`/api/chat/conversations${q}`)
  return data.items
}

export async function getConversation(conversationId: string): Promise<ConversationDetail> {
  return fetchJSON(`/api/chat/conversations/${conversationId}`)
}

export async function deleteConversation(conversationId: string): Promise<void> {
  await fetchJSON(`/api/chat/conversations/${conversationId}`, { method: 'DELETE' })
}

// --- Personas ---

export interface PersonaSummary {
  id: string
  name: string
  description: string
  system_prompt: string | null
  domain_ids: string[]
  domains: { id: string; name: string }[]
}

export async function listPersonas(): Promise<PersonaSummary[]> {
  const data = await fetchJSON<{ items: PersonaSummary[] }>('/api/personas')
  return data.items
}

export async function createPersona(body: { name: string; description?: string; system_prompt?: string; domain_ids?: string[] }): Promise<PersonaSummary> {
  return fetchJSON('/api/personas', { method: 'POST', body: JSON.stringify(body) })
}

export async function updatePersona(id: string, body: { name?: string; description?: string; system_prompt?: string; domain_ids?: string[] }): Promise<PersonaSummary> {
  return fetchJSON(`/api/personas/${id}`, { method: 'PUT', body: JSON.stringify(body) })
}

export async function deletePersona(id: string): Promise<void> {
  await fetchJSON(`/api/personas/${id}`, { method: 'DELETE' })
}

// --- Documents (import) ---

export async function uploadDocuments(domainId: string, files: File[]): Promise<{ imported: number }> {
  const formData = new FormData()
  for (const f of files) formData.append('files', f)
  const resp = await fetch(`/api/domains/${domainId}/import/sources`, {
    method: 'POST',
    credentials: 'same-origin',
    body: formData,
  })
  if (resp.status === 401) {
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`
    throw new Error('Unauthorized')
  }
  if (!resp.ok) throw new Error('Upload failed')
  return resp.json()
}

// --- Overview ---

export async function getDomainOverview(domainId: string): Promise<DomainOverview> {
  const [beliefs, topics, sources, entries] = await Promise.all([
    fetchJSON<{ items: Belief[]; total: number }>(`/api/domains/${domainId}/beliefs?limit=0`).catch(() => ({ items: [], total: 0 })),
    listTopics(domainId).catch(() => ({ topics: [] })),
    listSources(domainId).catch(() => ({ sources: [] })),
    listEntries(domainId).catch(() => ({ entries: [] })),
  ])
  return {
    summary: '',
    topics: topics.topics,
    stats: {
      belief_count: beliefs.total,
      source_count: sources.sources.length,
      entry_count: entries.entries.length,
    },
  }
}
