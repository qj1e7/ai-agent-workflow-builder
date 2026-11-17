| Block | `internal` | `external` | `internal-escape` | `external-escape` | `deprecated-allowed` | `ssrf-on` |
|---|---|---|---|---|---|---|
| Code (JavaScript) | env no, config no, runner token no, identity 400 | env no, config no, runner token no, identity 400 | env YES, config YES, runner token YES, identity 200 | env no, config no, runner token YES, identity 400 | env no, config no, runner token no, identity 400 | env no, config no, runner token no, identity not reached (blocked by n8n) |
| AI Transform | env no, config no, runner token no, identity 400 | env no, config no, runner token no, identity 400 | env YES, config YES, runner token YES, identity 200 | env no, config no, runner token YES, identity 400 | env no, config no, runner token no, identity 400 | env no, config no, runner token no, identity not reached (blocked by n8n) |
| Sort, code mode | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached |
| Item Lists, code sort | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached | env no, config no, runner token no, identity not reached |
| Function | refused by n8n | refused by n8n | refused by n8n | refused by n8n | env no, config no, runner token no, identity 400 | refused by n8n |
| Function Item | refused by n8n | refused by n8n | refused by n8n | refused by n8n | env no, config no, runner token no, identity 400 | refused by n8n |
| LangChain Code | refused by n8n | refused by n8n | refused by n8n | refused by n8n | env YES, config no, runner token YES, identity 200 | refused by n8n |
| Code Tool (JavaScript), called by an AI Agent | env no, config no, runner token no, identity 400 | env no, config no, runner token no, identity 400 | env YES, config YES, runner token YES, identity 200 | env no, config no, runner token YES, identity 400 | env no, config no, runner token no, identity 400 | did not run |
| Code (Python), no import, `open()` | python runner unavailable | ran, env no, runner token no, `open` refused | python runner unavailable | ran, env no, runner token YES | python runner unavailable | python runner unavailable |
| Code (Python), `import os` | python runner unavailable | refused before running | python runner unavailable | ran, env no, runner token YES | python runner unavailable | python runner unavailable |
| Code (Python), `__subclasses__` | python runner unavailable | refused before running | python runner unavailable | refused before running | python runner unavailable | python runner unavailable |
| Code Tool (Python), no import, `open()` | timed out | ran, env no, runner token no, `open` refused | timed out | ran, env no, runner token YES | timed out | did not run |
| Merge, SQL `control` | 1 row(s) | 1 row(s) | 1 row(s) | 1 row(s) | 1 row(s) | 1 row(s) |
| Merge, SQL `allowed_folder` | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox |
| Merge, SQL `n8n_config` | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox |
| Merge, SQL `proc_self_environ` | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox |
| Merge, SQL `url` | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox | refused by the SQL sandbox |
| HTTP Request to the identity endpoint, no header | 400 | 400 | 400 | 400 | 400 | blocked by n8n's SSRF protection |

Left out, and the same as `internal` in every row: `files-block-off`, `files-restrict-empty`, `files-restrict-n8n`, `files-restrict-n8n-block-off`.

