import { cn } from '@/lib/utils'

type SpinnerSize = 'sm' | 'default' | 'lg'

// Box size + border width per size.
const SIZES: Record<SpinnerSize, string> = {
  sm: 'size-4 border-2',
  default: 'size-6 border-2',
  lg: 'size-9 border-[3px]',
}

// A brand loading spinner: a faint ring with a solid head that spins, coloured
// from the active accent (--primary) so it matches the theme. Reusable anywhere
// a loading indicator is needed. Pass `label` for screen-reader-only text
// (the visual ring is decorative / aria-hidden).
function Spinner({
  className,
  size = 'default',
  label,
}: {
  className?: string
  size?: SpinnerSize
  label?: string
}) {
  return (
    <span role="status" className={cn('inline-flex items-center justify-center', className)}>
      <span
        aria-hidden
        className={cn('animate-spin rounded-full border-primary/25 border-t-primary', SIZES[size])}
      />
      {label ? <span className="sr-only">{label}</span> : null}
    </span>
  )
}

export { Spinner }
