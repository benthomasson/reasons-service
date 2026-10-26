export interface UserInfo {
  identity: string
  role: string
  display_name: string | null
  tenants: TenantMembership[]
}

export interface TenantMembership {
  tenantId: string
  tenantName: string
  role: string
}

export interface Tenant {
  id: string
  name: string
  type: string
  created_at: string
}

export interface TenantMember {
  email: string
  role: string
  created_at: string
}

export interface Domain {
  id: string
  name: string
  description: string
  tenant_id?: string
  config?: Record<string, unknown>
  public?: boolean
  members_only?: boolean
  allowed_tags?: string[]
  created_at: string
  source_count?: number
  entry_count?: number
  belief_count?: number
}

export interface DomainCounts {
  source_count?: number
  entry_count?: number
  summary_count?: number
  belief_count?: number
}

export interface Belief {
  id: string
  text: string
  truth_value: string
  type?: string
  depth?: number
  source?: string
  justification_count?: number
  is_premise?: boolean
  metadata?: Record<string, unknown>
}

export interface BeliefDetail extends Belief {
  justifications: Justification[]
  dependents: { id: string; text: string; truth_value: string }[]
}

export interface Justification {
  type: string
  label: string
  antecedents: { id: string; text: string; truth_value: string }[]
  outlist: { id: string; text: string; truth_value: string }[]
}

export interface Proposal {
  id: string
  node_id: string
  text: string
  type: string
  justification_label?: string
  antecedents?: string[]
  status: string
  proposed_by: string
  created_at: string
  reviewed_by?: string
  reviewed_at?: string
  review_notes?: string
}

export interface Story {
  id: string
  domain_id: string
  title: string
  body: string
  algorithm: string
  beliefs?: { id: string; text: string; truth_value: string }[]
  image_path?: string
  created_at: string
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  beliefs_used?: { id: string; text: string; truth_value: string }[]
  created_at?: string
}

export interface Note {
  id: string
  domain_id: string
  content: string
  status: string
  created_by: string
  created_at: string
  updated_at: string
}

export interface TaskItem {
  id: string
  type: string
  domain_id: string
  tenant_id: string
  status: string
  message?: string
  error?: string
  progress?: number
  created_at: string
  updated_at: string
  claimed_by?: string
}

export interface SourceEntry {
  id?: string
  slug: string
  url?: string
  title?: string
  word_count?: number
  author?: string
  content_type?: string
  fetched_at?: string
}

export interface SummaryItem {
  id: string
  topic: string
  title?: string
  created_at?: string
  source_slugs?: string[]
}

export interface EntryItem {
  id: string
  topic: string
  title: string
  created_at: string
}

export interface NotificationItem {
  id: string
  title: string
  body: string
  type: string
  read: boolean
  created_at: string
  domain_id?: string
  metadata?: Record<string, unknown>
}

export interface Topic {
  id: string
  name: string
  description: string
  belief_count: number
}

export interface DomainOverview {
  summary: string
  topics: Topic[]
  stats: DomainCounts
}
