# Samurai Sales Portal Connector (Business Central extension)

Business Central's standard API cannot assign lot numbers, so a sales order of lot-tracked items cannot be posted from
the portal with it ("You must assign a lot number for item …"). This small extension adds that:

| Action | What it does |
| --- | --- |
| `assignLotsAndPost` | Assigns lots to the order lines that need them, then posts the order (Ship and Invoice) |
| `assignLots` | Only assigns the lots (to check them on the order before posting) |

```
POST https://api.businesscentral.dynamics.com/v2.0/{tenant}/{environment}/api/samuraiFoods/portal/v1.0/companies({companyId})/portalSalesOrders({orderId})/Microsoft.NAV.assignLotsAndPost
```

`{orderId}` is the order's id in the standard API (`salesOrders`). The portal calls this by itself when the extension
is installed; without it, the portal uses the standard Ship and Invoice action.

## How lots are chosen

For each item line with a Qty. to Ship whose item tracking code has *Lot Specific Tracking* or *Lot Sales Outbound
Tracking*, and that has no item tracking yet:

1. open stock of the item at the line's location and variant, by lot (Item Ledger Entries, Remaining Quantity);
2. less what other documents already claim of each lot (outbound item tracking and reservations);
3. earliest expiry date first (FEFO); lots without an expiry date last;
4. as many lots as needed for the Qty. to Ship (Base); if the stock is short, nothing is posted and the error says by how much.

Lines whose lots were assigned by hand are left as they are.

## Install

1. In VS Code with the AL Language extension, open this folder, run **AL: Download Symbols** against the
   Samurai Foods environment (AequmTest first), then **AL: Package** (Ctrl+Shift+B).
2. Business Central → **Extension Management** → **Upload Extension** → choose the `.app` file → Deploy.
3. **Microsoft Entra Applications** → the portal's app → **User Permission Sets**: add `SF PORTAL API`
   (next to `D365 BUS FULL ACCESS`).

Object IDs 50120–50129 are used. If they clash with another extension, change them in `app.json` and the three `.al`
files. `platform`/`application` 26.0 work on later versions too.

## Check

In the portal, make an invoice for an order of a lot-tracked item. The invoice should show **In Dynamics** with the
posted invoice number, and the Dynamics sync log "order lots assigned (FEFO) and posted in Dynamics". In Business
Central, the Posted Sales Invoice → line → Item Tracking Lines shows the lots used.
