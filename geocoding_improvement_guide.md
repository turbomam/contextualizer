# Geocoding Improvement Strategies for NMDC Biosamples

## Analysis Summary
Your geocoding achieved a **45.7% success rate** (32/70 locations). The main failure patterns are:
- **Ocean/Water bodies**: 34% of failures (13/38)
- **Too specific/complex names**: 34% of failures (13/38) 
- **Country code format issues**: 11% of failures (4/38)
- **Specific geographic features**: 11% of failures (4/38)
- **Data quality issues**: 11% of failures (4/38)

## Key Strategies to Improve Success Rate

### 1. Preprocessing for Better Geocoding

#### A. Handle Country Code Formats
**Problem**: `DEU: Brandenburg`, `ISR: Golan Heights`, `KOR: Busan`, `NOR: Luster Municipality`
**Solution**: Convert ISO 3-letter codes to full country names
```python
country_code_map = {
    'DEU': 'Germany',
    'ISR': 'Israel', 
    'KOR': 'South Korea',
    'NOR': 'Norway',
    'USA': 'United States'
}

def fix_country_codes(location_string):
    for code, name in country_code_map.items():
        if location_string.startswith(f'{code}:'):
            return location_string.replace(f'{code}:', f'{name}:')
    return location_string
```

#### B. Simplify Ocean/Water Body References
**Problem**: Generic ocean references fail (e.g., "Northeast Atlantic Ocean", "Mexico: North Pacific Ocean")
**Solution**: For marine locations, focus on the nearest land reference
```python
def simplify_marine_locations(location_string):
    # Remove generic ocean references and keep specific features
    if 'Ocean:' in location_string and any(feature in location_string for feature in ['Basin', 'Ridge', 'Seamount']):
        return location_string  # Keep specific marine features
    elif 'Ocean' in location_string or 'Sea' in location_string:
        # Extract country/region part only
        parts = location_string.split(':')
        if len(parts) > 1:
            return parts[0].strip()  # Return just the country
    return location_string
```

#### C. Clean Up Redundant Information
**Problem**: `Puerto Rico: Adjuntas, Adjuntas`, `Puerto Rico: Naguabo, Naguabo`
**Solution**: Remove duplicate location names
```python
def remove_redundant_names(location_string):
    parts = location_string.split(':')
    if len(parts) == 2:
        country, places = parts[0].strip(), parts[1].strip()
        place_parts = [p.strip() for p in places.split(',')]
        # Remove duplicates while preserving order
        unique_places = []
        for place in place_parts:
            if place not in unique_places:
                unique_places.append(place)
        return f"{country}: {', '.join(unique_places)}"
    return location_string
```

#### D. Fix Common Typos and Misspellings
**Problem**: `Thailand: Chiang Ma` (should be Chiang Mai), `Brazil: Obidos` (should be Óbidos)
**Solution**: Create a correction dictionary
```python
typo_corrections = {
    'Chiang Ma': 'Chiang Mai',
    'Obidos': 'Óbidos',
    'Massachusettes': 'Massachusetts',
    # Add more as you identify them
}

def fix_typos(location_string):
    for typo, correction in typo_corrections.items():
        location_string = location_string.replace(typo, correction)
    return location_string
```

### 2. Multi-Step Geocoding Strategy

#### A. Hierarchical Fallback Approach
```python
def hierarchical_geocode(location_string, geocoder):
    """Try multiple versions of the location string"""
    variants = []
    
    # Original string
    variants.append(location_string)
    
    # Remove research station/facility names
    simplified = re.sub(r'\b(Research Station|Field Station|Experimental Range|Biological Station)\b', '', location_string)
    variants.append(simplified.strip())
    
    # Just the main location (remove specific features)
    parts = location_string.split(':')
    if len(parts) == 2:
        country = parts[0].strip()
        places = parts[1].strip().split(',')
        
        # Try country + first place
        variants.append(f"{country}: {places[0].strip()}")
        
        # Try country + last place
        if len(places) > 1:
            variants.append(f"{country}: {places[-1].strip()}")
        
        # Try just the country
        variants.append(country)
    
    # Try each variant
    for variant in variants:
        try:
            result = geocoder.geocode(variant)
            if result:
                return result, variant
        except:
            continue
    
    return None, None
```

#### B. Use Multiple Geocoding Services
```python
from geopy.geocoders import Nominatim, GoogleV3, ArcGIS, GeoNames

def multi_service_geocode(location_string):
    """Try multiple geocoding services"""
    geocoders = [
        Nominatim(user_agent="nmdc_geocoder"),
        ArcGIS(),
        # GoogleV3(api_key='your_key'),  # If you have API key
        # GeoNames(username='your_username')  # If you have account
    ]
    
    for geocoder in geocoders:
        try:
            result = geocoder.geocode(location_string)
            if result:
                return result, geocoder.__class__.__name__
        except:
            continue
    
    return None, None
```

