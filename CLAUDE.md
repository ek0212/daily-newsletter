### How to Work

- Do not consider a task complete until it has been tested end to end and meets the stated requirements
- If a task involves creating or modifying a feature, run the app and confirm it works before returning control to me
- Log significant architectural or product decisions in `DECISIONS.md` in the project root. Each entry should include: date, decision, context, alternatives considered, why they were rejected, and current status (ACTIVE or BACKTRACKED). This prevents future sessions from re-exploring dead ends

### Code Standards

- Move all magic numbers and hardcoded text to a centralized constants file
- Keep functions small and focused (SOLID principles)
- Use descriptive variable and function names
- Follow DRY: prefer reusing existing patterns in the codebase over inventing new solutions
- Write tests for core logic
- Add comments only when the "why" isn't obvious from the code itself
- Prioritize functionality over aesthetics in early iterations
- For any frontend work, follow the skill at https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md

### Security

- Never embed API keys, secrets, or credentials in client-side code, generated HTML/JS, or any file that gets committed to git
- Secrets must only exist in `.env` (gitignored), CI/CD secrets, or server-side code that is never served to browsers
- For client-side features needing keys, let the user provide their own key at runtime (e.g., localStorage input), never baked into source
- After any change involving secrets, grep your build output for known key prefixes (e.g., `AIzaSy`, `sk-`, `ghp_`, `AKIA`) to verify nothing leaked

### Validation (required after every change)

**Build:**
- Fix all build errors and warnings before proceeding
- Use a feature flag to toggle debug/verbose logging (on for testing, off for production. Check logs for unexpected errors or warnings.
- Run scripts from the project root so dependencies resolve correctly

**UI:**
- Walk through the full user flow start to finish and verify correct content, working interactions, and loading assets
- Test at mobile viewport (375×667) for overflow, clipped content, or unreachable buttons
- Confirm all branching paths (success, error, back, skip) work without dead ends and route changes reset stale state
- Confirm all data entries have required fields, and all URLs/assets resolve (no 404s, no broken redirects)
- Use Puppeteer or a browser automation tool to screenshot each distinct screen and check for broken layouts, missing assets, theming issues, or placeholder content

**Performance:**
- Batch API requests where possible and respect rate limits

### Writing Style

- Write directly. Use simple sentences. Be concise. Present data neatly
- No "This isn't X. It's Y." contrasts
- No self-answering rhetorical questions
- No em dashes. Use commas instead
- No three-part alliterative phrases
- No vague inspirational pivots
- No unsourced claims or unverified quotes
- Never ship LLM-generated factual claims without checking them against an authoritative source
- When uncertain, use hedging language rather than asserting something as settled