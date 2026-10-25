// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useTranslation } from 'react-i18next'
import { Checkbox } from '@/components/ui/checkbox'

interface Member { user_id: number; display_name: string }

/** Who may settle a conflict — mirrors the server's _require_resolver.
 *  Arbiter mode: the arbiters named for the round (admin or not), or any
 *  project admin when none of them is still a member. Consensus: the
 *  round's reviewers, or an admin. */
export function canResolveConflicts(
  config: { conflict_resolution: string; reviewer_ids: number[]
    arbiter_ids?: number[] | null },
  members: Member[], me: number, isAdmin: boolean,
): boolean {
  if (config.conflict_resolution !== 'arbiter')
    return isAdmin || config.reviewer_ids.includes(me)
  const named = (config.arbiter_ids ?? [])
    .filter((id) => members.some((m) => m.user_id === id))
  return named.length ? named.includes(me) : isAdmin
}

/** Up to two members named as the round's arbiters. With lots, they are also
 *  never paired on the same lot. */
export function ArbiterPicker({ members, arbiters, onArbiters, disabled, lots }: {
  members: Member[]
  arbiters: number[]
  onArbiters: (ids: number[]) => void
  disabled: boolean
  lots?: boolean
}) {
  const { t } = useTranslation()
  return (
    <div className="ml-6 mt-2 rounded-md border border-border p-3">
      <p className="mb-1 text-sm text-muted-foreground">
        {t('Arbiters (up to two)')}
        <span className="text-muted-foreground/70">
          {' '}{lots
            ? t('— never paired on the same lot, so every conflict has an arbiter who did not vote on it')
            : t('— they settle the conflicts of this round. With none named, any project admin does.')}
        </span>
      </p>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {members.map((m) => {
          const checked = arbiters.includes(m.user_id)
          return (
            <label key={m.user_id} className="flex items-center gap-2 text-sm text-muted-foreground">
              <Checkbox disabled={disabled || (!checked && arbiters.length >= 2)}
                        checked={checked}
                        onCheckedChange={(v) => onArbiters(v
                          ? [...arbiters, m.user_id]
                          : arbiters.filter((id) => id !== m.user_id))} />
              {m.display_name}
            </label>
          )
        })}
      </div>
    </div>
  )
}
