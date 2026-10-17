import { Navigate, useParams } from 'react-router'

/** Link from the after-call text: remember which call this phone is looking at, then open the inbox. */
export function ReportLink() {
  const { callId } = useParams()
  if (callId && callId !== localStorage.getItem('willow.call')) {
    // A new call starts with a clean slate on this device.
    for (const key of ['approved', 'read', 'edits', 'confirmed']) localStorage.removeItem(`willow.${key}`)
    localStorage.setItem('willow.call', callId)
  }
  return <Navigate to="/app" replace />
}
