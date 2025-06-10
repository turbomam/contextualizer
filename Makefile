.PHONY: all backup-data clean clean-derived clean-test \
        elevation geo hello hello-world soil \
        test test-agent test-feature-aggregation test-minimal test-soil \
        weather wiki test-agent test-minimal test-soil test-feature-aggregation

RUN_UV_PYTHON=uv run
RUN_UV_PYTEST=uv run pytest

# Default target
all: \
    local/oak_ridge_features.json local/nmdc-ai-map-enriched.json \
    local/nmdc-envo-normalized.json local/nmdc-osm-enriched.json \
    nmdc-osm-envo-test-cases.json \
    hello hello-world elevation geo soil weather wiki \
    test-agent test-minimal
    # Run the agent-test entry point, corresponding to src/agent_test/__init__.py

# Testing targets
test: test-agent test-minimal test-soil test-feature-aggregation

hello:
	$(RUN_UV_PYTHON) agent-test

# Run elevation info script directly
elevation:
	$(RUN_UV_PYTHON) src/agent_test/evelation_info.py

# src/agent_test/geo_agent.py
# Run the geo_agent.py script
geo:
	$(RUN_UV_PYTHON) src/agent_test/geo_agent.py

# Run the hello_world.py script
hello-world:
	$(RUN_UV_PYTHON) src/agent_test/hello_world.py

# src/agent_test/maptools.py -- no main to test

# Run the soil_agent.py script
soil:
	$(RUN_UV_PYTHON) src/agent_test/soil_agent.py

# Run the weather.at.py script
weather:
	$(RUN_UV_PYTHON) src/agent_test/weather.at.py

# Run the wikipedia_animal_qa.py script
wiki:
	$(RUN_UV_PYTHON) src/agent_test/wikipedia_animal_qa.py

# Run original agent tests
test-agent:
	$(RUN_UV_PYTEST) tests/test_agent.py -v

test-minimal:
	$(RUN_UV_PYTEST) tests/test_minimal_agent.py -v

# Directory setup
local/:
	mkdir -p $@

# OSM feature extraction for test location (Oak Ridge)
local/oak_ridge_features.json: src/agent_test/osm_features.py | local/
	$(RUN_UV_PYTHON) $< --lat 35.97583846 --lon -84.2743123 --radius 1000 --output $@

# NMDC biosample data fetch
local/nmdc-biosamples.json: | local/
	wget -O $@ 'https://api.microbiomedata.org/nmdcschema/biosample_set?max_page_size=99999'

# Process biosamples to add lat/lon and elevation
local/nmdc-latlon-inferred.json local/nmdc-latlon-summary.json: src/make_nmdc_biosamples_location_inferences.py local/nmdc-biosamples.json
	$(RUN_UV_PYTHON) $< \
		--input $(word 2,$^) \
		--add-inferred-latlon \
		--add-inferred-elevation \
		--random-n 1300 \
		--output local/nmdc-latlon-inferred.json \
		--summary-output local/nmdc-latlon-summary.json
		
# Process biosamples with map image interpretation
local/nmdc-ai-map-enriched.json: src/biosample_map_interpreter.py local/nmdc-latlon-inferred.json
	$(RUN_UV_PYTHON) $< \
		--input $(word 2,$^) \
		--output $@ \
		--max-samples 13 \
		--map-types satellite,roadmap,terrain \
		--zoom-levels 13,15,17

# Extract OSM features for each biosample location (only for locations with confident coordinates)
local/nmdc-osm-enriched.json: src/biosample_osm_enricher.py local/nmdc-latlon-inferred.json
	$(RUN_UV_PYTHON) $< \
		--input $(word 2,$^) \
		--output $@ \
		--radius 1000 \
		--max-distance 10000 \
		--max-samples 130

# Apply EnvO normalization to OSM features
local/nmdc-envo-normalized.json: src/biosample_envo_normalizer.py local/nmdc-osm-enriched.json
	$(RUN_UV_PYTHON) -m src.biosample_envo_normalizer \
		--input $(word 2,$^) \
		--output $@ \
		--max-samples 130 \
		--max-features 20 \
		--confidence 0.7 \
		--biosample-index -1

# Compare asserted vs inferred environmental values
local/nmdc-comparison-summary.json local/nmdc-llm-comparison.json: src/biosample_llm_comparator.py local/nmdc-ai-map-enriched.json local/nmdc-envo-normalized.json
	$(RUN_UV_PYTHON) $< \
		--input $(word 2,$^) \
		--osm-features $(word 3,$^) \
		--output local/nmdc-llm-comparison.json \
		--summary-output local/nmdc-comparison-summary.json \
		--max-samples 13

test-soil:
	$(RUN_UV_PYTEST) tests/test_soil_agent.py -v
	
test-feature-aggregation:
	$(RUN_UV_PYTEST) tests/test_feature_aggregation.py -v

# Test case management
nmdc-osm-envo-test-cases.json: local/nmdc-envo-normalized.json
	$(RUN_UV_PYTHON) -m src.utils.create_test_cases \
		--select-best-worst $< \
		--num-samples 5 \
		--output $@

# Cleanup targets
clean:
	rm -rf local/

# Clean only derived files, preserving input data
clean-derived:
	# Remove files that can be recreated from scripts and inputs
	rm -f local/oak_ridge_*.json
	rm -f local/nmdc-latlon-*.json 
	rm -f local/nmdc-osm-enriched*.json
	rm -f local/nmdc-envo-normalized*.json
	rm -f local/nmdc-ai-map-enriched.json
	rm -f local/nmdc-llm-comparison.json
	rm -f local/nmdc-comparison-summary.json
	rm -f envo_lexical_index.yaml
	
# Clean test files but keep the main pipeline files
clean-test:
	rm -f local/nmdc-*-test*.json
	rm -f local/oak_ridge_*.json
	
# Documentation of available map types
# - hybrid: Combines satellite imagery with road labels
# - terrain: Already added - shows topographical features
# - Historical imagery: Available through Earth Engine APIs (separate service)