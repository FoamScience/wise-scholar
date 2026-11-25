/** The terminal lines that fetch the ws script from this server, pull an exercise into a folder of its own and keep
 * it in step, and the one that submits it. */
export function localCommands(server: string, exerciseId: number): { setup: string; submit: string } {
  const folder = `exercise-${exerciseId}`
  return {
    setup: [`curl -o ws.py ${server}/api/ws.py`, `python3 ws.py --server ${server} pull ${exerciseId}`, `python3 ws.py watch ${folder}`].join('\n'),
    submit: `python3 ws.py submit ${folder}`,
  }
}

/** The panel shows while the exercise takes edits and the server runs commands: without Run, submit cannot run it. */
export function workLocallyShown(open: boolean, kept: boolean, commands: boolean): boolean {
  return open && !kept && commands
}
