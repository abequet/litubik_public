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

export default function Register() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: instance } = useInstance()
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const user = await api.post<User>('/api/auth/register', {
        email, password, display_name: displayName,
      })
      queryClient.setQueryData(['me'], user)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('Registration failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen grid-rows-[1fr_auto] place-items-center bg-background px-4">
      <div className="w-full max-w-sm">
        <h1 className="mb-6 text-center text-2xl font-semibold tracking-tight text-foreground">
          LitUbik
        </h1>
        <Card className="p-6">
          <form onSubmit={submit} className="space-y-4">
            <h2 className="font-semibold text-foreground">{t('Create your account')}</h2>
            {instance?.demo && (
              <p className="text-sm text-muted-foreground">
                {t('On this demo, accounts are reserved for invited collaborators. To try LitUbik, start a guest session from the demo address instead.')}
              </p>
            )}
            <div>
              <label className="mb-1.5 block text-sm font-medium text-foreground">
                {t('Display name')}{' '}
                <span className="text-muted-foreground">{t('(a pseudonym is fine)')}</span>
              </label>
              <Input
                required value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-foreground">{t('Email')}</label>
              <Input
                type="email" required value={email} autoComplete="email"
                onChange={(e) => setEmail(e.target.value)}
              />
              <p className="mt-1 text-xs text-muted-foreground">
                {t("Added to a project by a colleague? Register with that same email — you'll take over the pending account and its work.")}
              </p>
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-foreground">
                {t('Password')} <span className="text-muted-foreground">{t('(min. 8 characters)')}</span>
              </label>
              <Input
                type="password" required minLength={8} value={password}
                autoComplete="new-password"
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            {(instance?.legal ?? []).includes('terms') && (
              <p className="text-xs text-muted-foreground">
                <Trans
                  i18nKey="By creating an account you accept the <terms>terms of use</terms> and acknowledge the <privacy>privacy notice</privacy>."
                  components={{
                    terms: <Link to="/legal/terms" className="text-primary underline underline-offset-2" />,
                    privacy: <Link to="/legal/privacy" className="text-primary underline underline-offset-2" />,
                  }}
                />
              </p>
            )}
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? t('Creating…') : t('Create account')}
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              {t('Already registered?')}{' '}
              <Link to="/login" className="text-primary hover:underline">{t('Sign in')}</Link>
            </p>
          </form>
        </Card>
      </div>
      <AppFooter className="self-end" />
    </div>
  )
}
