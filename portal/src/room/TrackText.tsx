import { headlineWords, stopWords, type Track } from '../run'
import { ButtonLink } from '../ui/Button'

/** Each stop in words, in order. Stands in for the drawn line until the Tracker view lands. */
export function StopList({ track, label }: { track: Track; label: string }) {
  return (
    <ol aria-label={label}>
      {track.stops.map((stop, index) => (
        <li key={stop.key}>
          {stop.name}. {stopWords(stop, track.parcel?.at === index ? track.parcel.form : null)}
        </li>
      ))}
    </ol>
  )
}

/** The run's name, its headline as the live region, the subline, the stops, and the approval page while a person is needed. */
export function TrackText({ track, title, titleId }: { track: Track; title: string; titleId?: string }) {
  const gate = track.gate
  return (
    <>
      <h1 id={titleId}>{title}</h1>
      <div role="status" aria-atomic="true">
        <h2>{headlineWords(track.headline, { canDecide: false })}</h2>
        <p>{track.subline}</p>
      </div>
      <StopList track={track} label="Steps in this run" />
      {gate?.state === 'waiting' && gate.link ? <ButtonLink to={gate.link}>Open the approval page</ButtonLink> : null}
    </>
  )
}
