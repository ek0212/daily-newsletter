# Project Instructions (CLAUDE.md)

## How to Work with Me

- Focus on delivering working, functional changes quickly.
- For any new or modified feature: implement it cleanly, then run a quick manual verification (build + basic flow test) before handing control back to me.
- Do not treat every task as requiring full end-to-end regression testing. Ask me if deeper validation is needed.
- Log major architectural or product decisions in `DECISIONS.md` (project root). Keep each entry brief: date, decision, context, why chosen, alternatives considered, status (ACTIVE / BACKTRACKED).

## Code Standards

- Follow SOLID principles and keep functions small and single-purpose.
- Use clear, descriptive names for variables, functions, and files.
- Prefer DRY: reuse existing patterns and utilities from the codebase rather than duplicating logic.
- Move magic numbers, strings, and repeated values to a centralized constants or config file when it improves maintainability.
- Write tests only for complex core logic (not every helper).
- Add comments sparingly — only for "why" when the code alone doesn't make the intent obvious.
- Prioritize functionality, clarity, and performance over aesthetics in early iterations.
- For frontend work: follow the guidelines in Anthropic's frontend-design skill (https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md).

## Security (Non-Negotiable)

- Never embed API keys, secrets, or credentials in client-side code, generated files, or anything committed to git.
- Store secrets only in `.env` (gitignored), environment variables, or server-side code.
- For client-side needs, require the user to provide their own key at runtime (e.g., via input or localStorage).
- After any change that could involve keys or external services, search the build/output for common secret patterns (e.g., `sk-`, `AIzaSy`, `ghp_`, `AKIA`) to confirm nothing leaked.

## Validation (After Meaningful Changes)

**Build & Basic Checks:**

- Fix all build errors and warnings before handing back.
- Run the project from the root directory so paths and dependencies resolve correctly.
- Use a feature flag or env variable for debug/verbose logging during development.

**UI / Flow Checks:**

- Quickly walk through the main user flow affected by your changes and confirm it works.
- Test at mobile viewport (≈375px width) for obvious layout, overflow, or interaction issues.
- Verify success/error paths don't create dead ends or stale state.
- Ensure required fields are handled and no broken links/assets are introduced.

**Performance & General:**

- Batch API calls where it makes sense and respect rate limits.
- Keep changes focused — avoid unrelated refactors unless asked.

Do not over-validate or run heavy automation (e.g., full Puppeteer screenshot suites) on every iteration unless the task specifically requires it. When in doubt, implement first and confirm basics, then ask me for next steps.

## Writing & Communication Style

- Be direct and concise. Use simple, clear sentences.
- Present information neatly (lists, short paragraphs, code examples when helpful).
- Avoid rhetorical questions, em dashes, three-part alliteration, vague inspiration, or unsourced factual claims.
- When uncertain, use hedging language rather than strong assertions.
- Never ship LLM-generated factual claims without verification against an authoritative source if accuracy matters.

---

**Quick Reference Commands** (replace with your actual ones):

- Build: `npm run build` (or equivalent)
- Dev: `npm run dev`
- Test: `npm test`
- Lint/Fix: `npm run lint -- --fix`

Update this file over time as patterns solidify. Keep it concise — under ~150-200 lines total for best results.
