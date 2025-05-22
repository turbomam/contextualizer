# OpenStreetMap Feature Extraction and EnvO Normalization for NMDC Biosamples

## Pipeline Overview

The contextualizer project implements a pipeline to enrich NMDC biosamples with geographical context by:

1. **Validating Coordinates**: Cross-referencing asserted vs. inferred coordinates
2. **Extracting OSM Features**: Using Overpass API to obtain nearby environmental features
3. **Normalizing to EnvO Terms**: Mapping OSM features to standard ontology terms
4. **Aggregating Features**: Making higher-level environmental inferences from feature density
5. **Test Case Management**: Identifying samples with high/low agreement for continuous improvement

## Current Status

The complete pipeline is now operational with all stages working:

### Stage 1: Coordinate Validation ✅

- Successfully processes 1300 biosamples (10% of the ~13k total)
- Infers coordinates from geo_loc_name using geopy
- Adds elevation data using NMDC geoloc tools
- Calculates distance between asserted and inferred coordinates

### Stage 2: OSM Feature Extraction ✅

- Extracts features within a configurable radius (default 1000m) of sample coordinates
- Filters biosamples with unreliable coordinates (>10km difference between asserted/inferred)
- Organizes features by category (natural, water, landuse, etc.)
- Uses random sampling to select 130 biosamples (~10% of previous stage)
- Implements proper rate limiting and retry logic for Overpass API

### Stage 3: EnvO Normalization ✅

- Maps OSM features to EnvO terms using OAK and PydanticAI agents
- Calculates confidence scores for each mapping
- Extracts existing environmental terms from biosamples (env_broad_scale, env_local_scale, env_medium)
- Organizes results by NMDC environmental fields for direct comparison
- Uses random sampling to process a manageable subset

### Stage 4: Feature Aggregation ✅

- Analyzes feature density to make higher-level environmental inferences
- Makes intelligent predictions like "many trees indicate forest"
- Adds aggregated inferences to the appropriate NMDC environmental fields

### Stage 5: Test Case Management ✅

- Calculates agreement scores between asserted and inferred EnvO terms
- Automatically identifies samples with high and low agreement scores
- Maintains a growing test case library for continuous improvement
- Tracks performance over time through standard test cases

## Recent Improvements

### Project Organization

- Moved utility scripts to a dedicated `src/utils` directory
- Added proper Python package structure with `__init__.py` files
- Updated import paths to maintain compatibility
- Added tests to verify the organization works correctly

### Sampling Strategy

- Increased initial sample size from 130 to 1300 biosamples (10% of total ~13k)
- Modified OSM enricher to use random sampling instead of taking the first N samples
- Updated EnvO normalizer to also use random sampling
- Set downstream processes to use 10% of their input (~130 samples)

### Test Case Infrastructure

- Added an agreement score calculation to evaluate how well inferred EnvO terms match asserted terms
- Implemented a function to automatically select the best and worst performing samples
- Added a new CLI parameter to select top/bottom N samples from a results file
- Added a Makefile target to generate test cases from the normalized results
- Enhanced test case metadata to include agreement scores and categories
- Added asserted terms to the test cases for easier comparison

### Rate Limiting

- Maintained appropriate rate limiting for API calls:
    - 0.5s delay between geocoding requests
    - 0.1s delay between elevation requests
    - 1.0s delay between OSM API requests
    - Retry mechanisms with 5s delays for API failures

## Example Data

### OSM Feature Example

```json
{
  "id": "8149703597",
  "type": "natural:tree",
  "coordinates": [
    43.0771678,
    -89.3849078
  ],
  "area": null,
  "environmental_tags": {
    "natural": "tree"
  },
  "distance_from_center": 188.87
}
```

### EnvO Mapping Example

```json
{
  "envo_id": "ENVO:00000097",
  "envo_label": "forest biome",
  "confidence": 0.85,
  "reasoning": "The presence of numerous trees (>50) within a small area strongly indicates a forest environment.",
  "feature_id": "aggregation-natural:tree",
  "feature_type": "aggregation:natural:tree",
  "distance": 0.0,
  "nmdc_field": "env_broad_scale",
  "nmdc_field_confidence": 0.9,
  "is_aggregation": true,
  "feature_count": 87
}
```

## Ongoing Challenges

1. **Agreement Evaluation**: The current agreement score is based on exact matches between asserted and inferred EnvO
   terms. This could be enhanced with semantic similarity measures.

2. **Field Coverage**: Currently targeting only `env_broad_scale`, `env_local_scale`, and `env_medium`. More NCBI
   Biosample fields could be added in the future.

3. **Feature Type Coverage**: The system works well for common feature types (trees, water bodies, etc.) but may need
   expansion for more specialized environmental features.

4. **Confidence Scoring**: The confidence mechanism could be refined based on feature distance, density, and alignment
   with known environmental patterns.

## Next Steps

1. **Semantic Similarity**: Develop a more sophisticated way to measure agreement between asserted and inferred EnvO
   terms by considering ontological relationships.

2. **Expanded Targets**: Add support for additional NCBI Biosample environmental fields based on documentation.

3. **Benchmark Development**: Create a formal benchmark dataset with ground-truth annotations to better evaluate the
   system's performance.

4. **Long-term Metrics**: Establish metrics to track improvement over time as the system evolves.

5. **Feature Aggregation Expansion**: Add more feature aggregation rules to infer higher-level environmental contexts.

6. **Interactive Visualization**: Create tools to visualize the relationship between geographic features and inferred
   environmental context.

## Output Files

- `local/nmdc-biosamples.json`: Raw biosample data from NMDC API
- `local/nmdc-latlon-inferred.json`: Biosamples with coordinate validation (1300 samples)
- `local/nmdc-osm-enriched.json`: Biosamples with OSM features (130 samples)
- `local/nmdc-envo-normalized.json`: Biosamples with OSM features mapped to EnvO terms (130 samples)
- `nmdc-osm-envo-test-cases.json`: Collection of test cases with performance metrics

## Usage

Run the full pipeline using Makefile targets:

```bash
# Run the complete pipeline including test case generation
make all

# Run individual stages
make local/nmdc-latlon-inferred.json
make local/nmdc-osm-enriched.json
make local/nmdc-envo-normalized.json
make nmdc-osm-envo-test-cases.json

# Run tests
make test
```