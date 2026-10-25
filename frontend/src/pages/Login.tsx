// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Trans, useTranslation } from 'react-i18next'
import { api, ApiError, type User } from '../api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import AppFooter from '../components/AppFooter'
import { useInstance } from '../components/DemoBanner'

/** Demo instances, on their guest host name: try LitUbik in one click. No
 * e-mail, no password — the session is a sandbox deleted at the daily reset. */
function GuestEntry({ resetHour }: { resetHour: number }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [accepted, setAccepted] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const start = async () => {
    setBusy(true)
    setError('')
    try {
      const user = await api.post<User>('/api/auth/guest', { accept_terms: true })
      queryClient.setQueryData(['me'], user)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('Could not start a guest session'))
    } finally {
      setBusy(false)
    }
  }

  const link = 'text-primary underline underline-offset-2'
  return (
    <Card className="mb-4 p-6">
      <h2 className="font-semibold text-foreground">{t('Try LitUbik without an account')}</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        {resetHour >= 0
          ? t('One click opens a guest session with an example review already set up. No e-mail, no password; everything is deleted every day at {{hour}} UTC.',
              { hour: `${String(resetHour).padStart(2, '0')}:00` })
          : t('One click opens a guest session with an example review already set up. No e-mail, no password.')}
      </p>
      <label className="mt-3 flex items-start gap-2 text-sm text-foreground">
        <input type="checkbox" className="mt-0.5" checked={accepted}
               onChange={(e) => setAccepted(e.target.checked)} />
        <span>
          <Trans
            i18nKey="I accept the <terms>terms of use</terms> and have read the <privacy>privacy notice</privacy>."
            components={{
              terms: <Link to="/legal/terms" className={link} />,
              privacy: <Link to="/legal/privacy" className={link} />,
            }}
          />
        </span>
      </label>
      {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
      <Button className="mt-3 w-full" disabled={!accepted || busy} onClick={start}>
        {busy ? t('Preparing your session…') : t('Start a guest session')}
      </Button>
    </Card>
  )
}

export default function Login() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: instance } = useInstance()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const guestEntry = !!instance?.guest_entry

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const user = await api.post<User>('/api/auth/login', { email, password })
      queryClient.setQueryData(['me'], user)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('Login failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen grid-rows-[1fr_auto] place-items-center bg-background px-4">
      <div className="w-full max-w-sm">
        <h1 className="mb-1 text-center text-2xl font-semibold tracking-tight text-foreground">
          LitUbik
        </h1>
        <p className="mb-6 text-center text-sm text-muted-foreground">
          {t('Systematic review pipeline')}
        </p>
        {guestEntry && <GuestEntry resetHour={instance?.reset_hour ?? -1} />}
        <Card className="p-6">
          <form onSubmit={submit} className="space-y-4">
            {guestEntry && (
              <h2 className="font-semibold text-foreground">{t('Invited collaborators: sign in')}</h2>
            )}
            <div>
              <label className="mb-1.5 block text-sm font-medium text-foreground">{t('Email')}</label>
              <Input
                type="email" required value={email} autoComplete="email"
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-foreground">{t('Password')}</label>
              <Input
                type="password" required value={password} autoComplete="current-password"
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" disabled={busy} className="w-full"
                    variant={guestEntry ? 'outline' : 'default'}>
              {busy ? t('Signing in…') : t('Sign in')}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              {instance?.demo ? t('Invited, without an account yet?') : t('No account?')}{' '}
              <Link to="/register" className="text-primary hover:underline">{t('Register')}</Link>
            </p>
          </form>
        </Card>
      </div>
      <AppFooter className="self-end" />
    </div>
  )
}
