import styles from './PageHead.module.css'

export const NOT_BUILT_WORDS = 'This page is not built yet.'

export function PageHead({ heading, lead }: { heading: string; lead: string }) {
  return (
    <div className={styles['head']}>
      <div>
        <h1 tabIndex={-1}>{heading}</h1>
        <p>{lead}</p>
      </div>
    </div>
  )
}

export function EmptyPage({ heading, lead }: { heading: string; lead: string }) {
  return (
    <>
      <PageHead heading={heading} lead={lead} />
      <p className="muted">{NOT_BUILT_WORDS}</p>
    </>
  )
}
