# Reply categories

Read the person's own words (ignore the quoted original email below them). Pick exactly one.

| Category | When | Examples |
|---|---|---|
| `interested` | Wants to talk, says yes to a call, asks for a time, or asks to be contacted. | "Sounds good, next week works." · "Gerne, wann passt es Ihnen?" · "Ja tak, lad os tage en snak." |
| `question` | Asks something concrete (price, features, language, references, security, how it works) without clearly saying yes to a call. A question plus "let's talk" is `interested`. | "What does it cost for a city of 60,000?" · "Avez-vous des références en Belgique ?" |
| `referral` | Points to someone else ("talk to my colleague X", "I've forwarded this to…"). Note the new person's name/email in the summary. | "Neem contact op met An Peeters." |
| `not_interested` | Declines, already has a provider, no budget, wrong timing, without asking to stop emails. | "We've just signed with another provider." · "Not now, maybe next year." |
| `unsubscribe` | Asks to stop emailing / remove them / complains about the email. | "Please remove me from your list." · "Désinscrivez-moi." |
| `left_org` | The person no longer works there, mailbox closed, and no replacement named. (If a replacement is named → `referral`.) | "Ik werk hier niet meer." |
| `auto_reply` | Out of office, automatic acknowledgement, ticket systems, delivery notices. | "Abwesend bis 12.11." · "We have received your message (ticket #123)." |
| `unclear` | Anything you can't place confidently, or a mix that needs a human. | Sarcasm, legal threats, replies in an unexpected language you can't read, messages about something else. |

## MQL rule

Only `interested` and `question` make a Lead MQL (engaged replies). Opens and other categories never do.

## Language

Pass `--reply-lang` with the language the person wrote in, using one of: `en-US`, `en-GB`, `fr`, `nl`, `nl-BE`, `de`, `da` (or `en`/`nl` if you can't tell the variant). Any other language: leave it out and the plan falls back to the language of their campaign email.
