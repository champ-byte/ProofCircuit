// Who can sign in to the demo and where each role lands. The server stays the authority on what a
// role may do; these rules only decide which screens the UI offers.
import type { CaseSummary, DemoUser, InboxView } from './types/api'

export const DEMO_MID = 'MID-DEMO-001'
export type Role = 'owner' | 'staff' | 'reviewer'
export const SIGN_IN_ROLES: Role[] = ['owner', 'staff', 'reviewer']

const IDENTITY_KEY = 'proofsaathi.identity'
// Test accounts (Eval…, Other Owner) and the operator never appear on the sign-in screen.
const SIGN_IN_HANDLES: Record<string, Role> = {
  owner: 'owner',
  'staff-delivery': 'staff',
  'staff-billing': 'staff',
  reviewer: 'reviewer',
}

/** "MID/handle" for a person offered on the sign-in screen, or null for anyone else. */
export function signInRole(identity: string | null): Role | null {
  if (!identity) return null
  const [mid, handle] = identity.split('/')
  return mid === DEMO_MID ? SIGN_IN_HANDLES[handle] ?? null : null
}

export function signInUsers(users: DemoUser[]): DemoUser[] {
  return users.filter((u) => signInRole(`${u.mid}/${u.handle}`) === u.role)
}

export function homeFor(role: string | null | undefined): string {
  if (role === 'staff') return '/staff'
  if (role === 'reviewer') return '/review'
  if (role === 'owner') return '/cases'
  return '/signin'
}

/** "Asha (Owner)" → "Asha". */
export function firstName(displayName: string): string {
  return displayName.replace(/\s*\(.*\)\s*$/, '')
}

/** The saved identity, ignoring anything that is not a sign-in person (old operator or test picks). */
export function savedIdentity(): string | null {
  try {
    const saved = localStorage.getItem(IDENTITY_KEY)
    return signInRole(saved) ? saved : null
  } catch {
    return null
  }
}

export function saveIdentity(identity: string) {
  try {
    localStorage.setItem(IDENTITY_KEY, identity)
  } catch {
    /* private mode: the person signs in again after a reload */
  }
}

/** A case needs the reviewer when it is in human review or has an open review task. */
export function needsReview(summary: CaseSummary, inbox: InboxView | null): string[] | null {
  const open = (inbox?.tasks ?? []).filter((task) => task.kind === 'review' && task.status === 'open')
  if (summary.workflow_state !== 'NEEDS_HUMAN_REVIEW' && open.length === 0) return null
  return open.map((task) => task.question ?? '').filter(Boolean)
}
