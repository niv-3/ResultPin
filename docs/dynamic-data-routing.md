# Multi-supplier data routing

Implemented 15 November 2026. New routing is staged OFF (`DYNAMIC_DATA_ROUTING=False`).
Existing CheapDataHub checkout remains the live route until account verification is complete.
No supplier account was funded and no real purchase was made during implementation.

## How it works

- Customer products and selling prices remain on ServicePlan. Importing supplier costs never reprices them.
- SupplierQuote maps one customer product to each supplier's exact bundle ID and network ID.
  Approve only after checking network, size, validity, data type, restrictions and included bonuses.
  A cheaper 1GB daily bundle is not interchangeable with 1GB weekly or monthly.
- DataSupplier controls credentials adapter, enablement, funding readiness, funding fee reserve,
  per-purchase fees and temporary pause. New profiles default disabled and unfunded.
- Credentials live in environment variables, never admin database fields or source control.
- The router excludes unapproved, unavailable, future-dated and older-than-24-hour quotes,
  inactive vendors, disabled/unfunded profiles, missing credentials and unsupported adapters.
- Rank eligible offers by cost plus supplier funding reserve and purchase fee; priority breaks ties.
  Keep the existing minimum estimated contribution of NGN30 after displayed cashback,
  payment fees and supplier funding fees. This excludes hosting, taxes and other overhead.
- Snapshot supplier, adapter, bundle ID, network ID, cost, funding-adjusted cost and promised cashback
  on each wallet/card order. Changing a product's supplier or prices cannot reroute a paid order.
- Revalidate the pinned offer before sending. Removed, disabled, stale or more expensive offers
  are rejected before vending and payment is refunded through the existing refund path.
- Never automatically retry or switch suppliers after sending a purchase. Timeouts, malformed
  responses and unknown statuses remain pending; no cashback or automatic refund on uncertainty.
  Temporarily pause that supplier for two minutes for new orders. A different *new* order may select
  another eligible supplier. Do not encourage the buyer to reorder an uncertain purchase.
- Wallet debits lock the user row to serialize concurrent purchases.

## Supported integrations and limits

- CheapDataHub: existing purchase API, dynamic route adapter and mapped quote refresh.
- ClubKonnect/Nellobyte: documented purchase and status-query adapters, account catalogue refresh.
  Prices use the upfront PRODUCT_AMOUNT conservatively; do not subtract unverified commissions.
- Bilalsadasub: disabled placeholder only. Its documentation says public discovery needs no token,
  but actual MTN/Airtel/Glo GET requests returned HTTP403 Unauthorized/Token Not Found on 15 November.
  Registration also reported Phone Number already Taken. Do not enable it or invent plan mappings.
- Ringo and VTU Agent are research candidates, not integrated or enabled suppliers.
- Airtime, electricity, cable and education retain their existing routes. Do not apply data bundle
  selection rules to them without separate service-specific verification.
- Funding readiness is an operator confirmation, not a real-time supplier balance feed.
  No balance verification or real supplier delivery has been claimed without account access.

## Activation checklist for the operator

1. Create/verify the supplier account and confirm its API tier, funding fees, refund policy and
   account prices. Get credentials privately. No need to paste tokens in chat.
2. Run `python manage.py migrate`, then `python manage.py setup_data_suppliers`.
   This creates only disabled profiles; it does not fund, activate, or purchase anything.
3. Add NELLOBYTE_USER_ID and NELLOBYTE_API_KEY to the host environment. For CheapDataHub use
   the existing CHEAPDATAHUB_API_KEY. Keep the global switch OFF during setup.
4. In admin, map Supplier quotes to existing customer plans, with supplier-specific IDs and labels.
   For example, Nellobyte's public catalogue labels product 4 on network 01 as
   `1GB - Weekly (SME Data)`; verify it in the actual account before approval.
5. Refresh each configured supplier's quotes:
   `python manage.py sync_supplier_quotes --supplier cheapdata`
   `python manage.py sync_supplier_quotes --supplier nellobyte`
   Nellobyte label/network changes remove approval; missing products become unavailable.
   Re-approve only after review. Retail prices remain unchanged.
6. Set vendor active, supplier enabled/funded only after credentials and funds are confirmed.
   Replace the conservative default 3% supplier funding reserve only with verified actual charges.
7. Run `python manage.py data_routes` for a read-only routing preview. Review wallet and card
   economics before enabling DYNAMIC_DATA_ROUTING=True on the host.
8. Schedule quote refreshes (e.g. every 15 minutes) and
   `python manage.py reconcile_data_orders` (e.g. every 2 minutes) in an existing secure scheduler.
   No new paid hosting service or unattended scheduler was created by this change.
   The 24-hour freshness limit fails closed if refreshes stop.
9. Reconciliation only queries old uncertain Nellobyte orders and settles confirmed successes
   once, including cashback. Non-success/unknown results remain for operator review. It never
   purchases or retries. CheapDataHub uncertain orders require its dashboard/support until a
   documented authenticated query adapter is available. Do not manually refund possible deliveries.

Turning the global switch OFF restores legacy selection for new purchases; already-paid orders
with a supplier snapshot continue using their original adapter. Disabling/removing credentials
before these finish prevents delivery and needs payment/refund review.

## Sources

- https://www.clubkonnect.com/apidocs.asp
- https://www.clubkonnect.com/APIParaGetDataBundleV1
- https://www.nellobytesystems.com/APIDatabundlePlansV3.asp?UserID=
- https://www.nellobytesystems.com/APICommissionRate.asp?section=data
- https://app.bilalsadasub.com/documentation/home

All automated checkout tests use mocked supplier/payment responses. They validate routing and
ledger behaviour, not live account access, network delivery speed or supplier reliability.