| Block | `internal` | `external` | `files-block-off` | `files-restrict-empty` | `files-restrict-n8n` | `files-restrict-n8n-block-off` |
|---|---|---|---|---|---|---|
| Execute Sub-workflow, from a file, `~/.n8n-files` | read, but not a workflow | read, but not a workflow | read, but not a workflow | read, but not a workflow | blocked by n8n | blocked by n8n |
| Execute Sub-workflow, from a file, `~/.n8n/config` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | other error (52 chars) |
| Execute Sub-workflow, from a file, a file outside both folders | blocked by n8n | blocked by n8n | blocked by n8n | read, but not a workflow | blocked by n8n | blocked by n8n |
| Git, clone from, `~/.n8n` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n |
| Git, clone into, `~/.n8n/custom` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n |
| Git, status, `~/.n8n-files` | not a git repository | not a git repository | not a git repository | not a git repository | blocked by n8n | blocked by n8n |
| Git, status, `~/.n8n` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | not a git repository |
| Read Binary File, read `~/.n8n-files` | READ (control marker) | READ (control marker) | READ (control marker) | READ (control marker) | blocked by n8n | blocked by n8n |
| Read Binary File, read a symlink to `~/.n8n/config` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY (encryptionKey marker) |
| Read Binary File, read `~/.n8n/config` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY (encryptionKey marker) |
| Read Binary File, read a file outside both folders | blocked by n8n | blocked by n8n | blocked by n8n | READ (outside marker) | blocked by n8n | blocked by n8n |
| Read Binary File, read `/proc/1/environ` | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY, DBPASS, NODEKEY, STARTSECRET, IDHEADER, RUNNERTOKEN | blocked by n8n | blocked by n8n |
| Read Binary File, read `/proc/self/environ` | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY, DBPASS, NODEKEY, STARTSECRET, IDHEADER, RUNNERTOKEN | blocked by n8n | blocked by n8n |
| Read Binary Files, read `~/.n8n-files` | READ (control marker) | READ (control marker) | READ (control marker) | READ (control marker) | blocked by n8n | blocked by n8n |
| Read Binary Files, read a symlink to `~/.n8n/config` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY (encryptionKey marker) |
| Read Binary Files, read `~/.n8n/config` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY (encryptionKey marker) |
| Read Binary Files, read a file outside both folders | blocked by n8n | blocked by n8n | blocked by n8n | READ (outside marker) | blocked by n8n | blocked by n8n |
| Read Binary Files, read `/proc/1/environ` | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY, DBPASS, NODEKEY, STARTSECRET, IDHEADER, RUNNERTOKEN | blocked by n8n | blocked by n8n |
| Read Binary Files, read `/proc/self/environ` | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY, DBPASS, NODEKEY, STARTSECRET, IDHEADER, RUNNERTOKEN | blocked by n8n | blocked by n8n |
| Read/Write Files from Disk, read `~/.n8n-files` | READ (control marker) | READ (control marker) | READ (control marker) | READ (control marker) | blocked by n8n | blocked by n8n |
| Read/Write Files from Disk, read a symlink to `~/.n8n/config` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY (encryptionKey marker) |
| Read/Write Files from Disk, read `~/.n8n/config` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY (encryptionKey marker) |
| Read/Write Files from Disk, read a file outside both folders | blocked by n8n | blocked by n8n | blocked by n8n | READ (outside marker) | blocked by n8n | blocked by n8n |
| Read/Write Files from Disk, read `/proc/1/environ` | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY, DBPASS, NODEKEY, STARTSECRET, IDHEADER, RUNNERTOKEN | blocked by n8n | blocked by n8n |
| Read/Write Files from Disk, read `/proc/self/environ` | blocked by n8n | blocked by n8n | blocked by n8n | READ ENCKEY, DBPASS, NODEKEY, STARTSECRET, IDHEADER, RUNNERTOKEN | blocked by n8n | blocked by n8n |
| Read/Write Files from Disk, write `~/.n8n-files` | WROTE | WROTE | WROTE | WROTE | blocked by n8n | blocked by n8n |
| Read/Write Files from Disk, write `~/.n8n/custom` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | WROTE |
| Read/Write Files from Disk, write a file outside both folders | blocked by n8n | blocked by n8n | blocked by n8n | WROTE | blocked by n8n | blocked by n8n |
| Write Binary File, write `~/.n8n-files` | WROTE | WROTE | WROTE | WROTE | blocked by n8n | blocked by n8n |
| Write Binary File, write `~/.n8n/custom` | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | blocked by n8n | WROTE |
| Write Binary File, write a file outside both folders | blocked by n8n | blocked by n8n | blocked by n8n | WROTE | blocked by n8n | blocked by n8n |

Left out, and the same as `internal` in every row: `internal-escape`, `external-escape`, `deprecated-allowed`, `ssrf-on`.
