// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useQuery } from '@tanstack/react-query'
import { api, type Framings, type FrameworkInfo, type ReviewTypeInfo } from '../api'

/** The review-type / question-framework catalogue, served by the backend so
 * the same list drives the UI labels and what the AI is told. Cached for the
 * session: it only changes with the app version. */
export function useFramings() {
  return useQuery<Framings>({
    queryKey: ['framings'],
    queryFn: () => api.get('/api/framings'),
    staleTime: Infinity,
  })
}

export function findFramework(
  framings: Framings | undefined, key: string | undefined,
): FrameworkInfo | undefined {
  return framings?.frameworks.find((f) => f.key === key)
}

export function findReviewType(
  framings: Framings | undefined, key: string | undefined,
): ReviewTypeInfo | undefined {
  return framings?.review_types.find((r) => r.key === key)
}
