import assert from 'node:assert/strict'
import { test } from 'node:test'
import { localCommands, workLocallyShown } from '../src/workLocally.ts'

test('the commands fetch ws.py from this server, pull the exercise into its own folder, watch it there and submit it', () => {
  assert.deepEqual(localCommands('http://tutor.lan:8321', 42), {
    setup: 'curl -o ws.py http://tutor.lan:8321/api/ws.py\npython3 ws.py --server http://tutor.lan:8321 pull 42\npython3 ws.py watch exercise-42',
    submit: 'python3 ws.py submit exercise-42',
  })
})

test('the panel shows only for an open exercise whose files are still there, on a server that runs commands', () => {
  assert.equal(workLocallyShown(true, false, true), true)
  assert.equal(workLocallyShown(true, false, false), false)
  assert.equal(workLocallyShown(false, false, true), false)
  assert.equal(workLocallyShown(true, true, true), false)
})
