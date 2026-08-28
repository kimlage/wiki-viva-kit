# Wiki Viva v8.1.2

Released on 2026-08-28.

This patch corrects the documented entry routes for the standalone 2D source
workspace introduced in v8.1. The canonical operator route is
`/w?view=sources&dock=source`; the synthetic public demo uses
`/demo/w?view=sources&dock=source`.

The release also adds a regression gate that verifies both routes remain in the
public README. A plain `view=sources` remains the source perspective of the 3D
wiki and must not be documented as the standalone management workspace.
