import { PageHead } from './PageHead'

export const ASK_HEADING = 'Ask an Operator to add you'

/** The sign-in worked, but no Operator has put this person on the People list yet. */
export function AskToBeAdded({ display }: { display: string }) {
  return (
    <>
      <PageHead
        heading={ASK_HEADING}
        lead={`You are signed in as ${display}, but you are not on the People list yet. An Operator on the team can add you. Once they have, reload this page.`}
      />
    </>
  )
}
