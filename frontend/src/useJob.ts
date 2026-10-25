// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useRef, useState } from 'react'
import type { JobInfo } from './api'

/** Follow a background job over SSE; calls onDone on any terminal state.
 *  `log` keeps the stream of progress messages (newest first) so pages can
 *  show a live activity feed; it survives job completion until the next
 *  watch() so the user can still read what happened. */
export function useJobWatcher(onDone: () => void) {
  const eventSourceRef = useRef<EventSource | null>(null)
  const [state, setState] = useState('')
  const [error, setError] = useState('')
  const [log, setLog] = useState<string[]>([])
  useEffect(() => () => eventSourceRef.current?.close(), [])

  const watch = (jobId: number) => {
    setError('')
    setState('Starting…')
    setLog([])
    const es = new EventSource(`/api/jobs/${jobId}/stream`, { withCredentials: true })
    eventSourceRef.current = es
    es.onmessage = (event) => {
      const job = JSON.parse(event.data) as JobInfo
      if (job.status === 'running' || job.status === 'queued') {
        setState(job.total > 1 ? `${job.message} (${job.progress}/${job.total})`
                               : job.message || 'Working…')
        if (job.message) {
          setLog((prev) => prev[0] === job.message
            ? prev : [job.message, ...prev].slice(0, 100))
        }
      } else {
        es.close()
        setState('')
        if (job.status === 'failed') setError(job.error.split('\n')[0] || 'Job failed')
        onDone()
      }
    }
    es.onerror = () => { es.close(); setState('') }
  }
  return { watch, state, error, setError, log }
}
