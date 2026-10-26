import type {
  UserInfo, Domain, Belief, BeliefDetail, Proposal,
  ChatMessage, EntryItem, SourceEntry, Topic, DomainOverview,
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
    headers: { ...headers(!!init?.body), ...init?.headers },
  })
  if (resp.status === 401) {
    window.location.href = '/login'
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
  params?: { search?: string; truth_value?: string; sort?: string; offset?: number; limit?: number },
): Promise<{ beliefs: Belief[]; total: number }> {
  const q = new URLSearchParams()
  if (params?.search) q.set('search', params.search)
  if (params?.truth_value) q.set('truth_value', params.truth_value)
  if (params?.sort) q.set('sort', params.sort)
  if (params?.offset) q.set('offset', String(params.offset))
  if (params?.limit) q.set('limit', String(params.limit))
  const qs = q.toString()
  const data = await fetchJSON<{ items: Belief[]; total: number }>(`/api/domains/${domainId}/beliefs${qs ? '?' + qs : ''}`)
  return { beliefs: data.items, total: data.total }
}

export async function getBeliefDetail(domainId: string, nodeId: string): Promise<BeliefDetail> {
  return fetchJSON(`/api/domains/${domainId}/beliefs/${nodeId}`)
}

export async function explainBelief(domainId: string, nodeId: string): Promise<{ explanation: string }> {
  return fetchJSON(`/api/domains/${domainId}/beliefs/${nodeId}/explain`)
}

export async function searchBeliefs(domainId: string, query: string): Promise<{ results: Belief[] }> {
  const data = await fetchJSON<{ items: Belief[] }>(`/api/domains/${domainId}/search?q=${encodeURIComponent(query)}`)
  return { results: data.items }
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

export async function getSource(domainId: string, slug: string): Promise<{ content: string; frontmatter?: Record<string, unknown> }> {
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

// --- Topics ---

export async function listTopics(domainId: string): Promise<{ topics: Topic[] }> {
  const data = await fetchJSON<{ items: Topic[] }>(`/api/domains/${domainId}/topics`)
  return { topics: data.items }
}

// --- Chat ---

export function streamChat(
  body: { domain_id: string; message: string; history?: { role: string; content: string }[] },
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
    window.location.href = '/login'
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
