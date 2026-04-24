#!/usr/bin/env bash
# Journal prompt templates.

JOURNAL_SYSTEM_PROMPT="You are a journal writer. Your only job is to produce clean markdown journal entries about coding sessions. Never use tools, never ask questions, never ask for permissions. Output ONLY the markdown, starting directly with the # title. Be concise and technical."

# build_journal_prompt <repo> <branch> <hash> <author> <commit_msg> <diff_stat> <diff>
build_journal_prompt() {
  local repo="$1"
  local branch="$2"
  local hash="$3"
  local author="$4"
  local commit_msg="$5"
  local diff_stat="$6"
  local diff="$7"
  local date_human
  date_human="$(date '+%Y-%m-%d %H:%M')"

  cat <<PROMPT
Analyze this git commit and write a structured markdown journal entry. Output ONLY the markdown, starting directly with the # title.

Required sections (use exactly these headings):
# <descriptive title based on commit message and changes>
**Date:** ${date_human}
**Repo:** ${repo} | **Branch:** ${branch} | **Commit:** ${hash}

## TL;DR
One or two sentences summarising what changed and why.

## What Was Worked On
Bullet list of topics/features/modules touched.

## What Was Accomplished
Concrete bullet list — file names, function names, specific outcomes.

## Files Changed
Table: | File | Change |

## Key Decisions
Decisions made and reasoning (infer from diff if not in commit message).

## Problems & Solutions
Any notable issues visible in the diff and how they were resolved.

## Action Items
- [ ] follow-up tasks implied by the diff or commit message

## Tags
\`kebab-case-tags\` relevant to the tech and domain

---

COMMIT INFO:
Author: ${author}
Message: ${commit_msg}

DIFF STATS:
${diff_stat}

DIFF:
${diff}
PROMPT
}
