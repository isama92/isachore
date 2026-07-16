// Up to two uppercase letters from a name, used as the avatar fallback when a
// user has no picture. "Ada Lovelace" -> "AL", "Ada" -> "AD", "" -> "?".
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}