### 3. Feature-Specific Handling

#### A. Research Stations and Protected Areas
Many locations are research facilities that might not be in standard geocoding databases.
```python
def handle_research_facilities(location_string):
    """For research stations, try the general area instead"""
    if any(keyword in location_string.lower() for keyword in ['field station', 'research', 'experimental', 'biological station']):
        # Extract the geographic region
        parts = location_string.split(':')
        if len(parts) == 2:
            country = parts[0].strip()
            # Remove facility-specific terms and try geocoding the area
            area = re.sub(r'\b(Research Station|Field Station|Experimental Range|Biological Station|National Forest)\b', '', parts[1])
            area = re.sub(r'\s+', ' ', area).strip()
            return f"{country}: {area}"
    return location_string
```

#### B. Water Bodies and Marine Locations
```python
def handle_marine_locations(location_string):
    """Special handling for marine/aquatic locations"""
    marine_keywords = ['Ocean', 'Sea', 'Bay', 'Gulf', 'Sound', 'Strait']
    
    if any(keyword in location_string for keyword in marine_keywords):
        # For specific named features (reefs, basins), try searching with quotes
        if any(feature in location_string for feature in ['Reef', 'Basin', 'Ridge', 'Seamount', 'Atoll']):
            # Extract the specific feature name
            parts = location_string.split(':')
            if len(parts) == 2:
                feature_part = parts[1].strip()
                # Try geocoding just the specific feature
                return f'"{feature_part}"'  # Quotes for exact match
    
    return location_string
```

### 4. Alternative Data Sources

#### A. Use Specialized Databases
```python
# For marine locations, consider using marine gazetteer APIs
def query_marine_gazetteer(location_string):
    """Query marine-specific databases"""
    # Example: GEBCO Gazetteer, VLIZ Marine Regions, etc.
    # Implementation depends on available APIs
    pass

# For protected areas and research stations
def query_protected_areas_db(location_string):
    """Query protected areas databases"""
    # Example: WDPA (World Database on Protected Areas)
    # GBIF dataset locations
    pass
```

#### B. Use GBIF/Scientific Institution Databases
Many of your locations are from scientific institutions. Consider:
- GBIF (Global Biodiversity Information Facility) dataset locations
- LTER (Long Term Ecological Research) site coordinates
- National park and protected area databases

### 5. Manual Curation for High-Value Locations

For frequently used locations (high `count` values), consider manual curation:

**High Priority Manual Geocoding** (based on count > 50):
- `Australia: Queensland, Great Barrier Reef, Davies Reef` (count: 51)
- `USA: Alaska, Caribou-Poker Creeks Research Watershed` (count: 129)
- `USA: California, San Joaquin Experimental Range` (count: 118)
- `USA: Alabama, Talladega National Forest` (count: 173)

### 6. Complete Preprocessing Pipeline

```python
def preprocess_location_string(location_string):
    """Complete preprocessing pipeline"""
    # Step 1: Fix country codes
    location_string = fix_country_codes(location_string)
    
    # Step 2: Fix typos
    location_string = fix_typos(location_string)
    
    # Step 3: Remove redundant information
    location_string = remove_redundant_names(location_string)
    
    # Step 4: Handle marine locations
    location_string = handle_marine_locations(location_string)
    
    # Step 5: Handle research facilities
    location_string = handle_research_facilities(location_string)
    
    return location_string

def improved_geocoding_pipeline(location_string, geocoder):
    """Complete improved geocoding pipeline"""
    # Preprocess
    processed_string = preprocess_location_string(location_string)
    
    # Try hierarchical geocoding
    result, used_variant = hierarchical_geocode(processed_string, geocoder)
    
    if result:
        return {
            'original': location_string,
            'processed': processed_string,
            'used_variant': used_variant,
            'latitude': result.latitude,
            'longitude': result.longitude,
            'status': 'success'
        }
    
    # If still failed, try multi-service approach
    result, service = multi_service_geocode(processed_string)
    
    if result:
        return {
            'original': location_string,
            'processed': processed_string,
            'service': service,
            'latitude': result.latitude,
            'longitude': result.longitude,
            'status': 'success'
        }
    
    return {
        'original': location_string,
        'processed': processed_string,
        'latitude': None,
        'longitude': None,
        'status': 'failed'
    }
```

