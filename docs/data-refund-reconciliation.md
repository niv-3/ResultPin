# Data delivery and refunds

CheapDataHub's authenticated transaction history returns `category`, `completed`,
`recipient`, `amount`, `item`, `timein` and `tx_ref`. Verified against its read-only
API on 19 November 2026. Documentation: https://www.cheapdatahub.ng/api/docs/

Wallet history checks pending data orders in the background, without repeating a
purchase. Checks are throttled to once per customer every 30 seconds, with six
checks per wallet-page visit. Background checks do not extend the idle session.
Orders younger than two minutes are left pending to allow supplier processing.

Only `Failed - Refunded` with `completed=false` permits an automatic wallet
refund. `Successful` with `completed=true` settles success and cashback once.
The full retail debit is refunded, not the supplier's lower cost.

An order must match recipient, cost, bundle size/network and timestamp (within
60 seconds). When a supplier reference was returned it must also match exactly.
Multiple possible supplier or local matches require manual review. Unmatched,
malformed, incomplete and unavailable history never proves failure. Snapshot
costs and cashback are retained on new wallet orders; legacy orders use their
current plan cost, so a changed cost can require manual review.

Refunds and status changes are atomic, using the original `REFUND-<reference>`
ledger key. Existing manual refunds are respected. Reconciliation does not
touch card-payment orders or send new vending requests.

Operators can also run `python manage.py reconcile_data_orders` with production
settings through an approved scheduler. No scheduler is provisioned by this
change. Wallet-page checks run without one; users who never return to the wallet
need scheduled reconciliation or operator review.

Gunicorn uses four request threads and a 60-second worker timeout. Data purchase
calls use a 3-second connection timeout and 15-second read timeout. This reduces
blocking and the old worker/supplier timeout collision; it does not establish
the root cause of the observed Render 502 or guarantee no future gateway errors.
