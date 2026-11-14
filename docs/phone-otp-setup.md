# Phone verification setup

Phone OTP support is prepared using Termii transactional SMS. Email remains required for receipts and fallback verification. This is signup verification, not an SMS on every password login.

## Required account setup

1. Create or sign in to the Termii account. Confirm the current Nigeria transactional SMS rate in its dashboard before funding.
2. Obtain approval for the sender name and the transactional/DND route. Do not assume a submitted sender name is approved.
3. Copy the account's API key and account-specific base URL privately into the Render service environment. Never paste the key in chat or Git.
4. Configure `TERMII_API_KEY`, `TERMII_SENDER_ID`, `TERMII_BASE_URL`, and `SMS_OTP_HOURLY_LIMIT` (starts at 20 across the app).
5. After deploying and applying migrations, enable `SMS_OTP_ENABLED=true`. Before enabling, SMS is not offered and existing email signup continues.
6. With explicit permission for the recipient and message cost, send one real signup code and verify receipt, correct/incorrect/expired code handling and email fallback. Provider acceptance alone does not prove delivery.

## Behaviour and limits

- SMS is selected by default when configured; customer can select email instead.
- Nigerian phone numbers are normalized to international format for delivery.
- Code expires after 10 minutes; existing five-attempt/five-resend limits remain.
- Resends have a one-minute cooldown. Email fallback sends a new code and replaces the earlier SMS code after successful dispatch.
- Shared database limits allow at most three SMS dispatch attempts per number per hour and 20 total per hour by default, including failed provider attempts. Numbers are stored as keyed hashes in the limiter.
- Codes, API keys and provider responses must never be logged.
- SMS account keys and API endpoint are server-side only. Endpoint must be HTTPS on a Termii subdomain.
- Existing customers can still sign in with phone number or email and password.
- Email fallback verifies access to the email; it must never be treated as proof of phone ownership for future recovery or financial authorization.

## Sources

- https://developers.termii.com/ (account-specific API base URL)
- https://termii.com/ (transactional `/api/sms/send` example)
- https://termii.com/pricing (current rate card must be confirmed with provider)
