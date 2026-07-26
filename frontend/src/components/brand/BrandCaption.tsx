import { cn } from '@/lib/utils'
import { CAPTION_D, CAPTION_VIEWBOX } from './paths'

/**
 * "Do task!" in the original handwriting, the tagline half of the Login lockup.
 *
 * Login only, deliberately: the sidebar header is too narrow to give this the width
 * it needs, and it was taken back out of there for that reason.
 *
 * Sized by WIDTH, not height: the phrase is nearly 2:1, so driving it from a height
 * that matches the neighbouring type leaves it about 20px wide and illegible.
 *
 * Decorative — it is artwork, and the link that carries it is already labelled — so
 * it stays out of the accessibility tree. It is also never translated, for the same
 * reason the brand name is not: it is a drawing, not a string.
 */
export default function BrandCaption({ className }: { className?: string }) {
  return (
    <svg
      viewBox={CAPTION_VIEWBOX}
      className={cn('h-auto w-20 fill-primary', className)}
      aria-hidden="true"
    >
      <path d={CAPTION_D} />
    </svg>
  )
}
