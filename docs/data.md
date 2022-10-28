# Data

The EUBUCCO dataset is distributed in two data formats:

* Geopackage (`.gpkg`): building attributes + footprint geometries
* CSV (`.csv`): building attributes only

The coordinate reference system used for all geometries is `EPSG:3035`.


## Structure

| Attribute | Type | Definition |
| --------- | ---- | ---------- |
| id | `string` | Unique EUBUCCO building identifier based on the version number of the database, the GADM city identifier and an ascending number for all buildings in the city |
| id_source | `string` | Identifier from the original dataset (if no identifier was provided the file name and an ascending number for all buildings in the country was applied) |
| height | `float` | Distance in meter between the elevation of the ground floor and of a point representing the top of the building (lowest or highest roof point, highest building point, ...); see the relevant height | definition in `input−dataset−metatable−v0.1.xlsx` |
| age | `integer` | Initial construction end year of the building (e.g. not the renovation year, if any) |
| type | `string` | Usage type of the building, based on our classification ∈ {residential, non−residential, unknown}
| type_source | `string` / `float` | Usage type of the building, from the original dataset, possibly a human-readable type or a code; see type_matches−v0.1.zip for human-readable matching translated in English if relevant |
| geometry | `string` | Footprint of the building as a 2D (X,Y) polygon object projected in `ETRS89` (`EPSG: 3035`) and encoded as a WKT `string` (only included in GPKG files) |


## Metadata

1. **Metadata table on input datasets** (`input−dataset−metatable−v0.1.xlsx`): This table contains 38 dimensions
that provide users with the main information about input datasets. Specifically, the file contains the input dataset’s
    * name and area information (e.g. country, dataset specific area and dataset name)
    * meta info (e.g. access date, data owner, license, link to ressource or download approach)
    * structure (e.g. file format, breakdown or additional files matched for attributes)
    * content relevant to EUBUCCO v0.1 (e.g. availability of given attributes or LoDs)
    * variable names (e.g. ID, construction year, or building element for `.gml` files)
    * and validation information via the number of buildings at three stages of the workflow (after parsing, cleaning and matching with administrative boundaries) together with the losses that occurred and a short explanation in case of large losses
1. **Table on excluded datasets** (`excluded−datasets−v0.1.xlsx`): This table provides an overview of available government datasets that were not included in this study with a rational why, most often because they were only available at a high cost. For all these datasets we contacted the data owner to ask whether the data were available for free for research; the status of the dataset reflects their answer and a contact date is also indicated in the file
1. **Database content metrics at the city-level** (`city−level−overview−tables−v0.1.zip`): The overview files provide 48 city-level metrics for all 41,456 cities, of which 627, mostly very small cities, do not contain any building. The files enable a detailed overview of the database content in term of geometries and attributes can be used to study patterns across regions and countries and can also be used to identify bugs or outliers. They are provided as a table for each country with the following naming: `<country>_overview−v0.1.csv`. Each table contains:
    * the city ID, name and region
    * building counts and footprint metrics including total number of buildings, total footprint area, footprint area distribution, max footprint area, number of 0-m<sup>2</sup> footprints, etc.
    * height distribution metrics in relative and absolute terms, including overall metrics e.g. median and max value, also outliers outside of a reasonable range e.g. negative values, and metrics by height bins e.g. `[3, 5(` or `[11, 15(`
    * type distribution metrics in relative and absolute terms computed for the variable type and describing the proportion of residential, non-residential and unknown building types
    * construction year distribution metrics in relative and absolute terms grouped by construction year bins e.g. `[1801, 1900(` or `[1951, 2000(` and also counting additional dimensions such as outliers outside of a reasonable range e.g. negative values
1. **Type matching tables** (`type_matches−v0.1.zip`): Multiple tables are provided for each relevant dataset or group of datasets (if cadaster codes apply for several datasets in Germany and Italy) as `<dataset>−type_matches−v0.1.csv`. These tables enable to map the type of the raw data (`type_source`) to the type column (`type_source`) of the database and provide an English translation of the type of the raw data
1. **Administrative code matching table** (`admin−codes−matches−v0.1.csv`): This table enables to match the GADM code from building ids with its country, region, city and the input dataset per city.
1. **Administrative city levels** (`gadm−city−levels−v0.1.csv`): This table provides an overview of the GADM level that was chosen to define the city level per country.
