# Profile assets

`stats.svg` and `activity.svg` are committed snapshots. The profile reads these
files directly from this repository instead of calling a third-party stats
service every time someone visits.

The `Update profile analytics` workflow refreshes them daily at 03:17 UTC
(12:17 KST), on changes to the generator, or via **Run workflow**. It uses only
GitHub's public contribution calendar. No personal access token is required;
the workflow's repository token is used by checkout/git to commit the images.
The public calendar follows the account's existing contribution visibility
settings; this workflow does not change them or query private repositories.

To refresh locally (Python 3.10+; no packages required):

```sh
python3 -m unittest discover -s tests -v
python3 scripts/update_profile.py
```

The summary covers the latest 365 UTC dates, not the account's lifetime. The
current streak may end yesterday while today's UTC date is unfinished. The
activity chart covers the latest 31 days. Both cards show their date range;
an empty period is labeled explicitly rather than treated as a loading error.

If GitHub is unavailable, returns incomplete data, or changes its calendar
markup, generation fails before updating the cards. Actions then skips the
commit step, leaving the previous images in place. Check the failed workflow
and the date range on the cards if they stop refreshing.
