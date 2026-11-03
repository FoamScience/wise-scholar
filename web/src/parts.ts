// A term in the lesson text (`[left ventricle](#part-ventricle)`) and the figure part it names
// (`data-part="ventricle"`) light up together: pointing at either marks both, and the figure dims its other parts.
const SCOPE = '.lesson, .book-chapter'
const LINKED = '[data-ref], [data-part]'

function lit(scope: ParentNode, id: string, on: boolean) {
  for (const part of scope.querySelectorAll<Element>('[data-part]')) {
    if (part.getAttribute('data-part') !== id) continue
    part.classList.toggle('part-on', on)
    part.closest('.figure-box')?.classList.toggle('parts-focus', on)
  }
  for (const term of scope.querySelectorAll<Element>('[data-ref]')) {
    if (term.getAttribute('data-ref') === id) term.classList.toggle('term-on', on)
  }
}

function target(e: Event): { scope: ParentNode; id: string } | null {
  const el = (e.target as Element | null)?.closest?.(LINKED)
  const id = el?.getAttribute('data-ref') ?? el?.getAttribute('data-part')
  if (!el || !id) return null
  return { scope: el.closest(SCOPE) ?? document, id }
}

/** Listens once for the whole page, so figures and text rendered later link without wiring of their own. */
export function linkParts() {
  const show = (e: Event) => {
    const t = target(e)
    if (t) lit(t.scope, t.id, true)
  }
  const hide = (e: Event) => {
    const t = target(e)
    const el = (e.target as Element | null)?.closest?.(LINKED)
    // The pointer leaving a term the keyboard is on leaves it lit, and so does focus leaving one under the pointer.
    const held = e.type === 'pointerout' ? el?.contains(document.activeElement) : el?.matches(':hover')
    if (t && !held) lit(t.scope, t.id, false)
  }
  document.addEventListener('pointerover', show)
  document.addEventListener('pointerout', hide)
  document.addEventListener('focusin', show)
  document.addEventListener('focusout', hide)
}
