# local/

Scratch space that is never committed. Everything here is gitignored except this file.

Put your subscriptions in `local/feeds.opml` — that is where `just opml-import` looks by default:

```sh
just opml-import                      # reads local/feeds.opml
just opml-import path/to/other.opml   # or name one
just opml-export > local/feeds.opml   # write the current list back out
just host=<box>.ts.net opml-import    # same command, against the deployed box
```

Export any reader you already use — NetNewsWire, Reeder, Feedly, FreshRSS all produce OPML. Outlines
naming a site rather than a feed are resolved by feed discovery on import, and folder titles become
subscription categories.

## Formatting

Exports usually arrive as one enormous line. `.opml` is associated with XML in
`.vscode/settings.json`, so format-on-save tidies it once you install the recommended
`redhat.vscode-xml` extension — VS Code will offer it when you open the workspace.

Attributes stay on their element and wrap at 100 columns, so one subscription reads as one row. The
repo's Prettier setup can't do this: it has no XML parser and there is no `node_modules` here for a
plugin to load from.
