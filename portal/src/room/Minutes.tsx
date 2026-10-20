import { Fragment } from "react";
import type { MinutesEntry } from "../run";
import { cx } from "../ui/cx";
import { ActorAvatar } from "./Caption";
import styles from "./Minutes.module.css";

interface MinutesProps {
  entries: readonly MinutesEntry[];
  technical: boolean;
  onTechnical: (on: boolean) => void;
}

const clock = new Intl.DateTimeFormat("en-SG", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

/** The time of day a Minutes entry shows, HH:MM:SS, shared with the overview's So far list. */
export function clockTime(ms: number): string {
  return clock.format(new Date(ms));
}
const exact = new Intl.DateTimeFormat("en-SG", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  fractionalSecondDigits: 3,
  hour12: false,
});

export function Minutes({ entries, technical, onTechnical }: MinutesProps) {
  const shown = technical
    ? entries
    : entries.filter((entry) => entry.tier === "story");
  const rows = shown.map((entry, index) => ({
    entry,
    divider: entry.attempt !== (shown[index - 1]?.attempt ?? 1),
  }));
  return (
    <section className={styles["minutes"]} aria-labelledby="minutes-title">
      <div className={styles["head"]}>
        <h2 id="minutes-title">Minutes</h2>
        <button
          type="button"
          role="switch"
          aria-checked={technical}
          className={styles["switch"]}
          onClick={() => onTechnical(!technical)}
        >
          <span className={styles["knob"]} aria-hidden="true" />
          Show technical details
        </button>
      </div>
      {shown.length === 0 ? (
        <p className="muted">Nothing has happened yet.</p>
      ) : null}
      <div role="log" aria-label="Minutes of the run">
        <ol className={styles["log"]}>
          {rows.map(({ entry, divider }) => {
            return (
              <Fragment key={entry.seq}>
                {divider ? (
                  <li
                    className={styles["divider"]}
                    aria-label={`Attempt ${entry.attempt}`}
                  >
                    <span>Attempt {entry.attempt}</span>
                  </li>
                ) : null}
                <li
                  className={cx(
                    styles["entry"],
                    entry.tier === "technical" && styles["technical"],
                  )}
                >
                  <ActorAvatar actor={entry.actor} size={24} />
                  <div className={styles["body"]}>
                    <p className={styles["summary"]}>{entry.summary}</p>
                    {entry.quote ? (
                      <blockquote className={styles["quote"]}>
                        {entry.quote}
                      </blockquote>
                    ) : null}
                    <p className={styles["meta"]}>
                      <time dateTime={new Date(entry.at).toISOString()}>
                        {(technical ? exact : clock).format(new Date(entry.at))}
                      </time>
                      {technical ? (
                        <>
                          <span className={styles["kind"]}>{entry.kind}</span>
                          <span>seq {entry.seq}</span>
                        </>
                      ) : null}
                    </p>
                  </div>
                </li>
              </Fragment>
            );
          })}
        </ol>
      </div>
    </section>
  );
}
