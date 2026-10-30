import { ButtonLink } from '../../ui/Button'
import { IconPlus } from '../../ui/icons'
import { FIRST_STARTERS, NEW_WORKFLOW_PATH } from '../new/starters'
import styles from './Home.module.css'
import own from './FirstWorkflow.module.css'

export function FirstWorkflow() {
  return (
    <section className={styles['section']} aria-labelledby="first-h">
      <h2 id="first-h">Start your first workflow</h2>
      <p className="muted">Pick a ready-made one or describe your own. Nothing runs until you check the plan and turn it on.</p>
      <div className={own['starters']}>
        {FIRST_STARTERS.map((starter, index) => (
          <div key={starter.name} className={own['starter']}>
            <h3 id={`first-${String(index)}`}>{starter.name}</h3>
            <p>{starter.what}</p>
            {starter.task === null ? (
              <ButtonLink to="/software" aria-describedby={`first-${String(index)}`}>
                Add your software
              </ButtonLink>
            ) : (
              <ButtonLink to={NEW_WORKFLOW_PATH} state={{ task: starter.task }} aria-describedby={`first-${String(index)}`}>
                Use this
              </ButtonLink>
            )}
          </div>
        ))}
      </div>
      <div>
        <ButtonLink variant="primary" to={NEW_WORKFLOW_PATH} icon={IconPlus}>
          Describe your own
        </ButtonLink>
      </div>
    </section>
  )
}
