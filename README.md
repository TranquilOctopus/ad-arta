# ad-arta

Make a **2020 Samsung The Frame TV** go to **Art Mode** (instead of turning
off) when you press the power button on the **Apple TV remote**, and strip
out as many Samsung ads as possible.

## Why the TV turns off

The Siri Remote's power button sleeps the Apple TV and sends the TV an
HDMI-CEC "standby" command. Many Frame TVs treat that as a full power-off
instead of switching to Art Mode. The TV's firmware can't be changed, so
ad-arta works around it:

1. Turn off the Apple TV's CEC control of the TV, so the remote's power
   button **only** sleeps the Apple TV.
2. ad-arta runs on an always-on device on your network (Raspberry Pi, NAS,
   Mac mini, Home Assistant box...). It sees the Apple TV fall asleep and
   tells the Frame to switch to Art Mode over its local network API.
3. When the Apple TV wakes up, ad-arta switches the Frame out of Art Mode
   back to the Apple TV picture.

```
Siri Remote power button -> Apple TV sleeps -> ad-arta notices -> Frame: Art Mode
Siri Remote any button   -> Apple TV wakes  -> ad-arta notices -> Frame: TV mode
```

If the TV ever fully turns off anyway, ad-arta wakes it with Wake-on-LAN
and then switches it to Art Mode.

## Try this first: settings-only fix

Some 2020 Frame owners report that changing settings alone makes Art Mode
work, with no extra device needed. It's worth 2 minutes:

- On the TV: **Settings > General > External Device Manager > Anynet+ (HDMI-CEC)**.
  Turn it off, restart the TV and the Apple TV, and test the remote's power
  button. Some firmware also has an option for whether connected devices may
  turn the TV off. If you see one, turn it off and keep Anynet+ on.

If the TV still powers off, set up ad-arta below.

## Setup

### 1. TV settings

- **Settings > General > Network > Expert Settings > Power On with Mobile: On**
  (lets ad-arta reach and wake the TV).
- Give the TV a fixed IP address (DHCP reservation in your router). Note
  its IP and MAC address (Settings > Support > About This TV).

### 2. Apple TV settings

- **Settings > Remotes and Devices > Control TVs and Receivers: Off.**
  The power button now only sleeps the Apple TV, and ad-arta handles the TV.
  For volume, set **Remotes and Devices > Volume Control** to an IR option
  (Auto IR or Learn New Device) so the Siri Remote still controls TV volume.
- If a "Turn on your TV with your remote" option appears afterwards, you can
  turn it on.

### 3. Install ad-arta

On the always-on device (needs Python 3.10+):

```sh
git clone https://github.com/tranquiloctopus/ad-arta.git
cd ad-arta
python3 -m venv .venv
.venv/bin/pip install .
cp config.example.toml config.toml
nano config.toml          # set the TV IP and MAC
```

### 4. Pair with the TV

```sh
.venv/bin/ad-arta pair-tv
```

Choose **Allow** on the TV. The token is saved to `tv-token.txt`. Test it:

```sh
.venv/bin/ad-arta status
.venv/bin/ad-arta art-on     # TV should switch to Art Mode
.venv/bin/ad-arta art-off    # and back
```

### 5. Pair with the Apple TV

```sh
.venv/bin/atvremote scan                                  # find the Apple TV + identifier
.venv/bin/atvremote --id <identifier> --protocol companion pair
.venv/bin/atvremote --id <identifier> --protocol airplay pair
```

Type the PIN shown on the Apple TV each time. Credentials go to
`~/.pyatv.conf`, which ad-arta reads. Put the identifier in `config.toml`
if you have more than one Apple TV.

### 6. Run it

Try it in the foreground first and press the remote's power button:

```sh
.venv/bin/ad-arta run
```

Then run it as a service so it starts at boot. Edit the user and paths in
`deploy/ad-arta.service`, then:

```sh
sudo cp deploy/ad-arta.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ad-arta
journalctl -u ad-arta -f      # logs
```

Or with Docker: put `config.toml`, `tv-token.txt` and `.pyatv.conf` in
`./data`, then run `docker compose up -d`. Pair with the Apple TV before
this step.

## Removing ads

See **[docs/remove-ads.md](docs/remove-ads.md)**: TV privacy and ad
settings, a DNS blocklist for Pi-hole/AdGuard Home in `adblock/`, and how
to cut the TV off from the internet entirely while keeping Art Mode and
ad-arta working.

## Config

| Key | Meaning |
|---|---|
| `tv.host` | TV IP address |
| `tv.mac` | TV MAC address, for Wake-on-LAN |
| `tv.token_file` | Pairing token file (relative to the config file) |
| `tv.input_key` | Optional key sent after leaving Art Mode, e.g. `KEY_HDMI1` |
| `appletv.identifier` | Apple TV identifier from `atvremote scan` (optional) |
| `appletv.host` | Apple TV IP, skips discovery (optional) |
| `bridge.off_delay` | Seconds to wait before Art Mode (ignores quick sleep/wake blips) |
| `bridge.wake_tv_with_appletv` | Leave Art Mode when the Apple TV wakes |

## Troubleshooting

- **Nothing happens on sleep:** run `ad-arta -v run` and check that it
  logs "Connected to ..." and "Apple TV turned off". If it doesn't, pair
  again with both the `companion` and `airplay` protocols.
- **"TV is off and no mac is set":** add `tv.mac` and turn on Power On with Mobile.
- **TV asks to Allow again:** delete `tv-token.txt` and run `pair-tv` again.
- **Art Mode turns off after a few hours:** that's the Frame's own Sleep
  After / motion sensor setting in Art Mode settings.

## Development

```sh
pip install -e '.[test]'
pytest
```

Built on [pyatv](https://pyatv.dev) and
[samsungtvws](https://github.com/xchwarze/samsung-tv-ws-api).
