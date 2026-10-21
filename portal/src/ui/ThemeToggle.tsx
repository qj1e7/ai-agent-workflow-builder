import { IconMoon, IconSun } from './icons'
import { useTheme } from './theme'
import styles from './ThemeToggle.module.css'

export function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const dark = theme === 'dark'
  return (
    <button
      type="button"
      className={styles['toggle']}
      aria-label={dark ? 'Use light theme' : 'Use dark theme'}
      onClick={() => setTheme(dark ? 'light' : 'dark')}
    >
      {dark ? <IconSun size={20} strokeWidth={2} /> : <IconMoon size={20} strokeWidth={2} />}
    </button>
  )
}
