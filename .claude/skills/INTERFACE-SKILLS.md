# Interface skills

These ten skills review and polish the Portal's screens. They come from [jakubkrehel/skills](https://github.com/jakubkrehel/skills) at commit `672ae44ace6aaed65b86cbb1e2fd6fbea0e79578` (plugin version 1.23.0), under the MIT license in `LICENSE-interfaces.txt`. They are copied unchanged.

| Skill | Use it to |
| --- | --- |
| `better-interface` | Review a screen, flow or the whole Portal, and get one ranked report |
| `interface-review` | Review a branch or pull request for interface problems it added |
| `better-accessibility` | Check keyboard, focus, names, forms and screen-reader output |
| `better-layout` | Check grouping, alignment, spacing and narrow windows |
| `better-writing` | Check the words on screen |
| `better-typography` | Check the type scale, weights and wrapping |
| `better-colors` | Check colour roles and contrast |
| `better-ui` | Check surfaces, radius, shadows and icons |
| `better-motion` | Check what moves, and how |
| `variant` | Build a few versions of one component to choose from |

`better-interface` loads the seven `better-*` skills, so keep them together.

## What we left out, and why

- `afk` and `upskill` work through the project on their own. Our rules want a person to start work and approve each merge.
- `explain-interface` and `build-design` explain other websites or build from Figma. We don't need them.
- `break` and `state-machine` render a component under every state on a throwaway page. `variant` mentions them, but it works without them.

## Our rules come first

AGENTS.md, `docs/design/ai-native-principles.md` and the chat-first sketch win wherever a skill disagrees. For example, we write without em dashes, and a new user-facing sentence needs the team lead's OK.

## Updating

Copy the folders again from a newer commit, read the diff, and update the commit above. These are instructions that agents follow, so read every changed line first.
