# Claude Cowork Scheduled Task Guidance

Use this file to create a Claude Cowork scheduled task for the daily newsletter.
Cowork should act as the scheduler and operator. The Python pipeline remains the
source of truth for fetching, ranking, summarizing, rendering, and archiving.

Official Cowork references:

- <https://support.claude.com/en/articles/13854387-schedule-recurring-tasks-in-claude-cowork>
- <https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork>

## Platform Fit

Cowork scheduled tasks support:

- A saved task name, description, prompt, cadence, optional model, and optional working folder.
- Hourly, daily, weekly, weekday, manual, and on-demand runs from the Scheduled page.
- The same Cowork capabilities as a normal task, including local file access, shell commands, web research, connected tools, skills, and installed plugins.
- Connector steps such as reading a Gmail digest or sending an iMessage, when those connectors are configured in Claude Desktop.
- Review of past and upcoming runs from the Scheduled page.

Cowork scheduled tasks constrain this newsletter automation:

- Claude Desktop must be open and the computer must be awake at the scheduled time.
- If the app is closed or the computer is asleep, Cowork can skip the run and run it once the app is available again.
- Each run is a separate Cowork session, so the prompt and files must contain all durable instructions.
- The task should avoid asking daily follow-up questions. All routine choices must be pre-decided in the prompt.
- Cowork can make real local file changes in the selected folder. It should not delete files or change secrets.
- Network access, plugins, and connectors depend on the permissions configured in Claude Desktop and the organization.
- Gmail and iMessage actions depend on connector authorization. The task should report connector failures without blocking the newsletter build.

## Scheduled Task Fields

Use these values in Cowork's Scheduled task modal.

| Field | Value |
|---|---|
| Task name | Daily Midtown Briefing |
| Description | Build the daily newsletter, update the static site archive, read the YouTube email digest, and text a short result. |
| Folder | `/Users/evekazarian/Documents/Coding Projects/daily-newsletter` |
| Frequency | Daily |
| Time | 6:00 AM America/New_York |
| Model | Use the default Cowork model unless a more capable model is needed for debugging failures. |
| Permission mode | Start with ask-before-acting for setup. Use act-without-asking only after a clean manual run. |

## Automation Map

The scheduled task should treat each newsletter concern as a bounded step.

| Step | Automation piece | Repo source | Cowork role |
|---|---|---|---|
| Preflight | Confirm folder, environment file, dependencies, and network availability. | `.env.example`, `requirements.txt` | Check setup without printing secrets. Install dependencies only if the environment is missing them and permission allows it. |
| Fetch weather | Get NYC weather from the National Weather Service. | `src/weather.py` | Let the script fetch it. Report only if the section fails or is empty. |
| Fetch health | Get NYC respiratory illness status. | `src/health.py` | Let the script fetch it. Report failures as warnings, not blockers. |
| Fetch events | Get nearby NYC events. | `src/events.py` | Let the script fetch it. Do not manually curate events unless the script fails. |
| Fetch top news | Select broad top news using source scoring and deduplication. | `src/news.py`, `src/newsletter.py` | Let the deterministic ranking run. Do not replace it with ad hoc Cowork research. |
| Fetch YouTube | Collect recent videos and transcripts when available. | `src/youtube.py` | Let the script fetch it. Keep videos without transcripts if the script keeps them. |
| Read YouTube email digest | Find the newest YouTube digest email and extract notable links. | Gmail connector | Do not mutate the inbox. Use this as an iMessage supplement unless the repo is extended to ingest a saved digest file. |
| Fetch AI security | Collect papers and AI security news, deduplicate by title and topic. | `src/papers.py`, `src/ai_news.py`, `src/newsletter.py` | Let the script merge and rank the list. |
| Editorial enhancement | Use Groq summaries when `GROQ_API_KEY` is configured, otherwise use built-in fallbacks. | `src/llm_summarizer.py` | Do not paste provider responses or secrets into the task report. |
| Render | Render the email HTML and static site files. | `templates/newsletter.html`, `src/site_generator.py` | Run the script from the repo root so relative paths resolve. |
| Verify | Check today's archive, post page, email HTML, index, feed, and local output. | `site/posts/`, `site/index.html`, `site/feed.xml`, `output.html` | Confirm files exist and are non-empty. Summarize counts and warnings. |
| iMessage report | Send a short, clear completion text. | iMessage connector | Include section counts, YouTube digest highlights, and warnings. |
| Report | Produce a concise Cowork task result. | Generated files, digest extraction, and logs | Include status, files changed, section counts, connector status, and any blockers. |

## Scheduled Task Prompt

Paste this prompt into the Cowork scheduled task.

