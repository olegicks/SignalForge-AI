import type { MouseEvent } from 'react'
import { useNavigate } from 'react-router-dom'

/**
 * Makes a whole table row open a page on click. The ticker cell keeps a real <Link>, so
 * keyboard and screen-reader users still have a focusable link.
 */
export function useRowLink() {
  const navigate = useNavigate()

  return (to: string) => ({
    className: 'row-link',
    onClick: (event: MouseEvent<HTMLTableRowElement>) => {
      // Real links and buttons inside the row handle their own clicks.
      if ((event.target as HTMLElement).closest('a, button')) return
      // Don't hijack a text selection (e.g. copying the reasoning).
      if (window.getSelection()?.toString()) return
      if (event.ctrlKey || event.metaKey) {
        window.open(to, '_blank', 'noopener')
        return
      }
      navigate(to)
    },
  })
}
