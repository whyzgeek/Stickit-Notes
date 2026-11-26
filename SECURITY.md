# Security

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** on this repository
(Security → Report a vulnerability). Do not open a public issue. You can
expect a first response within a week.

## Threat model

stickit-notes puts text into Claude's context at the start of every session
and can carry that text between people. The risks and their mitigations:

| Risk | Mitigation |
|---|---|
| **Secrets or personal data leak through a shared export** | Export refuses any lesson that matches a secret pattern (API keys, tokens, private keys, JWTs, `password=`-style assignments). Home paths, user and host names, emails and IP addresses are redacted, and a diff of each change is shown. You can add your own redaction rules. Exports are files you send yourself; nothing is uploaded. |
| **Prompt injection through imported lessons** | Imports land in `inbox/` and are never injected until you `promote` them after `review`. Promoted imports are injected in a separate block labeled as reference data written by others, after your own lessons and within the same budget. Terminal escapes and control characters are stripped; size limits apply. |
| **Code execution from lesson content** | Lesson text is never executed or interpolated into a shell. Git runs as an argv list, with `--` before URLs and paths, and URLs starting with `-` are refused. Hooks only read files and print JSON. |
| **Personal details ending up in a published store** | Lessons are meant to be shareable, so `new`/`add`/`update` refuse any lesson (any scope) whose text contains your home path, user or host name, an email, an IP address, or one of your `redact.extra` patterns; override with `--allow-personal`. `doctor` flags existing ones, and `export` redacts them again. |
| **A broken or hostile store breaking sessions** | Hooks fail open: invalid files are skipped and counted, every exception is caught, and a 4 s time budget applies. |
| **Concurrent sessions corrupting files** | Writes are atomic (temp file, fsync, rename) and serialized with an advisory lock. |
| **Unexpected network use** | None. The only network access is `stickit sync` and `stickit init --clone`, both explicit, both with timeouts. |

## Limits

- Secret detection is pattern-based. It catches common formats, not every
  secret. Read an export before you share it.
- Your store's git history keeps everything ever committed. If a secret got
  into a lesson, rotate the secret; deleting the lesson is not enough.
- A promoted imported lesson is still text from someone else. Review it as you
  would review code.
