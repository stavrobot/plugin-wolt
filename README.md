# Wolt plugin

Browse [Wolt](https://wolt.com) from Stavrobot: search for restaurants near you,
read their menus, check whether they are open and what delivery costs, build a
basket, ask for a live price, and look up your recent orders.

**This plugin cannot place an order and cannot spend your money.** It stops one
step before buying. It will never submit an order and never charge your card.

It is not read only, though. It changes the basket you see in the Wolt app.
There is one basket per restaurant, and every change replaces that basket
completely. If you are building an order in the app at the same time, this
plugin can overwrite it.

Two limits are worth knowing before you start.

The plugin cannot remove the last item from a basket. To delete a whole basket,
use `empty_basket`.

A basket holds one line per menu item, so the same dish cannot appear twice with
different options. Ordering two burgers, one with cheese and one without, is not
possible here. Use the Wolt app for that.

It is built on [woltapi](https://github.com/skorokithakis/woltapi), an unofficial
library. Wolt does not support or endorse it.

## Tools

### search_restaurants

Search for restaurants near a location.

- `query` — what to search for, for example "pizza" or a restaurant name.
- `latitude`, `longitude` — optional. Defaults to your configured location.

Returns up to 10 restaurants with their names and slugs. The slug is what the
other tools take.

### get_restaurant_info

Details for one restaurant: address, opening hours for the week, whether it is
open now, delivery estimate and fee, minimum order, rating, phone, and its Wolt
page.

- `slug` — from `search_restaurants`.
- `latitude`, `longitude` — optional. The delivery location, which affects the
  estimate and fee. Defaults to your configured location.

### get_menu

A restaurant's menu, with names, prices, and descriptions. Each item also
carries its ID, whether it has options to choose, and whether it is restricted
or alcoholic. The item ID is what the basket tools take.

- `slug` — from `search_restaurants`.
- `filter` — optional. Only return items whose name contains this text.
- `limit` — optional, defaults to 30. Large menus run to hundreds of items, so
  the reply also reports how many matched in total.

### get_item_options

The choices for one menu item, such as size or extras. Option data is large, so
it is a separate tool rather than part of the menu.

- `slug` — from `search_restaurants`.
- `item_id` — from `get_menu`.

Each configuration reports its ID, its name, whether it is required, how many
values you may choose, and the values with their IDs and extra prices. The
configuration ID and the value IDs are what `update_basket` takes.

Some configurations are marked unsupported, with a reason. Wolt allows option
types this plugin cannot save, so they are shown rather than hidden, to avoid
choosing one and then failing.

### view_basket

Your saved Wolt baskets. This reads what the Wolt app shows.

- `slug` — optional. With it, you get the full basket for that restaurant, with
  items, chosen options, line prices and the total, all priced against the menu
  as it is now. Without it, you get a quick summary of every basket: restaurant,
  item count, and whether it is currently available.

If a restaurant has changed its menu since you saved a basket, the basket can no
longer be read. The tool says which item caused it. Use `empty_basket` to
recover.

### update_basket

Change one restaurant's basket. **This replaces the basket you see in the Wolt
app.** It never orders anything and never charges your card.

- `slug` — from `search_restaurants`.
- `action` — one of `add`, `set_count`, `set_options`, `remove`.
- `item_id` — from `get_menu`. Needed by every action.
- `count` — needed by `add` and `set_count`.
- `option_selections` — needed by `set_options`, optional for `add`. Uses the
  IDs from `get_item_options`.

`set_options` replaces the item's whole option selection. An empty list clears
every option, and any configuration you leave out is cleared too.

`remove` refuses to take out the last item, so deleting a whole basket is always
an explicit choice through `empty_basket`. Adding an item that is already in the
basket also refuses, and tells you its current count and options, because one
item ID means one basket line. Use `set_count` or `set_options` to change it.

Restricted and alcoholic items are refused.

The result is the basket after the change, so you can see what happened without
asking again.

### empty_basket

Permanently delete the saved Wolt basket for one restaurant. This cannot be
recovered. It never orders anything and never charges your card.

- `slug` — from `search_restaurants`.

If the restaurant has no saved basket, the result says that nothing was deleted.

### list_delivery_addresses

Your saved Wolt delivery addresses, with their IDs, so you can pick one for a
quote. Takes no parameters.

This exists because Wolt does not mark any saved address as the default. When
`get_quote` is not told which address to use, it takes the first one, so it
always reports which address it used.

### list_orders

Your recent orders: restaurant, time, items, and the order ID.

- `limit` — optional, defaults to 5.

At most 10 items are listed per order, with a count of the rest.

### get_order_status

The current status and charges for one order. Use this to check on a delivery
that is on its way.

- `purchase_id` — from `list_orders`.

### get_quote

A live price for a basket you have already built. **This buys nothing and
charges nothing.** It is the last step this plugin can take.

- `slug` — from `search_restaurants`. The restaurant must already have a basket.
- `delivery_target_id` — optional, from `list_delivery_addresses`. Without it,
  the first saved address is used, and the result says which one.
- `courier_tip` — optional, in cents. Defaults to zero.

Returns what Wolt would charge: the payable amount, the fee breakdown, the tip,
the address and card it priced against, whether Wolt would allow the purchase,
and whether age verification would be needed.

This is the only tool that touches your saved cards, and it only reads them to
price the order. It picks the card Wolt marks as the default, then the selected
one, then the only one. If it cannot decide, it lists your cards and stops.

Asking for a price does create a checkout record on Wolt's side. It is not an
order, and no money moves.

## Installation

Tell Stavrobot:

> Install the plugin at https://github.com/stavrobot/plugin-wolt

## Configuration

Three values are needed.

**`refresh_token`** — this is how the plugin signs in as you. To find it:

1. Sign in to Wolt in your browser.
2. Open Developer Tools and go to **Application > Cookies**.
3. Copy the value of the `__wrtoken` cookie, without the surrounding quotes.

This is not the `Bearer` token from an Authorization header, and not the refresh
token used by Wolt's support chat widget. Treat it like a password: anyone
holding it can read your Wolt account.

The token is stored in `config.json` alongside the plugin. Wolt sometimes issues
a replacement, which the plugin saves to `state.json` so you do not have to
repeat the steps above. Neither file is committed. If the plugin ever reports
that the token is expired or revoked, fetch a new `__wrtoken` and set it again.

**`latitude`** and **`longitude`** — your default location, used when a tool is
called without coordinates.

## License

GNU Affero General Public License, version 3. See [LICENSE](LICENSE).
