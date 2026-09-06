# Wolt plugin

Browse [Wolt](https://wolt.com) from Stavrobot: search for restaurants near you,
read their menus, check whether they are open and what delivery costs, and look
up your recent orders.

This plugin is read only. It cannot place an order or spend your money.

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

A restaurant's menu, with names, prices, and descriptions.

- `slug` — from `search_restaurants`.
- `filter` — optional. Only return items whose name contains this text.
- `limit` — optional, defaults to 30. Large menus run to hundreds of items, so
  the reply also reports how many matched in total.

### list_orders

Your recent orders: restaurant, time, items, and the order ID.

- `limit` — optional, defaults to 5.

At most 10 items are listed per order, with a count of the rest.

### get_order_status

The current status and charges for one order. Use this to check on a delivery
that is on its way.

- `purchase_id` — from `list_orders`.

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
