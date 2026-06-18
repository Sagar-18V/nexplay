import { defineConfig } from '@prisma/config'
import { readFileSync } from 'fs'
import { resolve } from 'path'

// Prisma's config loader (c12) sets dotenv: false, so we must load .env manually.
// Parse and inject the .env file synchronously before defineConfig reads process.env.
try {
  const envPath = resolve(process.cwd(), '.env')
  const envContent = readFileSync(envPath, 'utf-8')
  for (const line of envContent.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const eqIndex = trimmed.indexOf('=')
    if (eqIndex === -1) continue
    const key = trimmed.slice(0, eqIndex).trim()
    const value = trimmed.slice(eqIndex + 1).trim().replace(/^["']|["']$/g, '')
    if (!(key in process.env)) process.env[key] = value
  }
} catch {
  // .env not found — rely on environment being pre-set
}

export default defineConfig({
  schema: 'prisma/schema.prisma',
  datasource: {
    url: process.env.DATABASE_URL!,
  },
})