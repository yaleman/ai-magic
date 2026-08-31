---
name: notify-user
description: Use when work is blocked on the user's input, approval, or another time-sensitive response and the user needs timely attention in the current session.
---

# Notify User

## Overview
Use a macOS attention prompt to get the user's attention when progress is blocked on them or a reply is urgent.

Core principle: notify for attention, not for chatter.

## When to Use
- Work cannot continue until the user answers a question.
- A prompt approval or decision is needed to avoid waiting.
- The user asked for something time-sensitive and a response is now required.

## When Not to Use
- Routine progress updates
- Normal task completion
- Non-urgent follow-up questions
- Repeating the same notification for the same blocker without new information

## Attention Format
- Title: `Codex Needs Attention`
- Body: one short sentence with the blocker and the action needed
- Sound: beep before showing the dialog

Keep the message direct. Good pattern: `Blocked on your input: approve the BLE address to continue.`

## Command
Use this exact pattern:

```bash
/usr/bin/osascript -e 'beep 2' -e 'display dialog "Blocked on your input: approve the BLE address to continue." with title "Codex Needs Attention" buttons {"OK"} default button "OK"'
```

Use `display notification` only as an optional fallback on Macs where Notification Center banners are known to appear reliably.

After triggering the prompt, ask the matching blocking question in the chat.

## Examples
Notify:
- Waiting on the user to choose between two implementation options
- Waiting on approval before making a risky change
- Waiting on credentials, access, or a device that the user must provide now

Do not notify:
- Reporting that exploration is in progress
- Reporting that tests passed
- Asking a low-priority cleanup question that can wait in chat

## Common Mistakes
- Sending notifications for every milestone instead of only blocked or urgent cases
- Using a vague body like `Please respond` instead of naming the blocker
- Sending multiple notifications for the same unresolved blocker without a material change
- Relying on Notification Center banners when they are suppressed by Focus mode or local notification settings