```text
You are running the scheduled daily automation for The Midtown Briefing.

Work in this folder:
/Users/evekazarian/Documents/Coding Projects/daily-newsletter

Goal:
Build today's daily newsletter, update the static site archive, read the latest YouTube email digest, send me a short iMessage summary, and leave a concise run report in this Cowork session.

Operating rules:
- Work autonomously during scheduled runs.
- Do not ask routine follow-up questions. If a required setup detail is missing, make the safest local assumption and report it.
- Do not print, copy, summarize, or expose values from .env or any secret-bearing file.
- Do not delete files.
- Do not create or modify a separate cron, launchd, or external scheduler. Cowork is the scheduler.
- Do not rewrite newsletter content manually unless the Python pipeline fails in a way that can be fixed locally.
- Do not mark emails as read, archive, delete, label, forward, or reply to them.
- Keep changes inside the selected project folder.

Preflight:
1. Confirm the working directory is /Users/evekazarian/Documents/Coding Projects/daily-newsletter.
2. Confirm .env exists. Do not display its contents.
3. Confirm requirements.txt exists.
4. Confirm Python can import the installed dependencies needed by src/newsletter.py.
5. If dependencies are missing, install from requirements.txt only if the environment and permissions allow it. Otherwise report the exact missing package names.

YouTube email digest:
1. Use the Gmail connector, if available, to find the newest YouTube-related digest email received since the previous scheduled run or within the last 36 hours.
2. Search for messages with YouTube links and digest-like subjects or senders. Use terms such as YouTube, youtu.be, digest, newsletter, recommendations, subscriptions, videos, and watched.
3. If multiple messages match, choose the newest message with the most relevant YouTube links.
4. Extract up to 5 notable items:
   - title
   - channel or source, when available
   - YouTube URL
   - one short reason it looks worth watching
5. Deduplicate against obvious repeats by URL, video ID, and title.
6. If no digest is found or the Gmail connector is unavailable, continue the newsletter build and report this as a warning.

Run newsletter build:
1. From the repo root, run:
   python3 src/newsletter.py
2. Let the repo's Python code fetch and choose all content:
   - NYC weather
   - NYC respiratory health status
   - NYC events
   - top general news
   - recent YouTube videos
   - AI security papers
   - AI security news
   - optional Groq editorial summaries when GROQ_API_KEY is configured
3. Do not replace these deterministic repo steps with manual web research.

Verify:
1. Determine today's date in YYYY-MM-DD using America/New_York.
2. Confirm these files exist and are non-empty:
   - output.html
   - site/index.html
   - site/feed.xml
   - site/posts/YYYY-MM-DD.json
   - site/posts/YYYY-MM-DD.html
   - site/posts/YYYY-MM-DD.email.html
3. Read the generated JSON and count:
   - news items
   - YouTube items
   - AI security items
   - events
   - whether weather is present
   - whether health status is present
4. Count the YouTube digest items extracted from email.
5. Check the command output for errors and warnings. Treat missing optional API keys as warnings only if the code used fallbacks.

iMessage:
After verification, send exactly one iMessage using the iMessage connector.

Use this format:

🌞 Midtown Briefing is ready

🗞️ News: {count}
▶️ YouTube: {count}
📬 YouTube digest: {count}
🤖 AI security: {count}
🎟️ Events: {count}
🌤️ Weather: {short weather status}
🩺 Health: {short health status}

📺 From email:
{up to 3 short digest highlights, each as "• Title - why it looks good"}
{if no digest items: "No digest found today."}

✅ Site updated:
{public site URL if SITE_URL is known, otherwise "site/index.html"}

⚠️ Notes:
{only include real warnings; otherwise say "No issues."}

Keep the iMessage cute, concise, and easy to scan. Do not include logs, stack traces, secrets, or long file paths unless the run failed.

Report:
Return a concise report with:
- Status: success, success with warnings, or failed
- Files generated or updated
- Section counts
- YouTube digest count and connector status
- Warnings or blockers
- The next manual action, only if one is required

Do not commit, push, send email, post to Slack, or publish through another connector unless a separate task instruction explicitly asks for that action. The only connector-send action allowed in this task is the final iMessage.
```

## First-Run Setup

Before enabling an unattended daily run:

1. Open Claude Desktop and start a Cowork task in this folder.
2. Run the scheduled task prompt manually once.
3. Approve dependency installation only if packages are missing.
4. Confirm `.env` contains any optional keys you want the pipeline to use:
   - `GROQ_API_KEY` for editorial summaries
   - `SITE_URL` for RSS links and generated site URLs
   - `VERBOSE_LOGGING=1` only when debugging
5. Confirm the Gmail connector can read the YouTube digest without mutating email state.
6. Confirm the iMessage connector can send one test message to you.
7. Open `output.html` or `site/index.html` locally and confirm the newsletter renders.
8. Switch the scheduled task to daily cadence only after the manual run succeeds.

## Failure Handling

Use this response policy for scheduled runs.

| Condition | Scheduled task behavior |
|---|---|
| Missing `.env` | Stop after preflight and report the missing file. Do not invent keys. |
| Missing dependency | Install from `requirements.txt` if allowed. If not allowed, report missing packages. |
| External feed failure | Continue if the script produced fallback output. Report the affected section. |
| Optional API key missing | Continue with fallback behavior. Report the disabled optional enhancement. |
| Gmail connector unavailable | Continue the newsletter build. Send the iMessage without digest highlights and report the connector issue. |
| iMessage connector unavailable | Complete the newsletter build and leave the report in Cowork. Mark the run success with warnings if the build passed. |
| Generated file missing | Mark the run failed and include the missing path. |
| Secret detected in output | Stop, report the file path, and do not publish or commit. |

## Full Digest Integration

The prompt above uses the YouTube email digest as an iMessage supplement.
To include those email items inside the generated newsletter page, extend the
Python pipeline first. A safe pattern is:

1. Have Cowork write extracted digest items to a local JSON file such as `data/youtube_email_digest.json`.
2. Add code in `src/youtube.py` to load that file, normalize title/channel/link/summary fields, and deduplicate it against RSS-derived videos.
3. Let `src/newsletter.py` render those normalized items through the existing YouTube section.

Do not ask Cowork to hand-edit generated HTML every morning. That would make the scheduled task brittle and hard to verify.

## Optional Publishing Task

Keep publishing separate from the daily build unless you explicitly want Cowork to push changes.
If publishing is added later, create a second scheduled task with its own prompt and approvals.
That task can inspect `git status`, review generated files, commit the static site changes, and push to the configured remote.
