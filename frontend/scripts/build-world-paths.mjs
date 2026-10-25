// Dev-only generator for src/components/results/world-paths.json — the
// pre-projected SVG country outlines the Results choropleth renders at
// runtime with zero geo dependency. Re-run only if the base map must change:
//
//   cd frontend
//   npm install --no-save d3-geo topojson-client world-atlas iso-3166
//   node scripts/build-world-paths.mjs
//
// Natural Earth 110m via world-atlas; Antarctica dropped (empty vertical
// space); features keyed by ISO 3166-1 alpha-3 to match the backend's
// country normalization; coordinates rounded to 1 decimal to keep the
// asset ~100 kB.
import { writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { geoNaturalEarth1, geoPath } from 'd3-geo'
import { feature } from 'topojson-client'
import { iso31661 } from 'iso-3166'

const require = createRequire(import.meta.url)
const world = require('world-atlas/countries-110m.json')

const alpha3ByNumeric = Object.fromEntries(
  iso31661.map((c) => [c.numeric, c.alpha3]))
// Natural Earth quirks: disputed/partially recognized ids
alpha3ByNumeric['-99'] = null // N. Cyprus, Somaliland… no ISO code
const KOSOVO_NAME = 'Kosovo'

const countries = feature(world, world.objects.countries).features
  .filter((f) => f.id !== '010') // Antarctica

const projection = geoNaturalEarth1().fitSize(
  [960, 500], { type: 'FeatureCollection', features: countries })
const path = geoPath(projection)
if (path.digits) path.digits(1)

const out = []
for (const f of countries) {
  let iso3 = alpha3ByNumeric[f.id] ?? null
  if (!iso3 && f.properties?.name === KOSOVO_NAME) iso3 = 'XKX'
  const d = path(f)
  if (!d) continue
  out.push({ iso3, name: f.properties?.name ?? '', d })
}

writeFileSync(
  new URL('../src/components/results/world-paths.json', import.meta.url),
  JSON.stringify(out))
console.log(`world-paths.json written: ${out.length} countries,`,
            `${out.filter((c) => !c.iso3).length} without ISO code`)
