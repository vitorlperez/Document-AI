# M22 — Chat answer formatting

Status: verified by pane-285. The shared tree was already on mission27/org-onboarding
when inspected (HEAD bfe56a9); no branch switch or reset was performed. Scope: answer-blocks.ts, answer-markdown.tsx,
chat-workspace.css, synthesis guidance in questions.py, regression tests and visual evidence.
Do not change or commit existing library/onboarding edits or graphify-out/. No push.
During validation another worker committed onboarding as 575528f on the shared branch.
Delivery to main uses an isolated worktree and only this patch, without that concurrent commit.

Reproduction: the supplied screenshot shows four professional experiences, each numbered 1,
and oversized Google Drive labels. `docker compose logs backend --since 60m` fails because
the service is named api; api logs contain no raw answer, so the fixture is reconstructed.
Hypothesis confirmed in source: parseMarkdown stops its list loop at a blank line, creating
separate list blocks; BlockView emits an ol without start for each. Even sequential input
therefore resets. Citations are inline replacements and do not insert block boundaries.
Provider cause: 33f50cf deleted .citation-tool from question-scope.css. The source-row JSX
in 9df6713 has that same class; edde2b7 only adds focus/ids and 7d3df7e does not restyle
sources. Without that rule, provider text inherits 16px vs 12px names. The global 44px
minimum on product links also inflates every row to 64–65px (including padding).

Acceptance: continuous loose lists, initial start preserved, paragraph continuations and
citations retained; prompt calibrates detail without query routing; compact linked sources;
before/after desktop and 390px screenshots; frontend tests, tsc, eslint and backend pytest.

## Changes and evidence

- The parser now keeps blank-separated items in one list, retains initial start (including
  ::: steps), and retains indented continuation paragraphs and their citations. Headings,
  independent prose and a changed base marker type still end the list.
- Shared synthesis guidance calibrates detail semantically, including explicit detail
  requests taking precedence over an opening question word. Professional experience is
  company — role — period; highlights at most one short sentence. No runtime query rules.
- Source metadata is 11px secondary text vs 12px file names; original links are centered
  in compact rows with an enlarged invisible hit area. Links and citation focus still work.
- Red before the fix: screenshot/list regression failed; prompt contracts 10 failed,
  8 passed. Green: 39/39 frontend tests; 25/25 focused backend/prompt tests; full pytest
  911 passed, 13 skipped, 4 deprecation warnings. tsc and eslint exit 0; diff --check exit 0.
- Playwright ran against a separate real Vite frontend at 127.0.0.1:3014, using only mocked
  API responses. Docker at :3000 was not restarted. The same long fixture is used before
  and after; screenshots do not claim a live LLM answer. All eight PNGs were captured;
  both answer crops before/after were visually inspected. After: 1., 2., 3., 4., six citation
  pills, three original links, no horizontal overflow. Source heights: desktop 36/37/37px,
  mobile 48/37/37px. See artifacts/chat-answer-format/* and before/after-results.json.
- All requested preserved commits remain ancestors. Existing dirty code diffs were compared
  byte for byte and remain unchanged. No graph update was run or graph files committed,
  respecting the explicit boundary. A graph query was used for initial navigation.
- Rebuild frontend and api images to apply renderer/CSS and synthesis prompt to Docker;
  backend also serves worker images from the common build. No schema migration required.

skills: inline [oc-builder, oc-blackbox, oc-stamp]
