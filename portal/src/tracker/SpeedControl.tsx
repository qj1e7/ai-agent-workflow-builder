import { useId } from 'react'
import type { Speed } from '../run'
import { SPEEDS } from './speed'
import { tourStop } from '../tour/stops'
import styles from './SpeedControl.module.css'

/** 1x, 2x and Instant as native radios, so arrow keys and the checked state come with the browser. */
export function SpeedControl({ value, onChange }: { value: Speed; onChange: (speed: Speed) => void }) {
  const name = useId()
  return (
    <fieldset className={styles['seg']} {...tourStop('speed')}>
      <legend className="visually-hidden">Speed</legend>
      {SPEEDS.map((option) => (
        <label key={option.label} className={styles['option']}>
          <input type="radio" name={name} value={String(option.value)} checked={value === option.value} onChange={() => onChange(option.value)} />
          <span>{option.label}</span>
        </label>
      ))}
    </fieldset>
  )
}
