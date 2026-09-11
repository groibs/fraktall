import './globals.css'
import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Fraktall',
  description: 'Fraktall remote console for local AI video processing'
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  )
}
