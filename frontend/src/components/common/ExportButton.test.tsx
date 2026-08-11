/**
 * The export button (FS-652).
 *
 * 160 lines, stubbed out of every page test that mounts it —
 * `vi.mock('../components/common', () => ({ ExportButton: () => null }))` in both
 * `OEE.test.tsx` and `AssetDetail.test.tsx` — so until now nothing had ever rendered it.
 * It reported as covered because a stub is indistinguishable from a component nobody
 * exercised.
 *
 * WHAT IS WORTH PINNING HERE. Not the markup. This component has three paths that fail in
 * ways a user cannot see:
 *
 *   1. A **202 + job descriptor** for large pulls, which polls and then downloads. If the
 *      poll silently gives up, the user is left looking at a button that stopped spinning
 *      and no file.
 *   2. An error body that arrives as a **Blob**, because the request sets
 *      `responseType: 'blob'` — so the server's `detail` is inside a blob, not on
 *      `err.response.data.detail`, and reading it the ordinary way yields "[object Blob]".
 *   3. `onError` being **optional**. When a caller passes none, the failure goes to
 *      `console.error` and the screen says nothing at all.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
vi.mock('../../api/client', () => ({ api: { get: (...a: unknown[]) => get(...a) } }))

import { ExportButton } from './ExportButton'

// A Blob with a working `text()`. jsdom's implementation does not resolve one here, and
// `blobToJson` is `JSON.parse(await blob.text())` — so without this the component's blob
// branch throws, the catch keeps its default message, and every assertion below would be
// passing on the environment rather than on the code.
const blob = (body: unknown): Blob => {
  const json = JSON.stringify(body)
  const b = new Blob([json], { type: 'application/json' })
  Object.defineProperty(b, 'text', { value: async () => json })
  return b
}

beforeEach(() => {
  vi.clearAllMocks()
  // jsdom implements neither of these; without them the download path throws before the
  // assertions and every test here would pass for the wrong reason.
  URL.createObjectURL = vi.fn(() => 'blob:stub')
  URL.revokeObjectURL = vi.fn()
})

describe('ExportButton', () => {
  it('downloads the file the server returns', async () => {
    get.mockResolvedValue({
      status: 200,
      data: new Blob(['id,name\n1,a\n']),
      headers: { 'content-disposition': 'attachment; filename="assets.csv"' },
    })
    render(<ExportButton endpoint="/api/v1/exports/assets" />)
    fireEvent.click(screen.getByRole('button', { name: /export/i }))
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled())
  })

  it('takes the filename from the server, not the fallback', async () => {
    // The fallback exists for servers that omit the header. Preferring it would rename
    // every export to `export.csv` and quietly lose the server's own labelling.
    get.mockResolvedValue({
      status: 200,
      data: new Blob(['x']),
      headers: { 'content-disposition': 'attachment; filename="2026-08-oee.xlsx"' },
    })
    const created: string[] = []
    const realCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = realCreate(tag)
      if (tag === 'a') Object.defineProperty(el, 'download', {
        set: (v: string) => created.push(v), get: () => created[created.length - 1],
      })
      return el as HTMLElement
    })
    render(<ExportButton endpoint="/e" filename="fallback.csv" />)
    fireEvent.click(screen.getByRole('button', { name: /export/i }))
    await waitFor(() => expect(created).toContain('2026-08-oee.xlsx'))
    vi.mocked(document.createElement).mockRestore()
  })

  it('reports the server reason when the error body is a Blob', async () => {
    // THE ONE THAT MATTERS. `responseType: 'blob'` means an error body is a Blob too, so
    // `err.response.data.detail` is undefined and a naive handler shows "Export failed"
    // for every cause — including "you are not allowed to export this".
    get.mockRejectedValue({ response: { data: blob({ detail: 'Export is admin-only' }) } })
    const onError = vi.fn()
    render(<ExportButton endpoint="/e" onError={onError} />)
    fireEvent.click(screen.getByRole('button', { name: /export/i }))
    await waitFor(() => expect(onError).toHaveBeenCalledWith('Export is admin-only'))
  })

  it('falls back to a message rather than rendering [object Blob]', async () => {
    const unreadable = new Blob(['not json'])
    Object.defineProperty(unreadable, 'text', { value: async () => 'not json' })
    get.mockRejectedValue({ response: { data: unreadable }, message: 'Network Error' })
    const onError = vi.fn()
    render(<ExportButton endpoint="/e" onError={onError} />)
    fireEvent.click(screen.getByRole('button', { name: /export/i }))
    await waitFor(() => expect(onError).toHaveBeenCalled())
    expect(onError.mock.calls[0][0]).not.toMatch(/object Blob/)
  })

  it('polls a 202 job to completion and then downloads', async () => {
    get
      .mockResolvedValueOnce({ status: 202, data: blob({ job_id: 'job-1' }), headers: {} })
      .mockResolvedValueOnce({ data: { status: 'completed', filename: 'big.csv', processed: 9, total: 9 } })
      .mockResolvedValueOnce({ data: new Blob(['big']), headers: {} })
    render(<ExportButton endpoint="/e" />)
    fireEvent.click(screen.getByRole('button', { name: /export/i }))
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled())
    expect(get).toHaveBeenCalledWith('/api/v1/exports/jobs/job-1')
  })

  it('surfaces a job that FAILED rather than ending quietly', async () => {
    // A failed job answers 200 with status:"failed" — so nothing throws, and without this
    // branch the button simply stops spinning and the user waits for a file forever.
    get
      .mockResolvedValueOnce({ status: 202, data: blob({ job_id: 'job-2' }), headers: {} })
      .mockResolvedValueOnce({ data: { status: 'failed', errors: [{ error: 'row 41 is malformed' }] } })
    const onError = vi.fn()
    render(<ExportButton endpoint="/e" onError={onError} />)
    fireEvent.click(screen.getByRole('button', { name: /export/i }))
    await waitFor(() => expect(onError).toHaveBeenCalledWith('row 41 is malformed'))
  })

  it('re-enables itself after a failure', async () => {
    // Without the `finally`, one failed export disables the button for the life of the
    // page and the only recovery a user has is a reload.
    get.mockRejectedValue(new Error('nope'))
    render(<ExportButton endpoint="/e" onError={vi.fn()} />)
    const button = screen.getByRole('button', { name: /export/i })
    fireEvent.click(button)
    await waitFor(() => expect(button).not.toBeDisabled())
  })
})
