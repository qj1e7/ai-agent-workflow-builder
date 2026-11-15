import { Link } from 'react-router'
import { IconChevronLeft } from '../ui/icons'
import styles from './BackToChat.module.css'

/** The way back from a page the chat opened. The conversation is where it was left (ChatProvider keeps it). */
export function BackToChat() {
  return (
    <Link to="/" className={styles['back']}>
      <IconChevronLeft size={16} />
      Back to the chat
    </Link>
  )
}
