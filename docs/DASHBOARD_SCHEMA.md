# Current PowerTune Dashboard Format (Legacy)

This document describes the existing PowerTune dashboard persistence and
portable-file formats. It is not the proposed HIVE schema. The current format
is legacy, irregular, and has no explicit schema version.

HIVE will use a deliberately documented, versioned schema. Do not retrofit
speculative HIVE schema concepts into the current PowerTune format.

## Persistence paths and formats

Each UserDash QML component has independent working content:

| Dashboard | QML component | Settings-backed property |
|---|---|---|
| UserDash 1 | `Gauges/Userdash1.qml` | `datastore1` |
| UserDash 2 | `Gauges/Userdash2.qml` | `datastore2` |
| UserDash 3 | `Gauges/Userdash3.qml` | `datastore3` |

Each component's `Settings` alias persists its datastore through Qt settings.
The datastore is a JSON string containing an array of element objects. The
actual QSettings storage location is chosen by Qt and is not the portable
dashboard-file directory.

**Save** rebuilds the selected UserDash's JSON records from its live widget
children and writes the result to that UserDash's datastore. The three
datastores are separate; saving one does not save the other two.

**Export/Import** is separate from Save. Export writes a portable text file
under the directory returned by `ptDashboardsPath()` (Linux:
`/var/lib/powertune/UserDashboards/`; Windows development:
`C:/PowerTune/UserDashboards/`). Each element is a comma-separated positional
row, with no versioned header. Import reads those rows and creates widgets; it
does not directly load the JSON datastore. This is a legacy CSV-like format,
not a general-purpose escaped CSV format. Import splits each row on commas
while preserving empty fields, so an empty cell no longer shifts subsequent
values. Export writes empty cells as empty cells; it does not substitute a
space placeholder.

The format still does not quote or escape commas, quotes, carriage returns, or
line feeds inside values. A comma in a value is parsed as another field;
carriage returns and line feeds delimit records. Quotes have no special
meaning. Values containing these delimiters cannot be represented reliably
without changing the legacy format.

## Common element fields

The JSON records are not a uniform object schema. The fields below are common
concepts, but not every element has every field:

| Field/concept | Meaning | Presence |
|---|---|---|
| `info` | **Element reload/type discriminator.** `createDash()` switches on this string to select the widget constructor. | Written for every current Save record; required for current reload dispatch. |
| `x`, `y` | Widget position. | Written for positioned elements; numeric. |
| `width`, `height` | Widget dimensions. Some widgets save both; others use a single size field or derive height from width. | Element-specific; numeric where used. |
| Datasource name | A string naming the Dashboard value/property bound to the widget. The JSON key varies (`mainvaluename`, `valuepropertymain`, `datasourcename`, or `source`). | Element-specific; may be absent for non-data widgets. |
| Resource URL/path | Image/GIF source value. | Element-specific string; may be a QRC URL or local-file URL. |
| Trigger/threshold | Numeric condition used by state widgets. | State Image has `trigger`; State GIF has `trigger` and `triggeroff`. |
| Options | Appearance, units, fonts, limits, and other settings. | Element-specific; see below. |

The exact element identifier strings are legacy values, including `"gauge
image"` for Picture/Image and `"State gauge"` for State Image.

## `type` and `id`

* `type` was not consumed by current reload dispatch and is no longer written
  by Save.
* SquareGauge writes `id` as its displayed title. Reload consumes this field
  and passes it back as the title.
* Bar gauges do not provide or require `type` or `id`.
* Other elements do not generally share SquareGauge's `id` role. Do not infer
  that every record has a title/id.

Historical JSON may contain extra fields such as `type`. Current loading
accepts known historical records without rewriting the stored JSON just by
opening the dashboard; subsequent Save writes the current serializer's fields.
This does not guarantee that arbitrary malformed fields or records are safe.

## Element-specific JSON records

The tables below describe fields emitted by the current `savedash()` in each
UserDash implementation. UserDash 1, 2, and 3 use the same element schemas;
only their settings keys differ. “Current Save” means that the serializer
writes the field. It does not imply a separately validated schema requirement
for every historical record.

### RoundGauge (`info: "Round gauge"`)

