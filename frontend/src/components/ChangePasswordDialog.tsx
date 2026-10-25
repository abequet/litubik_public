// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '@/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'

export default function ChangePasswordDialog({
  open, onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirmNext, setConfirmNext] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  const reset = () => {
    setCurrent(''); setNext(''); setConfirmNext(''); setError(''); setDone(false)
  }

  const change = useMutation({
    mutationFn: () => api.post('/api/auth/change-password', {
      current_password: current, new_password: next,
    }),
    onSuccess: () => { setDone(true); setError('') },
    onError: (e) =>
      setError(e instanceof ApiError ? e.message : t('Password change failed')),
  })

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (next !== confirmNext) {
      setError(t('New passwords do not match'))
      return
    }
    change.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) reset(); onOpenChange(o) }}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('Change password')}</DialogTitle>
          <DialogDescription>
            {t('Pick a new password of at least 8 characters.')}
          </DialogDescription>
        </DialogHeader>
        {done ? (
          <div className="space-y-3">
            <p className="text-sm text-success">{t('✓ Password changed.')}</p>
            <Button size="sm" onClick={() => { reset(); onOpenChange(false) }}>
              {t('Close')}
            </Button>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                {t('Current password')}
              </label>
              <Input type="password" required autoFocus value={current}
                     onChange={(e) => setCurrent(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                {t('New password')}
              </label>
              <Input type="password" required minLength={8} value={next}
                     onChange={(e) => setNext(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                {t('Confirm new password')}
              </label>
              <Input type="password" required minLength={8} value={confirmNext}
                     onChange={(e) => setConfirmNext(e.target.value)} />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" size="sm"
                    disabled={change.isPending || !current || !next || !confirmNext}>
              {change.isPending ? t('Changing…') : t('Change password')}
            </Button>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
