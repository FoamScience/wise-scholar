import assert from 'node:assert/strict'
import { test } from 'node:test'
import { starterOf, type ExerciseData } from '../src/course.ts'
import { Compartment, EditorState } from '@codemirror/state'
import type { TransactionSpec } from '@codemirror/state'
import { getChunks, unifiedMergeView } from '@codemirror/merge'
import { diffSwitch } from '../src/editor.ts'
import { LEGEND, diffSummary, openDiff } from '../src/editorSync.ts'
import en from '../src/locales/en.json' with { type: 'json' }

const exercise = (data: object) => ({ files: ['a.py', 'b.py'], run: '', last_run: null, ...data }) as unknown as ExerciseData

test('a file is compared with the starter code it was posed with, also an empty one', () => {
  const d = exercise({ starter: { 'a.py': 'a = 1\n', 'b.py': '' } })
  assert.equal(starterOf(d, 'a.py'), 'a = 1\n')
  assert.equal(starterOf(d, 'b.py'), '')
})

test('an exercise without recorded starters, or a file without one, is compared with nothing', () => {
  assert.equal(starterOf(exercise({}), 'a.py'), null)
  assert.equal(starterOf(exercise({ starter: { 'a.py': 'a = 1\n' } }), 'b.py'), null)
  assert.equal(starterOf(exercise({ starter: {} }), 'constructor'), null)
})

/** An editor's state with the dispatches it gets counted, as an EditorView would apply them. */
function editorOf(doc: string) {
  const diff = new Compartment()
  const view = {
    state: EditorState.create({ doc, extensions: [diff.of([])] }),
    dispatched: 0,
    dispatch(spec: TransactionSpec) {
      this.dispatched++
      this.state = this.state.update(spec).state
    },
    type(text: string) {
      this.dispatch({ changes: { from: this.state.doc.length, insert: text } })
    },
  }
  const told: string[] = []
  let loads = 0
  let failing = false
  const merge = diffSwitch(view, diff, (s) => told.push(s), async () => {
    loads++
    if (failing) throw new Error('chunk failed')
    return { unifiedMergeView, getChunks }
  })
  return { view, merge, told, loads: () => loads, fail: (on: boolean) => (failing = on) }
}

test('a diff turned on marks the changes and is told what it holds; turned off, the editor has none', async () => {
  const e = editorOf('a = 2\nprint(a)\n')
  await e.merge.set('a = 1\nprint(a)\n')
  assert.equal(getChunks(e.view.state)?.chunks.length, 1)
  assert.deepEqual(e.told, ['both'])
  await e.merge.set(null)
  assert.equal(getChunks(e.view.state), null)
  assert.equal(e.view.state.doc.toString(), 'a = 2\nprint(a)\n')
})

test('the summary follows typing, and is told only when it changes', async () => {
  const e = editorOf('x\n')
  await e.merge.set('x\n')
  e.view.type('y\n')
  e.merge.changed()
  e.view.type('z\n')
  e.merge.changed()
  assert.deepEqual(e.told, ['same', 'added'])
})

test('nothing is dispatched for a diff that is already as asked, nor on mount with none', async () => {
  const e = editorOf('x\n')
  await e.merge.set(null)
  assert.equal(e.view.dispatched, 0)
  await e.merge.set('y\n')
  const after = e.view.dispatched
  await e.merge.set('y\n')
  assert.equal(e.view.dispatched, after)
  assert.equal(e.loads(), 1)
})

test('a failed load rejects, leaves no diff, and the next turn on loads again', async () => {
  const e = editorOf('x\n')
  e.fail(true)
  await assert.rejects(e.merge.set('y\n'))
  assert.equal(getChunks(e.view.state), null)
  e.fail(false)
  await e.merge.set('y\n')
  assert.equal(getChunks(e.view.state)?.chunks.length, 1)
  assert.equal(e.loads(), 2)
})

test('a diff that finishes loading after its editor is gone, or after it was turned off, dispatches nothing', async () => {
  const e = editorOf('x\n')
  const late = e.merge.set('y\n')
  e.merge.stop()
  await late
  const f = editorOf('x\n')
  const off = f.merge.set('y\n')
  await f.merge.set(null)
  await off
  assert.equal(e.view.dispatched + f.view.dispatched, 0)
})

test('the legend names only the marks the diff shows', () => {
  assert.equal(diffSummary([]), 'same')
  assert.equal(diffSummary([{ fromA: 3, toA: 3, fromB: 3, toB: 8 }]), 'added')
  assert.equal(diffSummary([{ fromA: 3, toA: 8, fromB: 3, toB: 3 }]), 'removed')
  assert.equal(diffSummary([{ fromA: 0, toA: 2, fromB: 0, toB: 0 }, { fromA: 5, toA: 5, fromB: 3, toB: 6 }]), 'both')
  const words = (key: string) => (en.translation.exercise as Record<string, string>)[key.split('.')[1]]
  assert.doesNotMatch(words(LEGEND.added), /struck/i)
  assert.doesNotMatch(words(LEGEND.removed), /edge/i)
  assert.match(words(LEGEND.both), /Struck.*edge/)
})

test('two quick toggles share one load, and a load that fails after the diff was turned off reports nothing', async () => {
  const e = editorOf('x\n')
  const first = e.merge.set('y\n')
  await e.merge.set(null)
  await Promise.all([first, e.merge.set('y\n')])
  assert.equal(e.loads(), 1)
  const f = editorOf('x\n')
  f.fail(true)
  const late = f.merge.set('y\n')
  await f.merge.set(null)
  await late
  assert.equal(getChunks(f.view.state), null)
})

/** openDiff with an editor module that loads, or not, and an editor whose diff loads, or not. */
function diffOf(module: 'loads' | 'fails', diff: 'loads' | 'fails' = 'loads') {
  const heard: string[] = []
  const editor = {
    setDiff: async () => {
      heard.push('setDiff')
      if (diff === 'fails') throw new Error('merge chunk failed')
    },
    destroy: () => heard.push('destroy'),
  }
  const load = async () => {
    if (module === 'fails') throw new Error('editor chunk failed')
    return { createEditor: () => (heard.push('created'), editor) }
  }
  const close = openDiff({} as HTMLElement, { path: 'a.py', from: 'a\n', to: 'b\n' }, load, {
    loaded: () => heard.push('loaded'),
    diff: (s) => heard.push(s),
    failed: () => heard.push('failed'),
  })
  return { heard, close, settle: () => new Promise((r) => setTimeout(r)) }
}

test('a read-only diff whose editor cannot load reports it once and never claims to be up', async () => {
  const d = diffOf('fails')
  await d.settle()
  assert.deepEqual(d.heard, ['failed'])
})

test('a read-only diff whose merge code cannot load reports it after the editor is up', async () => {
  const d = diffOf('loads', 'fails')
  await d.settle()
  assert.deepEqual(d.heard, ['created', 'loaded', 'setDiff', 'failed'])
  d.close()
  assert.equal(d.heard.at(-1), 'destroy')
})

test('a read-only diff closed before its load ends reports nothing and creates no editor', async () => {
  for (const module of ['fails', 'loads'] as const) {
    const d = diffOf(module)
    d.close()
    await d.settle()
    assert.deepEqual(d.heard, [])
  }
})