Current Save writes `info`, `width`, `x`, `y`, `mainvaluename`, `maxvalue`,
`minvalue`, `warnvaluehigh`, `warnvaluelow`, `startangle`, `endangle`,
`redareastart`, `divider`, `tickmarksteps`, `minortickmarksteps`,
`setlabelsteps`, `decimalpoints`, `needleinset`, `setlabelinset`,
`setminortickmarkinset`, `setmajortickmarkinset`, `minortickmarkheight`,
`minortickmarkwidth`, `tickmarkheight`, `tickmarkwidth`,
`trailhighboarder`, `trailmidboarder`, `traillowboarder`,
`trailbottomboarder`, `labelfontsize`, `needleTipWidth`, `needleLength`,
`needleBaseWidth`, `redareainset`, `redareawidth`, `tickmarkcolor`,
`needlecolor`, `needlecolor2`, `backroundcolor`, `warningcolor`,
`minortickmarkcoloractive`, `minortickmarkcolorinactive`,
`majortickmarkcoloractive`, `majortickmarkcolorinactive`,
`labelcoloractive`, `labelcolorinactive`, `outerneedlecolortrailsave`,
`middleneedlecortrailsave`, `lowerneedlecolortrailsave`,
`innerneedlecolortrailsave`, `needlevisible`, `ringvisible`,
`needlecentervisisble`, `labelfont`, `desctextx`, `desctexty`,
`desctextfontsize`, `desctextfontbold`, `desctextfonttype`,
`desctextdisplaytext`, `desctextdisplaytextcolor`, `peakneedlecolor`,
`peakneedlecolor2`, `peakneedlelenght`, `peakneedlebasewidth`,
`peakneedletipwidth`, `peakneedleoffset`, and `peakneedlevisible`.

The names and spellings above are persisted API. Geometry, limits, angles,
steps, dimensions, and offsets are numeric; visibility and bold options are
booleans; datasource, font, and display-text values are strings; colors are
color values serialized by Qt/QML. Exact units, ranges, and defaults are
element properties in `Gauges/RoundGauge.qml`, not defined by a central schema.
The record stores `width` but not `height`; reload constructs a square using
that width. The `peakneedle*` fields are written and passed to the creation
helper, but their property assignments in that helper are commented out;
current reload therefore does not apply those saved values.

### Picture/Image (`info: "gauge image"`)

| Field | Type/meaning | Current Save / default / compatibility |
|---|---|---|
| `info` | String discriminator. | `"gauge image"`. |
| `x`, `y` | Numeric position. | Written by Save. |
| `pictureheight` | Numeric image size; the widget derives its dimensions from it. | Written by Save. |
| `picturesource` | String resource URL/path. | Written by Save; newly added Picture starts with a QRC selection image. |

The exact selection-image resource is a UI placeholder, not a schema default
for imported historical records.

### State Image (`info: "State gauge"`)

| Field | Type/meaning | Current Save / default / compatibility |
|---|---|---|
| `info` | String discriminator. | `"State gauge"`. |
| `x`, `y` | Numeric position. | Written by Save. |
| `height` | Numeric size, sourced from `pictureheight`. | Written by Save; reload passes it to the widget size parameter. |
| `source` | String datasource/property name, sourced from `mainvaluename`. | Written by Save. |
| `trigger` | Numeric state threshold, sourced from `triggervalue`. | Written by Save; QML property default is `0`, while the add-widget path supplies its own initial value. |
| `pictureoff`, `pictureon` | String resource URLs/paths, sourced from the OFF/ON image properties. | Written by Save; existing records retain their source values until the normal save path runs. |

The component's numeric trigger supports negative and decimal values. Its
editor validates input; invalid text is not applied and the previous valid
number remains in effect.

### State GIF (`info: "State GIF"`)

State GIF uses the State Image fields plus:

| Field | Type/meaning | Current Save / default / compatibility |
|---|---|---|
| `triggeroff` | Numeric OFF/state threshold, sourced from `triggeroffvalue`. | Written by Save and portable export. The component property default is `0`; the add-widget path supplies `0`. |

New State GIF instances start with empty optional OFF/ON resource sources
until configured, and the add path initializes the main trigger to `1` and
the OFF trigger to `0`. An empty-source instance must still show a visible,
selectable placeholder; double-tap opens the existing editor. The editor
selects the OFF/ON GIF resources and edits the thresholds.

The legacy source string ending in `,0` is treated as unconfigured for display.
Loading alone does not rewrite the stored source; normal Save/Export may write
the normalized value. Missing optional resources should not hide the widget.
GIF decoding on Device 0 is still unverified; possible missing `libqgif.so`
target packaging remains an open validation issue.

State GIF thresholds are numeric and support negative and decimal values.
Invalid editor text is rejected without replacing the prior valid threshold.

