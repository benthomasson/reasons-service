import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'

function linkifyBeliefRefs(text: string): string {
  return text.replace(/\[([a-zA-Z0-9_:./-]{4,})\](?!\()/g, (_match, id) => {
    return `[\`${id}\`](belief://${id})`
  })
}

function isWikitext(text: string): boolean {
  let indicators = 0
  if (/^={2,5}[^=].*[^=]={2,5}$/m.test(text)) indicators++
  if (/'{3,}/.test(text)) indicators++
  if (/\[\[.*\]\]/.test(text)) indicators++
  if (/^\*[^*]/m.test(text) && !/^[-*] /m.test(text)) indicators++
  return indicators >= 2
}

function wikiToMarkdown(text: string): string {
  let result = text
  result = result.replace(/^(={2,5})\s*(.+?)\s*\1$/gm, (_m, eq, title) => {
    const level = eq.length
    return '#'.repeat(level) + ' ' + title
  })
  result = result.replace(/'{3}(.+?)'{3}/g, '**$1**')
  result = result.replace(/'{2}(.+?)'{2}/g, '*$1*')
  result = result.replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, '[$2]($1)')
  result = result.replace(/\[\[([^\]]+)\]\]/g, '$1')
  return result
}

interface MarkdownProps {
  content: string
  wikitext?: boolean
}

export default function Markdown({ content, wikitext }: MarkdownProps) {
  let processed = content
  if (wikitext && isWikitext(content)) {
    processed = wikiToMarkdown(content)
  }
  processed = linkifyBeliefRefs(processed)

  return (
    <ReactMarkdown
      remarkPlugins={[remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={{
        a: ({ href, children, ...props }) => {
          if (href?.startsWith('belief://')) {
            const beliefId = href.replace('belief://', '')
            return (
              <a href={href} onClick={(e) => {
                e.preventDefault()
                window.dispatchEvent(new CustomEvent('navigate-belief', { detail: beliefId }))
              }} {...props}>
                {children}
              </a>
            )
          }
          return <a href={href} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>
        },
      }}
    >
      {processed}
    </ReactMarkdown>
  )
}
