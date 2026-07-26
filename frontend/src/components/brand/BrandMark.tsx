import { cn } from '@/lib/utils'
import { HEAD_D, MARK_VIEWBOX } from './paths'

/**
 * The brand mark: the cat's head knocked out of a rounded tile.
 *
 * The tile is a DOM element rather than an SVG `<rect>` so it keeps `shadow-logo`
 * and the brand radius, and so `bg-primary` tracks the accent the user picked.
 *
 * The SVG then fills that tile edge to edge, and `MARK_VIEWBOX` does the framing:
 * it crops to the ears so the face fills the tile rather than floating in the
 * middle of it, and the outer whiskers bleed off the sides. `public/favicon.svg`
 * uses the same viewBox, with Latte/Mocha teal baked in since a browser tab cannot
 * read the app theme.
 */
export default function BrandMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'grid size-8 shrink-0 place-items-center overflow-hidden rounded-lg bg-primary shadow-logo',
        className,
      )}
    >
      <svg viewBox={MARK_VIEWBOX} className="size-full fill-primary-foreground" aria-hidden="true">
        <path d={HEAD_D} />
      </svg>
    </span>
  )
}