### SquareGauge (`info: "Square gauge"`)

Current Save writes:

* `info` (string discriminator);
* `width`, `height`, `x`, `y`, `maxvalue`, `decplace`, `decplace2`,
  `titlefontsize`, and `mainfontsize` (numeric geometry/format settings);
* `unit` (main unit string), `id` (display title string);
* `vertgaugevis`, `horigaugevis`, and `secvaluevis` (visibility booleans);
* `valuepropertymain` and `valuepropertysec` (datasource/property names);
* `warnvaluehigh`, `warnvaluelow` (numeric warning limits);
* `framecolor`, `backroundcolor`, `titlecolor`, `titletextcolor`, `textcolor`,
  and `barcolor` (colors);
* `textfont` and `valuefont` (font selections).

Reload consumes these keys to restore the SquareGauge, including `id` as its
title. The defaults for options are the component defaults in
`Gauges/Squaregauge.qml`; the serialized record does not define a separate
default table.

### Vertical/bar gauge (`info: "Bar gauge"`)

Current Save writes `width`, `height`, `x`, `y`, `maxvalue`, `minvalue`,
`decplace`, `unit`, `valuepropertymain`, `warnvaluehigh`, `warnvaluelow`, and
`info`. These are numeric geometry/limits/decimal settings, a unit string, a
datasource/property name, warning values, and the string discriminator.
Neither `type` nor `id` is present or needed.

The reload creator applies dimensions, limits, decimal places, unit,
datasource, and position. Although Save records warning limits and the reload
call passes them to the creator, the current vertical-gauge creation helper
does not assign those two arguments to the created widget. The widget's
component defaults therefore remain in effect for those properties; this is a
current implementation discrepancy, not a different documented field
meaning. See `Gauges/Verticalbargauge.qml` for component defaults.

## Portable Export/Import notes

Portable rows use the element `information` string as their first field, then
type-specific positional values. They are separate from the JSON object
records above. Some rows do not contain the same fields as JSON Save. The
reader preserves empty fields and all three UserDash importers use the same
field-preserving split behavior. State GIF fields are ordered as `info`, `x`,
`y`, `pictureheight`, `mainvaluename`, `triggervalue`,
`statepicturesourceoff`, `statepicturesourceon`, `triggeroffvalue`; either or
both source cells may be empty without shifting the trigger fields.

Do not treat the portable rows as a normalized schema or assume every widget
type has identical fields in JSON and text export.

## Unknowns and limits of this reference

The source establishes the current Save keys and reload paths, but does not
establish a complete formal schema for every historical dashboard version.
Unless a field is explicitly described above, its historical optionality,
default, accepted range, unit, and validation rules are unknown. In particular,
the complete set of accepted datasource names and the escaping/encoding rules
for arbitrary portable text values are not defined. Treat omitted or
unrecognized element fields as unknown rather than assuming a shared default.

## Compatibility and safe editing

* Historical JSON records are parsed and dispatched by `info`; opening a
  source dashboard does not itself write the datastore.
* Known legacy extra fields, including the unused `type`, are tolerated by the
  current loader. Current Save rebuilds records and omits unused fields.
* Historical portable rows with empty comma-separated cells are now parsed
  with their empty positions retained. Rows previously misinterpreted because
  empty cells were discarded may therefore load differently, with subsequent
  fields restored to their intended positions. Historical space placeholders
  remain literal spaces; they are not rewritten to empty values.
* The targeted legacy `file:///home/pi/Logo/` translation is applied in
  memory for dashboard image resources. It is not a global path rewrite.
* When editing a dashboard file for a controlled test, preserve valid JSON
  types (numbers as numbers, booleans as booleans, strings as strings) and
  preserve the original element-specific keys. The portable text format is
  positional and especially sensitive to empty values and commas.
* Validate edits by importing into a noncritical UserDash slot and comparing
  element types and settings before replacing any important dashboard.
* Some field names, defaults, accepted value ranges, and older format variants
  remain undocumented. Check the relevant widget, creation helper, serializer,
  and reload branch before changing or adding a field.

## Source references

Primary evidence is the `savedash()`, `createDash()`, portable import/export,
and component initialization code in `Gauges/Userdash1.qml`,
`Gauges/Userdash2.qml`, and `Gauges/Userdash3.qml`; widget constructors and
properties in `Gauges/create*.js` and the corresponding gauge QML files; and
the dashboard paths in `ptpaths.h`.
