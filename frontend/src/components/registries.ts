// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useQuery } from '@tanstack/react-query'
import { api, type RegistryInfo } from '../api'

/** The register catalogue (PROSPERO, OSF, …), served by the backend so the
 * same list drives the settings form, the audit trail and the Methods draft.
 * Cached for the session: it only changes with the app version. */
export function useRegistries() {
  return useQuery<RegistryInfo[]>({
    queryKey: ['registries'],
    queryFn: () => api.get('/api/registries'),
    staleTime: Infinity,
  })
}

export function findRegistry(
  registries: RegistryInfo[] | undefined, key: string | undefined,
): RegistryInfo | undefined {
  return registries?.find((r) => r.key === key)
}
