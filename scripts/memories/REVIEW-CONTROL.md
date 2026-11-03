# Optional explicit Daily Review control

The TV Memories login app can consume a private local command queue for an
owner-authenticated Axon Service. The feature is disabled unless the private
configuration explicitly contains `review_control.enabled: true`, an `owner`,
and the installed TV's `wake_mac` and `wake_broadcast`. These identifiers stay
in private configuration, never in Git. Queue location is `review-commands`
beside the application's existing config, owned by the login user, mode 0700.

The only accepted command is `tv.dumbtv.review-launch/v1`: operationID (canonical
UUID), owner, issuedAt and expiresAt (integer milliseconds). Its deadline is
exactly two hours after the original wake-alarm offer. No shell, app name, target
address or photo/calendar payload is accepted. Commands must be private regular
files, not symlinks. The login app atomically claims each operation before any
network effect and keeps its receipt. An interrupted claim becomes uncertain;
restarting never repeats that wake attempt.

The fixed path wakes the configured TV if needed, connects through the native
app's existing ADB server, opens Home, allows its Home Guard to settle, opens
DailyReview, and checks that exact activity's window focus. Execution is bounded
and expiry is checked again before wake and activity launch. Failure never
schedules a later automatic retry. The regular photo/Daily Review refresh path
still waits for an already reachable TV and never wakes it.

Build and installation use `build-mac.sh` from clean freshly fetched main. No
branch artifact may be installed on a household Mac or TV. Native queue tests
use synthetic records and no LAN/ADB connection; full wake-alarm acceptance
requires the signed-main Mini app and the explicit phone action.
