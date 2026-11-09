export type State = 'held' | 'fading' | 'shaky' | 'unseen'

export const STATE_COLOR: Record<State, string> = { held: '--teal', fading: '--amber-line', shaky: '--danger', unseen: '--mastery-off' }

let registered = false

/** cytoscape with the fcose layout, loaded on first use. */
export function loadCytoscape() {
  return Promise.all([import('cytoscape'), import('cytoscape-fcose')]).then(([{ default: cytoscape }, { default: fcose }]) => {
    if (!registered) {
      cytoscape.use(fcose)
      registered = true
    }
    return cytoscape
  })
}

export function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}
