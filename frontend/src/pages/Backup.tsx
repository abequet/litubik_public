// SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { HardDriveDownload } from 'lucide-react'
import { api, type User } from '../api'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'

/** Superadmin — download a full backup of the instance (SQLite database +
 * secret.key, optionally every stored project file). The recurring variant
 * lives in scripts/backup_litubik.ps1 (documented in the help). */
export default function BackupPage() {
  const { t } = useTranslation()
  const { data: me } = useQuery<User | null>({
    queryKey: ['me'], queryFn: () => api.get('/api/auth/me'),
  })
  const [includeFiles, setIncludeFiles] = useState(true)

  if (!me?.is_admin) {
    return <p className="text-sm text-muted-foreground">
      {t('Only an application admin downloads instance backups.')}
    </p>
  }

  return (
    <div>
      <h1 className="text-xl font-semibold tracking-tight text-foreground">
        {t('Instance backup')}
      </h1>
      <p className="mt-1 mb-4 max-w-2xl text-sm text-muted-foreground">
        {t('One zip with the whole database (all projects, all accounts) plus the secret key — everything needed to bring the instance back after a crash or a bad manipulation.')}
      </p>
      <Card className="max-w-2xl space-y-4 p-5">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox" checked={includeFiles}
            onChange={(e) => setIncludeFiles(e.target.checked)}
          />
          {t('Include stored files — PDFs, raw RIS, protocols (heavier archive, but a complete restore)')}
        </label>
        <Button asChild>
          <a href={`/api/admin/backup?files=${includeFiles}`}>
            <HardDriveDownload className="size-4" />
            {t('Download a full backup (.zip)')}
          </a>
        </Button>
        <p className="text-xs text-muted-foreground">
          {t('To restore: stop the app, put litubik.db (and secret.key) from the zip back into the data/ folder, remove any litubik.db-wal / litubik.db-shm files, unzip storage/ next to them, restart.')}
        </p>
        <p className="text-xs text-muted-foreground">
          {t('For an automatic recurring backup on your machine (with rotation of the oldest copies), use scripts/backup_litubik.ps1 from the repository — see the help, “Collaboration” page, “Backups” section.')}
        </p>
      </Card>
    </div>
  )
}
