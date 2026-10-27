import {
  PageSection,
  Title,
  Card, CardTitle, CardBody,
  ClipboardCopy,
  DescriptionList, DescriptionListGroup, DescriptionListTerm, DescriptionListDescription,
  Label, Flex, FlexItem,
  Content,
} from '@patternfly/react-core'
import { useTenant } from '../TenantContext'

export default function ConnectPage() {
  const { domainId, domains } = useTenant()
  const domain = domains.find(d => d.id === domainId)
  const baseUrl = window.location.origin

  const mcpUrl = `${baseUrl}/mcp`

  const tools = [
    { name: 'search', scope: 'read', desc: 'Full-text search over beliefs and source documents' },
    { name: 'deep_search', scope: 'read', desc: 'IDF-ranked search with source chunk context' },
    { name: 'explain_belief', scope: 'read', desc: 'Show full justification chain for a belief' },
    { name: 'get_belief', scope: 'read', desc: 'Get details of a specific belief by ID' },
    { name: 'what_if', scope: 'read', desc: 'Simulate retracting or asserting a belief' },
    { name: 'find_issues', scope: 'read', desc: 'Find gated beliefs and negative candidates' },
    { name: 'list_beliefs', scope: 'read', desc: 'List beliefs with optional status filter' },
    { name: 'list_topics', scope: 'read', desc: 'List topics ranked by frequency' },
    { name: 'list_domains', scope: 'read', desc: 'List available domains' },
    { name: 'list_sources', scope: 'read', desc: 'List source documents' },
    { name: 'get_source', scope: 'read', desc: 'Get full content of a source document' },
    { name: 'list_entries', scope: 'read', desc: 'List entries with optional topic filter' },
    { name: 'get_entry', scope: 'read', desc: 'Get full content of an entry' },
    { name: 'list_summaries', scope: 'read', desc: 'List summaries with optional topic filter' },
    { name: 'get_summary', scope: 'read', desc: 'Get full content of a summary' },
    { name: 'propose_belief', scope: 'propose', desc: 'Propose a new belief for review' },
    { name: 'propose_retraction', scope: 'propose', desc: 'Propose retracting an existing belief' },
    { name: 'list_proposals', scope: 'review', desc: 'List proposals with status filter' },
    { name: 'get_proposal', scope: 'review', desc: 'Get details of a proposal' },
    { name: 'accept_proposal', scope: 'review', desc: 'Accept a pending proposal' },
    { name: 'reject_proposal', scope: 'review', desc: 'Reject a pending proposal' },
    { name: 'withdraw_proposal', scope: 'propose', desc: 'Withdraw your own proposal' },
  ]

  const scopeColor = (scope: string) => {
    if (scope === 'read') return 'blue'
    if (scope === 'propose') return 'green'
    return 'orange'
  }

  return (
    <PageSection hasOverflowScroll style={{ height: '100%' }}>
      <Flex direction={{ default: 'column' }} gap={{ default: 'gapLg' }} style={{ maxWidth: 900 }}>

        <FlexItem>
          <Title headingLevel="h1" size="xl">Connect to MCP</Title>
          <Content component="p" style={{ marginTop: '0.5rem' }}>
            Connect AI agents to this Reasons Service instance via the Model Context Protocol (MCP).
            Agents can search beliefs, read sources, propose changes, and review proposals.
          </Content>
        </FlexItem>

        <FlexItem>
          <Card>
            <CardTitle>MCP Endpoint</CardTitle>
            <CardBody>
              <ClipboardCopy isReadOnly>{mcpUrl}</ClipboardCopy>
              <Content component="p" style={{ marginTop: '0.5rem', fontSize: '0.85rem', color: 'var(--pf-t--global--color--200)' }}>
                Streamable HTTP transport. Supports OAuth 2.0 with dynamic client registration when Google OAuth is configured.
              </Content>
            </CardBody>
          </Card>
        </FlexItem>

        <FlexItem>
          <Card>
            <CardTitle>Claude Code</CardTitle>
            <CardBody>
              <DescriptionList isHorizontal>
                <DescriptionListGroup>
                  <DescriptionListTerm>Add server</DescriptionListTerm>
                  <DescriptionListDescription>
                    <ClipboardCopy isReadOnly>
                      {`claude mcp add reasons --transport http ${mcpUrl}`}
                    </ClipboardCopy>
                  </DescriptionListDescription>
                </DescriptionListGroup>
                <DescriptionListGroup>
                  <DescriptionListTerm>With API key</DescriptionListTerm>
                  <DescriptionListDescription>
                    <ClipboardCopy isReadOnly>
                      {`claude mcp add reasons --transport http ${mcpUrl} --header "Authorization: Bearer YOUR_API_KEY"`}
                    </ClipboardCopy>
                  </DescriptionListDescription>
                </DescriptionListGroup>
              </DescriptionList>
            </CardBody>
          </Card>
        </FlexItem>

        <FlexItem>
          <Card>
            <CardTitle>Claude Desktop</CardTitle>
            <CardBody>
              <Content component="p" style={{ marginBottom: '0.75rem' }}>
                Add to your <code>claude_desktop_config.json</code>:
              </Content>
              <ClipboardCopy isCode isReadOnly variant="expansion">
{JSON.stringify({
  mcpServers: {
    reasons: {
      transport: "streamable-http",
      url: mcpUrl,
    }
  }
}, null, 2)}
              </ClipboardCopy>
            </CardBody>
          </Card>
        </FlexItem>

        <FlexItem>
          <Card>
            <CardTitle>VS Code (Copilot / Continue)</CardTitle>
            <CardBody>
              <Content component="p" style={{ marginBottom: '0.75rem' }}>
                Add to <code>.vscode/mcp.json</code> in your project:
              </Content>
              <ClipboardCopy isCode isReadOnly variant="expansion">
{JSON.stringify({
  servers: {
    reasons: {
      type: "http",
      url: mcpUrl,
    }
  }
}, null, 2)}
              </ClipboardCopy>
            </CardBody>
          </Card>
        </FlexItem>

        <FlexItem>
          <Card>
            <CardTitle>Python (MCP SDK)</CardTitle>
            <CardBody>
              <ClipboardCopy isCode isReadOnly variant="expansion">
{`from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client("${mcpUrl}") as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("search", {
            "query": "your question",
            "domain": "${domain?.name || 'your-domain'}"
        })`}
              </ClipboardCopy>
            </CardBody>
          </Card>
        </FlexItem>

        <FlexItem>
          <Card>
            <CardTitle>cURL</CardTitle>
            <CardBody>
              <Content component="p" style={{ marginBottom: '0.75rem' }}>
                Test the endpoint directly with an API key:
              </Content>
              <ClipboardCopy isCode isReadOnly variant="expansion">
{`curl -X POST ${mcpUrl} \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'`}
              </ClipboardCopy>
            </CardBody>
          </Card>
        </FlexItem>

        <FlexItem>
          <Card>
            <CardTitle>Available Tools ({tools.length})</CardTitle>
            <CardBody>
              <DescriptionList isCompact>
                {tools.map(t => (
                  <DescriptionListGroup key={t.name}>
                    <DescriptionListTerm>
                      <Flex gap={{ default: 'gapSm' }} alignItems={{ default: 'alignItemsCenter' }}>
                        <FlexItem><code>{t.name}</code></FlexItem>
                        <FlexItem><Label color={scopeColor(t.scope)} isCompact>{t.scope}</Label></FlexItem>
                      </Flex>
                    </DescriptionListTerm>
                    <DescriptionListDescription>{t.desc}</DescriptionListDescription>
                  </DescriptionListGroup>
                ))}
              </DescriptionList>
            </CardBody>
          </Card>
        </FlexItem>

        <FlexItem>
          <Card>
            <CardTitle>OAuth Scopes</CardTitle>
            <CardBody>
              <DescriptionList isHorizontal isCompact>
                <DescriptionListGroup>
                  <DescriptionListTerm><Label color="blue">reasons:read</Label></DescriptionListTerm>
                  <DescriptionListDescription>Search, list, and read beliefs, sources, entries, summaries, and topics</DescriptionListDescription>
                </DescriptionListGroup>
                <DescriptionListGroup>
                  <DescriptionListTerm><Label color="green">reasons:propose</Label></DescriptionListTerm>
                  <DescriptionListDescription>Propose new beliefs or retractions, withdraw your own proposals</DescriptionListDescription>
                </DescriptionListGroup>
                <DescriptionListGroup>
                  <DescriptionListTerm><Label color="orange">reasons:review</Label></DescriptionListTerm>
                  <DescriptionListDescription>List, accept, and reject proposals</DescriptionListDescription>
                </DescriptionListGroup>
              </DescriptionList>
            </CardBody>
          </Card>
        </FlexItem>

      </Flex>
    </PageSection>
  )
}
