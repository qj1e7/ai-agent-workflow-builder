import type { ReactNode } from 'react'
import styles from './PageHeader.module.css'

interface PageHeaderProps {
  title: string
  children?: ReactNode
  aside?: ReactNode
}

export function PageHeader({ title, children, aside }: PageHeaderProps) {
  return (
    <header className={styles['header']}>
      <div className={styles['words']}>
        <h1>{title}</h1>
        {children ? <p className={styles['lede']}>{children}</p> : null}
      </div>
      {aside ? <div className={styles['aside']}>{aside}</div> : null}
    </header>
  )
}