## 7. Expected Improvements by Pattern

### Ocean/Water Bodies (13 failures → ~8 expected successes)
- **Current failures**: Generic ocean references
- **Strategy**: Focus on land-based references, use marine gazetteers
- **Example**: "Mexico: North Pacific Ocean" → "Mexico" (should geocode successfully)

### Country Code Issues (4 failures → 4 expected successes)
- **Current failures**: ISO codes not recognized
- **Strategy**: Convert to full country names
- **Example**: "DEU: Brandenburg" → "Germany: Brandenburg" (should work, since "Germany: Brandenburg" already succeeds)

### Specific Features (4 failures → 2-3 expected successes)
- **Current failures**: Basins, glaciers not in standard databases
- **Strategy**: Use broader geographic context
- **Example**: "Mexico: Cuatro Cienegas Basin" → "Mexico: Cuatro Cienegas"

### Data Quality Issues (4 failures → 3-4 expected successes)
- **Current failures**: Typos, redundant names
- **Strategy**: Preprocessing corrections
- **Example**: "Thailand: Chiang Ma" → "Thailand: Chiang Mai"

## 8. Tools Beyond Nominatim

### A. Alternative Geocoding Services
```python
# Google Maps Geocoding API (paid, but very comprehensive)
from geopy.geocoders import GoogleV3
google_geocoder = GoogleV3(api_key='your_api_key')

# ArcGIS (free tier available)
from geopy.geocoders import ArcGIS
arcgis_geocoder = ArcGIS()

# GeoNames (free with registration)
from geopy.geocoders import GeoNames
geonames_geocoder = GeoNames(username='your_username')
```

### B. Specialized APIs for Scientific Locations
```python
# GBIF API for biodiversity research locations
import requests

def query_gbif_dataset_location(location_name):
    """Query GBIF for dataset coordinates"""
    url = "https://api.gbif.org/v1/dataset/search"
    params = {'q': location_name, 'type': 'SAMPLING_EVENT'}
    response = requests.get(url, params=params)
    # Parse response for coordinate information
    return response.json()

# LTER Network locations
def query_lter_sites(location_name):
    """Query Long Term Ecological Research network"""
    # LTER sites have well-documented coordinates
    # Implementation would depend on LTER data access
    pass
```

### C. Manual Coordinate Lookup Resources
For the most problematic locations, consider these resources:
- **GeoNames.org**: Manual search interface
- **Google Earth**: Visual identification and coordinate extraction
- **GBIF.org**: Search for datasets from specific locations
- **Research station websites**: Many publish their coordinates
- **Scientific papers**: Often include site coordinates in methods sections

## 9. Quality Assurance Strategies

### A. Coordinate Validation
```python
def validate_coordinates(lat, lon, expected_country=None):
    """Validate that coordinates make sense"""
    # Basic range checks
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return False
    
    # Reverse geocode to check country match
    if expected_country:
        try:
            reverse_result = geocoder.reverse(f"{lat}, {lon}")
            if reverse_result and expected_country.lower() in reverse_result.address.lower():
                return True
        except:
            pass
    
    return True  # If no country check or check passes
```

### B. Confidence Scoring
```python
def calculate_confidence_score(original, processed, result):
    """Calculate confidence in geocoding result"""
    score = 0.5  # Base score
    
    # Bonus for exact matches
    if original.lower() == processed.lower():
        score += 0.2
    
    # Bonus for specific coordinates (not country centroid)
    if result and hasattr(result, 'raw'):
        if 'exact' in str(result.raw).lower():
            score += 0.3
    
    # Penalty for major modifications
    if len(processed) < len(original) * 0.5:
        score -= 0.2
    
    return min(1.0, max(0.0, score))
```

## 10. Implementation Priority

1. **High Impact, Low Effort**: 
   - Fix country code formats (4 immediate successes)
   - Fix obvious typos (2-3 immediate successes)

2. **Medium Impact, Medium Effort**:
   - Implement hierarchical fallback geocoding
   - Add ArcGIS as secondary geocoder

3. **High Impact, High Effort**:
   - Manual curation of high-count failed locations
   - Integration with specialized marine/research databases

4. **Long-term Improvements**:
   - Build custom gazetteer for commonly used research sites
   - Collaborate with NMDC community to maintain location database

## Expected Overall Improvement

With these strategies, you could expect to improve from **45.7% to 75-85% success rate**:
- Country codes: +4 successes
- Typo fixes: +3 successes  
- Ocean simplification: +6-8 successes
- Hierarchical fallback: +3-5 additional successes

This would bring you from 32/70 successful to approximately 48-55/70 successful geocoding attempts.