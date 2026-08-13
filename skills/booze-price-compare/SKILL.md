---
name: booze-price-compare
description: Compare Australian liquor prices across configured retailers and rank matching bottle sizes by price per litre. Use when the user wants to find or compare spirits, whiskey, whisky, bourbon, gin, rum, vodka, tequila, liqueur, wine, or other packaged liquor across Dan Murphy's, BWS, Bob's Bulk Booze, or additional configured retailers. Do not use for bars, restaurants, cocktails, or general product reviews.
---

# Liquor price comparison

Find current retail listings for the user's requested liquor products, normalize bottle/pack sizes and prices, and return one comparison table ranked by value.

The workflow is deliberately split into:

1. **Discovery** — use web/browser/search tools to find current product listings.
2. **Normalization** — convert each listing to the JSON record format below.
3. **Comparison** — run `scripts/compare_prices.py` to calculate price per litre and render Markdown.

This keeps retailer-specific weirdness out of the comparison logic and makes new retailers cheap to add.

## Inputs

Extract these from the user's request:

- Product family or exact product names.
- Optional sizes to include or exclude.
- Optional retailer subset.
- Whether member-only prices should be included.
- Optional postcode/location for stock or delivery checks.
- Optional delivery-cost comparison.

If the user gives images or previous prices, treat them as additional observations, not as current retailer prices unless they explicitly say to use them as-is.

## Retailer configuration

Read `references/retailers.json` before searching.

Only search configured retailer domains unless the user asks to add another retailer.

To add a retailer, add one object to `references/retailers.json`. Do not change the comparison script unless the normalized data model itself needs to change.

## Product matching rules

Match the requested product closely.

For example, if the request is for:

- `Jack Daniel's Old No. 7` — do not silently include Honey, Fire, Apple, Bonded, Single Barrel, or premixed cans.
- `Gentleman Jack` — do not merge it with Old No. 7 merely because both are Jack Daniel's.

Exclude unless explicitly requested:

- premixed/RTD cans or bottles,
- gift packs,
- glassware bundles,
- miniatures,
- multipacks containing different products,
- different expressions/variants,
- marketplace listings from unrelated sellers when the retailer is only acting as a marketplace host.

When a listing is ambiguous, retain it only if the page clearly shows the requested product name and package size.

## Discovery workflow

For each configured retailer:

1. Try the retailer's own search/category entry point from `references/retailers.json`.
2. If site search is poor, use an available web search tool with a domain restriction, for example:
   - `site:danmurphys.com.au "Gentleman Jack" 1L`
   - `site:bws.com.au "Jack Daniel's Old No. 7" 700mL`
3. Prefer a current product-detail page over a search-result snippet.
4. If a page is JavaScript-heavy, use available browser/rendered-page tooling rather than inventing values from raw HTML.
5. Use JSON-LD/structured data when present, but verify that its price and size correspond to the visible product.
6. Capture the source URL for every observation.
7. Record `observed_at` in ISO-8601 form with timezone if available.

Do not rely on search-engine snippets alone when the live retailer page is accessible. Snippets can be stale.

## Pricing rules

Capture every materially different price as a separate record:

- public price,
- member price,
- multi-buy price,
- case/bulk price.

Never replace a public price with a member price without labelling it.

For member prices:

- set `offer_type` to `member`,
- put the membership/program name in `offer_label` if shown,
- keep the public/non-member price as a separate record when available.

For multi-buy or bulk prices:

- capture the **total displayed price** in `price_aud`,
- capture the number of identical bottles in `pack_quantity`,
- capture the per-bottle volume in `size_ml`,
- put the deal wording in `offer_label`.

The comparison script divides the total price by total liquid volume, so `2 × 700mL for $100` is treated as 1.4L for $100.

Do not infer a multi-buy effective price unless the advertised purchase quantity is explicit.

## Availability and delivery

Set `availability` only to what the retailer actually establishes, such as:

- `in_stock`
- `out_of_stock`
- `delivery`
- `pickup`
- `unknown`

If stock depends on a postcode or store and none is supplied, use `unknown`.

Delivery is optional:

- set `delivery_aud` only when a definite delivery charge for the user's order is known,
- use `0` only when delivery is explicitly free for the relevant order,
- otherwise use `null`.

Do not guess delivery charges from generic policy pages.

By default, rank on **merchandise price per litre**, matching the normal comparison table. If the user explicitly wants delivered cost, pass `--include-delivery` to the comparison script. A per-order delivery fee is only directly comparable when evaluating one listed line item per order.

## Normalized record format

Write observations to a temporary JSON file as an array of objects:

```json
[
  {
    "retailer": "Dan Murphy's",
    "product": "Jack Daniel's Old No. 7 Tennessee Whiskey",
    "size_ml": 1000,
    "pack_quantity": 1,
    "price_aud": 74.90,
    "offer_type": "public",
    "offer_label": null,
    "availability": "unknown",
    "delivery_aud": null,
    "source_url": "https://example.invalid/product",
    "observed_at": "2026-08-12T22:00:00+10:00"
  }
]
```

Required fields: `retailer`, `product`, `size_ml`, `price_aud`, `source_url`.

Defaults: `pack_quantity=1`, `offer_type=public`, `offer_label=null`, `availability=unknown`, `delivery_aud=null`, `observed_at=null`.

`size_ml` is the volume of **one bottle/unit**, not the whole pack.

## Compare and render

Run:

```bash
python3 scripts/compare_prices.py /path/to/observations.json
```

For delivered-cost ranking:

```bash
python3 scripts/compare_prices.py --include-delivery /path/to/observations.json
```

For JSON output:

```bash
python3 scripts/compare_prices.py --format json /path/to/observations.json
```

## Final response

Return **one primary Markdown table**, sorted by ascending `$ / L`.

Use these columns unless a field would be entirely empty:

| Rank | Retailer | Product | Size | Price | $/L | Offer | Availability |
|---:|---|---|---:|---:|---:|---|---|

Rules:

- Format AUD prices to two decimals.
- Render bottle size naturally: `500mL`, `700mL`, `1L`, `1.136L`.
- Render packs as `2 × 700mL`.
- Label member/multi-buy/bulk prices clearly.
- Link the retailer name to the exact source page when supported.
- Do not claim that an unavailable/out-of-stock listing is the best purchasable deal.
- After the table, state the cheapest **currently purchasable** match and its `$ / L`.
- If member pricing changes the winner, say so.
- If no stock state was established, say the ranking is by listed price only.
- Mention whether delivery was included.
- Include the observation date/time for current web observations.

## Quality checks

Before returning the table:

1. Verify each row is actually the requested expression/variant.
2. Verify each bottle size and pack quantity.
3. Verify the displayed price belongs to that exact size/pack.
4. Verify member/multi-buy restrictions are labelled.
5. Recalculate obvious rows or run the script.
6. Remove duplicates for the same retailer/product/size/offer.
7. Prefer live product-page data over cached/search snippets.
8. Do not fabricate availability, delivery, or membership eligibility.
9. If a retailer could not be checked, say which retailer failed and why.

## Extending the skill

To add a retailer:

1. Add an entry to `references/retailers.json`.
2. Include canonical name, allowed domains, useful entry URLs, query hints, and retailer-specific notes.
3. Keep all collected listings in the normalized record format.
4. Run the same comparison script.

If a retailer requires deterministic parsing often enough to justify code, add a standalone adapter under `scripts/adapters/` that emits normalized JSON records. Do not bake retailer-specific parsing into `compare_prices.py`.
