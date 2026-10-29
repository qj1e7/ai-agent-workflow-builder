import type { ReactNode } from 'react'
import { useLocation } from 'react-router'
import { useSession, useSessionStatus } from '../api/context'
import type { OidcSession } from '../api/session'
import { Button } from './Button'
import styles from './SignInGate.module.css'

export const EXPIRED_WORDS = 'Your sign-in has ended. Sign in again to keep working.'
export const SIGNED_OUT_TITLE = 'You are signed out'
export const FAILED_TITLE = 'Sign-in did not work'

function useSignIn(session: OidcSession): () => void {
  const { pathname, search } = useLocation()
  return () => void session.signIn(pathname + search)
}

export function SignInGate({ children }: { children: ReactNode }) {
  const session = useSession()
  const status = useSessionStatus()
  if (session.kind === 'dev' || status.kind === 'signed-in') return children
  switch (status.kind) {
    case 'expired':
      return (
        <>
          <ExpiredBanner session={session} />
          {children}
        </>
      )
    case 'signed-out':
      return (
        <SignInPage session={session} title={SIGNED_OUT_TITLE}>
          Sign in to use AI Workflow Builder.
        </SignInPage>
      )
    case 'failed':
      return (
        <SignInPage session={session} title={FAILED_TITLE}>
          {status.message}
        </SignInPage>
      )
  }
}

function SignInPage({ session, title, children }: { session: OidcSession; title: string; children: ReactNode }) {
  const signIn = useSignIn(session)
  return (
    <main className={styles['page']}>
      <h1>{title}</h1>
      <p>{children}</p>
      <Button variant="primary" onClick={signIn}>
        Sign in
      </Button>
    </main>
  )
}

function ExpiredBanner({ session }: { session: OidcSession }) {
  const signIn = useSignIn(session)
  return (
    <div className={styles['banner']} role="alert">
      <p>{EXPIRED_WORDS}</p>
      <Button variant="primary" onClick={signIn}>
        Sign in
      </Button>
    </div>
  )
}
