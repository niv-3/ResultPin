# Payvict address move: preflight review

Reviewed 14 November 2026. Preflight followed by an explicitly approved replacement deployment. No real payment or supplier purchase was performed.

## Verified
- Current web service srv-dbnllj3rjlhs7396hkig is live on paid 0.5c-512mb; deployed source 2b2af35.
- Existing address remains https://kobotap-preview.onrender.com.
- Public /health/ responds ok.
- PostgreSQL dpg-dbnll7jrjlhs7396gjjg-a is available in Oregon, version 18. It can be reused by a replacement web service in the same region. Do not create a new database or import a local development database.
- Hosted configuration inventory includes database, Django secret, Paystack keys, CheapDataHub key, VTpass keys/flags, Brevo key/sender and invited buyer controls. No linked environment group currently exists. Presence does not independently prove every credential is valid.
- Render settings derive allowed host and trusted CSRF origin from RENDER_EXTERNAL_HOSTNAME. Paystack checkout callback URLs are built from the request host.
- App manifest uses relative start URL and scope. Its branding is Payvict; installations and cookies on the old origin do not automatically migrate to a different origin.
- Google OAuth variables are absent from the visible service configuration and Google sign-in is not shown on the live login screen. If enabled later, add the new callback to Google first.
- Wallet funding credits use a unique reference and conditional pending-to-success update; webhook signatures and reference/currency/amount checks are present.
- 47 isolated regression tests passed across signup, idle sessions, mobile authentication, data catalogue, TV checkout, catalogue controls and blog SEO. No supplier purchase or real payment was executed.

## Must resolve before cutover
1. The actual new onrender hostname is only confirmed after Render assigns it. Service naming alone does not change the existing hostname. Do not promise payvict.onrender.com in advance.
2. render.yaml is stale: its service name is kobotap-preview and compute plan is free. Do not apply it unchanged or change its service name in a live Blueprint without reviewing whether Render will create a new billable resource. Preserve the existing database resource identity.
3. Database is still FREE and expires 7 December 2026. Paid web compute does not extend this. An application data backup and isolated restore were verified before the replacement deployment; arrange database continuation before expiry.
4. Copy current production settings safely into the replacement, retaining DATABASE_URL and SECRET_KEY and all payment/OTP/tester flags. Do not print or commit secrets. Do not upload the old seed catalogue unless specifically needed; an existing populated database must be reused.
5. Verify Paystack dashboard live callback and webhook addresses in a signed-in session. Then update to the assigned hostname and test signed webhook settlement, including an in-flight payment from the old host. Do not remove the old callback route before pending payments settle.
6. Verify whether VTpass/CheapDataHub have configured callback URLs or outbound IP restrictions. Update any old-host callback and recheck read-only authentication from the replacement. Do not enable a supplier purchase to test connectivity.
7. Verify any uploaded media storage. Current default MEDIA_ROOT is local filesystem and production URL routing does not serve it automatically. Reuse/copy any needed uploaded assets using persistent storage; repo static branding is rebuilt during deployment.
8. The old link cannot redirect after its service is stopped. Choose a functioning redirect/legacy webhook strategy before suspension. Avoid redirecting POST webhooks to HTML/login; route settlement requests to a working handler.
9. Before exposing both hosts, test shared-database concurrency for wallet debits and card fulfilment; existing unit tests are not proof of cross-instance race safety. Keep new checkout restricted until verified.
10. Compare account count, wallet ledger totals, transaction count and pending references before/after. These hosted data totals were not inspected in this review; never substitute the local DB.

## Cutover acceptance checks
- New hostname HTTPS + health + static assets; signup OTP/resend/password reset delivery.
- Existing phone/email sign-in, admin access, 15-minute inactivity timeout and password visibility.
- Existing user wallets/history show same records; no fresh registration required.
- Funding callback plus signed webhook credit exactly once; interrupted checkout recovers.
- Data/bill checkout simulations pass; any real spend requires explicit authorization.
- Old bookmarks and outstanding webhooks have a confirmed destination.
- Suspend old paid compute only after acceptance; retain database and rollback path. Confirm final billing/resource inventory.

## Paystack dashboard verification completed
- Signed-in live dashboard inspected on 14 November 2026.
- Live webhook is https://kobotap-preview.onrender.com/paystack_webhook/.
- Dashboard default live callback is blank; app code supplies checkout-specific callback URLs from the request host, so this is not inherently a fault.
- No live IP whitelist entries are displayed; the dashboard offers Add IP addresses.
- Test webhook still points to an older ngrok development URL; do not use it as the live destination.
- Live webhook was subsequently updated to the verified replacement hostname below and its saved value was checked after reload. No payments were initiated.

## Replacement deployed
- User explicitly approved copying the existing database/provider settings into a $7/month replacement service.
- New service: payvict-app, srv-dbs9l0bm8hqs73c58680; Oregon, 0.5c-512mb.
- Address: https://payvict-app.onrender.com; first deployment dep-dbs9l0jm8hqs73c587ag is Live on commit 2b2af35.
- All 16 configuration values were copied and checked for equality before submission. The existing database was reused; no seed fixture or new database was created. Deployment reported no pending migrations.
- Health endpoint returned ok; sign-in page and password visibility control rendered. Existing-account sign-in/wallet inspection awaits user sign-in in the in-app browser.
- Paystack live webhook now points to https://payvict-app.onrender.com/paystack_webhook/. Its saved value survived dashboard reload.
- A signed non-payment event returned HTTP 200, Ignored event, from the new endpoint. This verifies routing and signature authentication, not a real payment settlement.
- Settings show branch codex/kobotap-beta and Auto-Deploy On Commit. Existing render.yaml still describes the old Blueprint; do not apply it to the replacement.
- Existing-account sign-in was subsequently verified in the in-app browser. Wallet balance and previous top-up, data debit and cashback entries rendered; data provider selection, package catalogue and checkout rendered without submitting a purchase.
- Old web service srv-dbnllj3rjlhs7396hkig is now Suspended. Render explicitly displays: You are not billed for suspended services. Database was retained, not suspended or deleted. New service continued serving authenticated pages afterward.
- The old kobotap-preview address is retired, not redirected. Share the new address and reinstall/update any old-origin mobile shortcut. No promise of automatic redirection is made.

## Backup evidence
- Private ignored backup: tmp/private-backups/payvict-hosted-20261114T172057Z.json.
- Logical Django application data export, excluding browser sessions and generated content-type/permission metadata; not a PostgreSQL server/schema dump.
- Read-only repeatable-read snapshot: 220 objects, 6 users, 22 wallet records. Successful credits 3124.42 NGN, debits 2329.00 NGN, net 795.42 NGN.
- SHA256: 566ddea9bd4883ae7e5845faf4c943aef61d89ec7517c68321055e15e9be740b.
- Restored into disposable in-memory SQLite after migrations and fixture-seed cleanup; user count, wallet count and credit/debit totals matched.
- Snapshot had no pending transaction records. One uploaded file field references services/providers/dstv.png; persistence still needs review before retiring old storage.
- Scratch files and credentials are excluded by tmp/ in .gitignore. Never commit or share backups.
