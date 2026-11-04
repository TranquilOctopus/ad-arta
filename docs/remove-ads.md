# Removing ads from a 2020 Frame TV

Three levels, from gentle to strongest. Menu names differ slightly by
firmware and region; on 2020 models most of these live under
**Settings > Support > Terms & Policy** and **Settings > General**.

## Level 1: TV settings (5 minutes, nothing breaks)

| Setting | Path | Set to |
|---|---|---|
| Interest-Based Advertisements | Settings > Support > Terms & Policy | Off |
| Viewing Information Services (tracks what's on screen, including the Apple TV) | Settings > Support > Terms & Policy | Off |
| Voice Recognition Services | Settings > Support > Terms & Policy | Off |
| Autorun Smart Hub (home bar with ad tiles pops up at power-on) | Settings > General > Smart Features | Off |
| Autorun Last App | Settings > General > Smart Features | Off |
| Samsung TV Plus (ad-supported channels) | Settings > General > Smart Features, or the Samsung TV Plus app's own settings | Off / don't autostart |

Also in **Terms & Policy**, look for "Privacy Choices" or "Privacy Notice"
and decline any optional marketing or data-sharing items.

Since the Apple TV handles your apps, you'll rarely see the Samsung home bar
once Autorun Smart Hub is off.

## Level 2: block ad domains on your network

If you run **Pi-hole** or **AdGuard Home** (both run fine on the same
Raspberry Pi as ad-arta), add the list in `adblock/`:

- AdGuard Home or Pi-hole v6+: `adblock/samsung-ads.txt`
- older Pi-hole: `adblock/samsung-ads-domains.txt`

You can paste the raw GitHub URL of the file as a blocklist, or copy the
domains in by hand. Then set the TV's DNS to the Pi-hole/AdGuard address
(Settings > General > Network > Network Status > IP Settings > DNS Setting:
Enter manually), or set it for your whole network in the router.

This removes the sponsored tiles and banners on the home bar and stops ad
tracking. If an app or the Art Store stops working, check the query log
and unblock the domain it needs.

## Level 3: cut the TV off from the internet (strongest)

In your router, block internet access for the TV's IP or MAC address
(often called "parental controls", "access control" or a firewall rule).
The TV stays on your home network, so **ad-arta and Art Mode keep working**,
and so does the Apple TV over HDMI. Every Samsung ad and tracker disappears.

What you give up: firmware updates, the Samsung Art Store subscription
(your own uploaded photos still show) and the TV's built-in apps.
Tip: allow the internet back for an evening every few months to take
updates.

A milder version: decline the Smart Hub Terms & Conditions / Privacy Notice
in Terms & Policy. Built-in apps and ads stop; Art Mode with your own
pictures should still work, but the Art Store may need the terms accepted.
