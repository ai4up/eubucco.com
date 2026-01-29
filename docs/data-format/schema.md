# Data Schema Reference


### Core Data Fields

| Group | Attribute | Type | Definition | Example |
| :--- | :--- | :--- | :--- | :--- |
| **Identifiers** | `id` | `string` | Unique ID composed of a *Block ID*[^1] and sequence number. | `3ba70f9963714924-0` |
| | `region_id` | `string` | [NUTS3](https://ec.europa.eu/eurostat/web/nuts/maps) regional identifier. | `FR931` |
| | `city_id` | `string` | Local Administrative Unit ([LAU](https://ec.europa.eu/eurostat/web/nuts/local-administrative-units)) identifier for the city. | `FR93066` |
| **Attributes** | `type` | `category` | Binary usage type[^2]. | `residential` |
| | `subtype` | `category` | Detailed usage type[^3]. | `terraced` |
| | `height` | `float` | Distance in meters from ground floor to top of building. | `23.9` |
| | `floors` | `float` | Total number of above-ground floors. | `3.5` |
| | `construction_year` | `integer` | Year initial construction finished (not renovation year). | `1963` |
| **Geometry** | `geometry` | `binary` | Footprint geometry projected in `ETRS89` (`EPSG:3035`) encoded as WKB. Units in meters. | `01030000...` |

### Auxiliary Data Fields
| Group | Attribute | Type | Definition | Example |
| :--- | :--- | :--- | :--- | :--- |
| **Confidence** | `type_confidence` | `float` | Area-weighted intersection ratio (merged) or sum of calibrated subtype probabilities (predicted). Range: [0, 1]. | `0.95` |
| | `subtype_confidence`| `float` | Area-weighted intersection ratio (merged) or calibrated class probability (predicted). Range: [0, 1]. | `0.64` |
| | `height_confidence_lower` | `float` | Min source value (merged) or lower 95% bootstrap CI (predicted) for height. | `7.5` |
| | `height_confidence_upper` | `float` | Max source value (merged) or upper 95% bootstrap CI (predicted) for height. | `10.5` |
| | `floors_confidence_lower` | `float` | Min source value (merged) or lower 95% bootstrap CI (predicted) for floors. | `2.7` |
| | `floors_confidence_upper` | `float` | Max source value (merged) or upper 95% bootstrap CI (predicted) for floors. | `3.2` |
| | `construction_year_confidence_lower` | `int` | Min source year (merged) or lower 95% bootstrap CI (predicted) for year. | `1990` |
| | `construction_year_confidence_upper` | `int` | Max source year (merged) or upper 95% bootstrap CI (predicted) for year. | `2000` |
| **Sources** | `geometry_source` | `category` | Origin of footprint geometry. | `gov-france` |
| | `type_source` | `category` | Origin of `type` attribute. | `osm` |
| | `subtype_source` | `category` | Origin of `subtype` attribute. | `estimated` |
| | `height_source` | `category` | Origin of `height` attribute. | `estimated` |
| | `floors_source` | `category` | Origin of `floors` attribute. | `gov-france` |
| | `construction_year_source` | `category` | Origin of `construction_year` attribute. | `gov-france` |
| **Source IDs** | `geometry_source_id`| `string` | Primary identifier from the source provider. | `BATIMENT000...` |
| | `type_source_ids` | `array` | List of IDs from source(s) contributing to the `type` attribute. | `['osm_123']` |
| | `subtype_source_ids` | `array` | List of IDs from source(s) contributing to the `subtype` attribute. | `['osm_123']` |
| | `height_source_ids` | `array` | List of IDs from source(s) contributing to the `height` attribute. | `['ign_456']` |
| | `floors_source_ids` | `array` | List of IDs from source(s) contributing to the `floors` attribute. | `['ign_456']` |
| | `construction_year_source_ids` | `array` | List of IDs from source(s) contributing to the `construction_year`. | `['ign_456']` |
| **Source values** | `subtype_raw` | `string` | The original, unmapped building use type from the source dataset. | `Einfamilienhaus` |

### Example
| id | region_id | city_id | type | subtype | height | floors | construction_year | type_confidence | subtype_confidence | height_confidence_lower | height_confidence_upper | floors_confidence_lower | floors_confidence_upper | construction_year_confidence_lower | construction_year_confidence_upper | geometry_source | type_source | subtype_source | height_source | floors_source | construction_year_source | geometry_source_id | type_source_ids | subtype_source_ids | height_source_ids | floors_source_ids | construction_year_source_ids | subtype_raw | geometry |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| aec95c88db604a13-0 | FRF31 | FR54029 | residential | detached | 3.3 | 1.0 | nan | 1.0 | 0.99 | 3.2 | 3.5 | 1.0 | 1.0 | <NA\> | <NA\> | gov-france | osm | estimated | estimated | osm | <NA\> | BATIMENT0000000334652469 | ['lorraine-latest_1372503'] | <NA\> | <NA\> | ['lorraine-latest_1372503'] | <NA\> | Indifférencié | POLYGON ((402...)) |
| 9d1c73d618ef419e-0 | FRF31 | FR54037 | residential | detached | 5.7 | 2.0 | nan | 0.86 | 0.84 | 5.3 | 6.2 | 2.0 | 2.0 | <NA\> | <NA\> | gov-france | osm | estimated | estimated | osm | <NA\> | BATIMENT0000002101827291 | ['lorraine-latest_1661552'] | <NA\> | <NA\> | ['lorraine-latest_1661552'] | <NA\> | Indifférencié | POLYGON ((404...)) |
| ce19c9e4976d46f6-2 | FRF31 | FR54039 | non-residential | others | 3.8 | 2.0 | nan | 0.84 | 0.84 | nan | nan | 2.0 | 2.0 | <NA\> | <NA\> | gov-france | osm | osm | gov-france | osm | <NA\> | BATIMENT0000000334989890 | ['lorraine-latest_805209'] | ['lorraine-latest_805209'] | <NA\> | ['lorraine-latest_804619'] | <NA\> | Indifférencié | POLYGON ((407...)) |
| ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |


### Technical Notes

#### Building Type Classification
* We use a two-tier hierarchy to categorize building usage. The `type` field provides a high-level binary split, while the `subtype` field contains the granular class.
    * *Type:* `residential`. *Subtypes*: `detached` (single-family), `semi-detached` (duplex), `terraced` (row house), and `apartment` (multi-family).
    * *Type:* `non-residential`. *Subtypes*: `industrial`, `commercial`, `public`, `agricultural`, and `others` (e.g. garages)
* The `subtype_raw` column preserves the original source classification string prior to this harmonization. Refer to the metadata file on building type mapping for more details.


#### Geometry Encoding
* The `geometry` column is stored as *Well-Known Binary (WKB)*. This is a compact, machine-readable format optimized for GIS tools like PostGIS, QGIS, and GeoPandas.

#### Attribute Sources
* Attribute source categories are `osm`, `msft`, `gov-<region>`, `estimated` (where <region> represents the specific regional authoritative dataset identifier)

#### Attribute Uncertainty
* **Ground Truth**: `NaN` in a `<attr>_confidence` column indicates the attribute was provided directly by the geometry source; no merging or machine learning estimation was required.
* **Interpretation**: For `type_confidence` and `subtype_confidence`, a value of 0.6 implies that 60% of buildings in that cohort are statistically expected to be correctly classified.
* **Methodology**: For details on how the uncertainty of attribute estimation and merging is quantified, please refer to the [Uncertainty](../../../data-format/uncertainty) Section.


#### Attribute Merging
* **Source Mismatch**: If `geometry_source` and `<attr>_source` differ, the attribute has been merged between datasets.
* **Data Fusion:** If `<attr>_source_ids` contains multiple values, the final value has been from aggregated from multiple source buildings.

<!-- #### Attribute Prediction
* If `subtype_source` is `estimated` but `type_source` corresponds to a source dataset, only the subtype (i.e. residential subtype `detached`, `terraced`, etc.) has been estimated. -->


[^1]: Block ID: A unique identifier for a cluster of topologically connected (touching) buildings.
[^2]: Binary use type categories: `residential` and `non-residential`.
[^3]: Detailed use type categories: `industrial`, `commercial`, `public`, `agricultural`, `others`, `detached`, `semi-detached`, `terraced`, and `apartment`.
