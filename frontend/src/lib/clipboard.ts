/**
 * Copy `text`, reporting whether it actually happened.
 *
 * The boolean is the whole point. `navigator.clipboard?.writeText(text)` looks like it
 * handles a missing Clipboard API, but optional chaining makes the expression `undefined`
 * rather than throwing, so `await` resolves and a caller's `try` runs its success path having
 * copied nothing. The API is absent in any non-secure context, which includes a deployment
 * served over plain HTTP on a LAN address - and the caller that matters most here shows a
 * secret exactly once, so a success message that lied would cost the user the token.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (!navigator.clipboard) return false
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // Denied by permission or by the document not being focused. The caller says so.
    return false
  }
}
