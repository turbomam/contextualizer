#!/usr/bin/env python3
"""
Normalize OpenStreetMap features to Environment Ontology (EnvO) terms.

This script processes NMDC biosamples that have been enriched with OpenStreetMap 
features and maps these features to standardized EnvO terms. It uses the OAK 
(Ontology Access Kit) to properly interact with the EnvO ontology through native 
methods, not SQL queries. A PydanticAI agent with specialized tools is used to 
make intelligent mapping decisions.
"""

import json
import logging
import os
import re
import click
import random
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from tqdm import tqdm
from time import sleep
from dataclasses import dataclass
import asyncio
from datetime import datetime

# PydanticAI imports
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

# Feature aggregation
from src.utils.feature_aggregation import analyze_feature_density, FeatureAggregation

# OAK imports
from oaklib import get_adapter
from oaklib.datamodels.text_annotator import TextAnnotationConfiguration
from oaklib.utilities.lexical.lexical_indexer import (
    load_lexical_index,
    create_lexical_index,
    save_lexical_index
)

# Load environment variables
from dotenv import load_dotenv
load_dotenv(verbose=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
MIN_ANNOTATION_LENGTH = 4  # Minimum length for text annotations
MIN_LABEL_LENGTH = 3    # Minimum length for EnvO term labels
MAX_FEATURE_DISTANCE = 850  # Maximum distance in meters for feature consideration
LEX_INDEX_FILE = "envo_lexical_index.yaml"
CONFIDENCE_THRESHOLD = 0.7

class OSMFeature(BaseModel):
    """OpenStreetMap feature extracted from the enriched biosample data"""
    feature_id: str = Field(..., description="OSM identifier for the feature")
    feature_type: str = Field(..., description="Type of the feature (e.g., 'natural:water')")
    tags: Dict[str, str] = Field(..., description="OSM tags with environmental relevance")
    coordinates: Tuple[float, float] = Field(..., description="Latitude and longitude")
    distance_from_center: float = Field(..., description="Distance in meters from the sample location")
    area: Optional[float] = Field(None, description="Area of the feature in square meters if available")

class EnvOMapping(BaseModel):
    """Mapping from an OSM feature to an EnvO term"""
    envo_id: str = Field(..., pattern=r"^ENVO:\d{8}$", description="EnvO identifier (format: ENVO:XXXXXXXX)")
    envo_label: str = Field(..., min_length=1, description="Human-readable EnvO term label")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0")
    reasoning: str = Field(..., min_length=10, description="Explanation for the mapping decision")
    feature_id: str = Field(..., description="ID of the OSM feature being mapped")
    feature_type: str = Field(..., description="Type of the OSM feature being mapped")
    distance: float = Field(..., description="Distance from the sample location in meters")
    nmdc_field: Optional[str] = Field(None, description="Suggested NMDC field this mapping corresponds to (env_broad_scale, env_local_scale, or env_medium)")
    nmdc_field_confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="Confidence in the NMDC field assignment")

class EnvOLookupResult(BaseModel):
    """Result of an EnvO term lookup"""
    id: str = Field(..., description="EnvO ID (e.g., 'ENVO:00000097')")
    label: str = Field(..., description="Human-readable label for the EnvO term")
    is_obsolete: bool = Field(False, description="Whether the term is marked as obsolete")
    definition: Optional[str] = Field(None, description="Definition of the term if available")

class TextAnnotationResult(BaseModel):
    """Result of text annotation with EnvO terms"""
    text: str = Field(..., description="Original text that was annotated")
    matches: List[Dict[str, Any]] = Field(..., description="EnvO terms found in the text")
    coverage: float = Field(..., ge=0.0, le=1.0, description="Proportion of text covered by annotations")

class EnvOHelper:
    """Helper class for EnvO ontology operations using OAK"""
    
    def __init__(self):
        """Initialize the EnvO helper with OAK adapter"""
        # Use OAK SQLite implementation for EnvO
        logger.info("Initializing EnvO helper with OAK SQLite adapter")
        self.adapter = get_adapter("sqlite:obo:envo")
        
        # Configure text annotation
        self.annotation_config = TextAnnotationConfiguration()
        self.annotation_config.match_whole_words_only = True
        
        # Load or create lexical index
        self._load_lexical_index()
    
    def _load_lexical_index(self):
        """Load existing lexical index or create a new one"""
        try:
            self.lexical_index = load_lexical_index(LEX_INDEX_FILE)
            logger.info(f"Loaded existing lexical index from {LEX_INDEX_FILE}")
        except FileNotFoundError:
            logger.info(f"Creating new lexical index for EnvO")
            self.lexical_index = create_lexical_index(self.adapter)
            save_lexical_index(self.lexical_index, LEX_INDEX_FILE)
            logger.info(f"Saved new lexical index to {LEX_INDEX_FILE}")
    
    def get_term_info(self, envo_id: str) -> Optional[EnvOLookupResult]:
        """
        Get information about an EnvO term by ID.
        
        Args:
            envo_id: EnvO identifier (e.g., 'ENVO:00000097')
            
        Returns:
            EnvOLookupResult with term details or None if term not found
        """
        try:
            # Normalize to uppercase prefix
            envo_id = envo_id.replace("envo:", "ENVO:")
            
            # Check if term exists
            if envo_id not in self.adapter.entities():
                return EnvOLookupResult(
                    id=envo_id,
                    label="TERM NOT FOUND",
                    is_obsolete=False,
                    definition=None
                )
            
            # Get label
            try:
                # Debug logging to understand what's being returned by the adapter
                labels = list(self.adapter.labels(envo_id))
                logger.debug(f"Raw labels for {envo_id}: {labels}")
                
                # Convert tuple to string if needed
                if labels and isinstance(labels[0], tuple):
                    raw_label = str(labels[0][0]) if labels[0][0] else None
                    logger.debug(f"Extracted label from tuple for {envo_id}: '{raw_label}'")
                else:
                    raw_label = str(labels[0]) if labels else None
                    logger.debug(f"Direct label for {envo_id}: '{raw_label}'")
                
                # Validate label length and content
                if not raw_label:
                    logger.warning(f"No primary label found for {envo_id}")
                    use_alternative = True
                elif len(raw_label.strip()) < MIN_LABEL_LENGTH:
                    logger.warning(f"Primary label for {envo_id} is too short: '{raw_label}' (min length: {MIN_LABEL_LENGTH})")
                    use_alternative = True
                elif raw_label.strip() in ["E", "e", "C", "c"]:
                    logger.warning(f"Primary label for {envo_id} appears invalid: '{raw_label}'")
                    use_alternative = True
                else:
                    use_alternative = False
                    
                if use_alternative:
                    # Try to get alternative labels if primary is invalid
                    try:
                        alt_labels = list(self.adapter.entity_aliases(envo_id))
                        logger.debug(f"Alternative labels for {envo_id}: {alt_labels}")
                        
                        # Filter for valid alternative labels
                        valid_alt_labels = [l for l in alt_labels if isinstance(l, str) and len(l.strip()) >= MIN_LABEL_LENGTH]
                        
                        if valid_alt_labels:
                            label = valid_alt_labels[0]
                            logger.info(f"Using alternative label '{label}' for {envo_id} (primary label '{raw_label}' invalid or too short)")
                            
                            # Log all available alternatives for debugging
                            if len(valid_alt_labels) > 1:
                                logger.debug(f"Other valid alternatives for {envo_id}: {valid_alt_labels[1:]}")
                        else:
                            # If no valid alt labels, use the ID as a fallback
                            label = f"Term {envo_id}"
                            logger.warning(f"No valid labels found for {envo_id}, using ID as label. Raw alt_labels: {alt_labels}")
                    except Exception as e:
                        logger.warning(f"Error getting alternative labels for {envo_id}: {e}")
                        label = f"Term {envo_id}"
                else:
                    label = raw_label
                    
            except Exception as e:
                logger.warning(f"Error getting label for {envo_id}: {e}")
                label = f"Term {envo_id}"
                
            # Check if obsolete - handle SQLite implementation that may not have is_obsolete
            is_obsolete = False  # Default to not obsolete
            
            # Get definition if available
            try:
                definitions = list(self.adapter.definitions(envo_id))
                definition = str(definitions[0]) if definitions else None
                # Handle tuple definitions
                if isinstance(definition, tuple) and definition:
                    definition = str(definition[0])
            except Exception:
                definition = None
            
            return EnvOLookupResult(
                id=envo_id,
                label=label,
                is_obsolete=is_obsolete,
                definition=definition
            )
            
        except Exception as e:
            logger.warning(f"Error getting info for {envo_id}: {e}")
            # Return a placeholder result instead of None to prevent downstream errors
            return EnvOLookupResult(
                id=envo_id,
                label="TERM NOT FOUND",
                is_obsolete=False,
                definition=None
            )
    
    def is_true_whole_word_match(self, text: str, match_string: str) -> bool:
        """Verify if match_string occurs as a complete word"""
        words = re.findall(r"\b\w+\b", text.lower())
        return match_string.lower() in words
    
    def filter_annotations(self, annotations, text):
        """Filter annotations based on quality criteria"""
        filtered = []
        for ann in annotations:
            # Get the match string
            match_string = getattr(ann, "match_string", None)
            
            # Skip if match_string is None or empty
            if not match_string or len(match_string.strip()) == 0:
                continue
                
            # Skip too-short annotations
            if hasattr(ann, "subject_start") and hasattr(ann, "subject_end"):
                ann_length = ann.subject_end - ann.subject_start + 1
                if ann_length < MIN_ANNOTATION_LENGTH:
                    logger.debug(f"Skipping annotation '{match_string}' - too short ({ann_length} chars)")
                    continue
            
            # Skip very short match strings directly
            if len(match_string.strip()) < MIN_ANNOTATION_LENGTH:
                logger.debug(f"Skipping annotation '{match_string}' - match string too short")
                continue
                
            # Skip single-character matches (even if they're technically longer due to whitespace)
            if len(match_string.strip()) <= 1:
                logger.debug(f"Skipping annotation '{match_string}' - single character match")
                continue
                
            # Ensure whole word matches for single words
            if match_string and " " not in match_string:
                if not self.is_true_whole_word_match(text, match_string):
                    logger.debug(f"Skipping annotation '{match_string}' - not a whole word match")
                    continue
            
            # Skip matches that are just common words or abbreviations
            skip_terms = ["e", "a", "an", "the", "and", "of", "in", "on", "at"]
            if match_string.lower() in skip_terms:
                logger.debug(f"Skipping common word annotation '{match_string}'")
                continue
            
            filtered.append(ann)
        return filtered
    
    def compute_annotation_coverage(self, annotations, text_length):
        """Calculate what percentage of text is covered by annotations"""
        if not annotations or text_length == 0:
            return 0
            
        intervals = []
        for ann in annotations:
            if hasattr(ann, "subject_start") and hasattr(ann, "subject_end"):
                intervals.append((ann.subject_start, ann.subject_end))
                
        if not intervals:
            return 0
            
        # Merge overlapping intervals
        intervals.sort(key=lambda x: x[0])
        merged = []
        current_start, current_end = intervals[0]
        
        for start, end in intervals[1:]:
            if start <= current_end + 1:  # Adjacent or overlapping
                current_end = max(current_end, end)
            else:
                merged.append((current_start, current_end))
                current_start, current_end = start, end
                
        merged.append((current_start, current_end))
        
        total_covered = sum(end - start + 1 for start, end in merged)
        return total_covered / text_length
    
    def annotate_text(self, text: str) -> TextAnnotationResult:
        """
        Find EnvO terms in text using OAK annotation.
        
        Args:
            text: Text to annotate with EnvO terms
            
        Returns:
            TextAnnotationResult with matches and coverage metrics
        """
        try:
            # Get text annotations
            annotations = self.adapter.annotate_text(
                text, configuration=self.annotation_config
            )
            
            # Filter and process annotations
            filtered = self.filter_annotations(annotations, text)
            
            # Calculate coverage
            coverage = self.compute_annotation_coverage(filtered, len(text))
            
            # Convert to structured format
            matches = []
            for ann in filtered:
                term_id = ann.object_id
                if term_id.startswith("ENVO:"):
                    label = list(self.adapter.labels(term_id))[0]
                    matches.append({
                        "id": term_id,
                        "label": label,
                        "match": ann.match_string,
                        "start": ann.subject_start,
                        "end": ann.subject_end
                    })
            
            return TextAnnotationResult(
                text=text,
                matches=matches,
                coverage=coverage
            )
            
        except Exception as e:
            logger.error(f"Error annotating text: {e}")
            return TextAnnotationResult(
                text=text,
                matches=[],
                coverage=0.0
            )

class EnvoNormalizerAgent(Agent):
    """PydanticAI agent for mapping OSM features to EnvO terms."""
    
    def __init__(self):
        """Initialize the EnvO normalizer agent with OAK helper and model."""
        self.envo_helper = EnvOHelper()
        super().__init__(
            OpenAIModel(
                "anthropic/claude-sonnet",
                provider=OpenAIProvider(
                    base_url="https://api.cborg.lbl.gov",
                    api_key=os.getenv("CBORG_API_KEY"),
                )
            ),
            system_prompt="""You are an expert in environmental ontology helping to map geographical features 
            from OpenStreetMap to standardized Environment Ontology (EnvO) terms for NMDC biosamples.
            
            Your task is to analyze OSM features and determine the most appropriate EnvO term 
            for each feature, considering:
            1. The primary feature type (e.g., 'natural:water', 'landuse:forest')
            2. All relevant OSM tags describing the feature
            3. The distance from the point of interest
            4. Any relevant EnvO terms found in the feature description
            5. The biosample's existing EnvO terms (if provided)
            
            In NMDC biosamples, there are three important environmental fields:
            - env_broad_scale: The broad-scale environment context (e.g., biomes, large environmental systems)
            - env_local_scale: The local environment context (e.g., habitats, ecosystems)
            - env_medium: The environmental material (e.g., soil, water, air, sediment)
            
            When selecting an EnvO term:
            - Prefer terms that match the feature's environmental character
            - Consider how the feature would influence the local environment
            - Only use terms that exist in the EnvO ontology
            - Provide a confidence score based on how well the mapping fits
            - Explain your reasoning clearly
            - Suggest which NMDC field (env_broad_scale, env_local_scale, env_medium) this term would be appropriate for
            
            For features very far from the sample location (>500m), reduce confidence
            unless they are likely to have broad environmental impact.
            """
        )
    
    @Agent.tool
    def get_envo_term(self, ctx: RunContext, envo_id: str) -> EnvOLookupResult:
        """
        Look up information about an EnvO term by ID.
        
        Args:
            envo_id: The EnvO identifier to look up (e.g., 'ENVO:00000097')
            
        Returns:
            Information about the EnvO term including label, obsolete status, and definition
        """
        result = self.envo_helper.get_term_info(envo_id)
        if not result:
            return EnvOLookupResult(
                id=envo_id,
                label="TERM NOT FOUND",
                is_obsolete=False,
                definition=None
            )
        return result
    
    @Agent.tool
    def annotate_text_with_envo(self, ctx: RunContext, text: str) -> TextAnnotationResult:
        """
        Find EnvO terms in text using the EnvO ontology.
        
        Args:
            text: Text to analyze for environmental terms
            
        Returns:
            EnvO terms found in the text with their positions and coverage metrics
        """
        return self.envo_helper.annotate_text(text)
    
    @Agent.tool
    def search_envo_terms(self, ctx: RunContext, query: str, max_results: int = 5) -> List[EnvOLookupResult]:
        """
        Search for EnvO terms matching a query string.
        
        Args:
            query: Search string to find matching EnvO terms
            max_results: Maximum number of results to return (default: 5)
            
        Returns:
            List of matching EnvO terms with their details
        """
        results = []
        try:
            # Use basic search functionality
            search_results = self.envo_helper.adapter.basic_search(query)
            
            # Get full details for each result
            for term_id in list(search_results)[:max_results]:
                term_info = self.envo_helper.get_term_info(term_id)
                if term_info and not term_info.is_obsolete:
                    results.append(term_info)
            
            return results
        except Exception as e:
            logger.error(f"Error searching for '{query}': {e}")
            return []
    
    async def map_feature_to_envo(self, feature: OSMFeature, biosample_id: str = "unknown", 
                            biosample_coords: Tuple[float, float] = (None, None),
                            biosample_env_terms: Optional[Dict[str, Dict[str, str]]] = None) -> Optional[EnvOMapping]:
        """
        Map an OSM feature to the most appropriate EnvO term.
        
        Args:
            feature: OSM feature to map
            biosample_id: ID of the biosample being processed
            biosample_coords: Coordinates (lat, lon) of the biosample
            biosample_env_terms: Existing environment terms in the biosample (optional)
            
        Returns:
            EnvO mapping with confidence and reasoning
        """
        try:
            # Log context information for this mapping process
            lat, lon = biosample_coords
            logger.info(f"Processing EnvO mapping for biosample {biosample_id} at location {lat}, {lon}")
            logger.info(f"OSM feature: {feature.feature_id} ({feature.feature_type}) at distance {feature.distance_from_center}m")
            
            # Step 1: Create feature description
            feature_desc = (
                f"OSM Feature Type: {feature.feature_type}\n"
                f"Distance from sample: {feature.distance_from_center} meters\n"
                f"Tags: {feature.tags}\n"
            )
            
            # Step 2: First, proactively search for relevant EnvO terms using OAK
            feature_type_parts = feature.feature_type.split(':')
            search_terms = []
            
            # Extract search terms from feature type and tags
            if len(feature_type_parts) > 1:
                search_terms.append(feature_type_parts[1])  # e.g., "tree" from "natural:tree"
                # Also add more general terms for common OSM features
                if feature_type_parts[1] == "tree":
                    search_terms.extend(["forest", "woodland", "vegetation"])
                elif feature_type_parts[1] == "water":
                    search_terms.extend(["lake", "pond", "river", "stream", "aquatic"])
                elif feature_type_parts[1] == "beach":
                    search_terms.extend(["coast", "shore", "sand"])
                elif feature_type_parts[1] == "wood":
                    search_terms.extend(["forest", "woodland", "vegetation"])
            
            # Add the main category as a search term
            if len(feature_type_parts) > 0:
                search_terms.append(feature_type_parts[0])  # e.g., "natural" from "natural:tree"
                # Add appropriate general environmental terms based on category
                if feature_type_parts[0] == "natural":
                    search_terms.extend(["habitat", "ecosystem", "biome", "environment"])
                elif feature_type_parts[0] == "landuse":
                    search_terms.extend(["land use", "anthropogenic", "managed"])
                elif feature_type_parts[0] == "waterway":
                    search_terms.extend(["aquatic", "freshwater", "water body"])
            
            # Add important tags as search terms
            for key, value in feature.tags.items():
                search_terms.append(value)
                
            # Add some general search terms that apply to most features
            search_terms.extend(["environmental feature", "geographical feature"])
            
            # Get context from biosample's asserted environment terms
            env_context = ""
            if biosample_env_terms:
                env_context = "\nExisting biosample environment terms:\n"
                for field, term in biosample_env_terms.items():
                    env_context += f"- {field}: {term['id']} ({term['name']})\n"
                logger.info(f"Biosample {biosample_id} has existing environment terms: {biosample_env_terms}")
            
            # Step 3: Collect valid EnvO terms using OAK directly
            valid_terms = []
            logger.info(f"Biosample {biosample_id}: Searching for EnvO terms for feature {feature.feature_id} ({feature.feature_type})")
            logger.info(f"Biosample {biosample_id}: Search terms: {search_terms}")
            
            for term in search_terms:
                try:
                    # Use OAK basic search directly
                    search_results = self.envo_helper.adapter.basic_search(term)
                    result_list = list(search_results)
                    
                    if result_list:
                        logger.info(f"Biosample {biosample_id}: Found {len(result_list)} results for search term '{term}'")
                        # Get term info for top 5 results
                        for term_id in result_list[:5]:
                            term_info = self.envo_helper.get_term_info(term_id)
                            # Validate term has a proper label (not just "E" or "Term X")
                            if (term_info and 
                                term_info.label != "TERM NOT FOUND" and 
                                not term_info.label.startswith("Term ") and
                                len(term_info.label) >= MIN_LABEL_LENGTH and
                                term_info.label.strip() not in ["E", "e"]):
                                logger.info(f"  Biosample {biosample_id}: - {term_id} ({term_info.label})")
                                valid_terms.append(term_info)
                    else:
                        logger.info(f"Biosample {biosample_id}: No results found for search term '{term}'")
                        
                except Exception as e:
                    logger.warning(f"Error searching for '{term}': {e}")
            
            # Step 4: Use text annotation to find more terms
            annotation_result = self.envo_helper.annotate_text(feature_desc)
            
            # Add annotation matches to valid terms
            for match in annotation_result.matches:
                term_id = match['id']
                term_info = self.envo_helper.get_term_info(term_id)
                # Apply same validation as for search results
                if (term_info and 
                    term_info.label != "TERM NOT FOUND" and 
                    not term_info.label.startswith("Term ") and
                    len(term_info.label) >= MIN_LABEL_LENGTH and
                    term_info.label.strip() not in ["E", "e"]):
                    logger.info(f"  - Found annotation: {term_id} ({term_info.label})")
                    valid_terms.append(term_info)
            
            # Deduplicate terms
            unique_terms = {}
            for term in valid_terms:
                if term.id not in unique_terms:
                    unique_terms[term.id] = term
            
            valid_terms = list(unique_terms.values())
            
            # If no valid terms found, add fallback generic EnvO terms
            if not valid_terms:
                logger.warning(f"No valid EnvO terms found for feature {feature.feature_id} - adding fallbacks")
                
                # Add some generic fallback terms based on feature type
                fallback_terms = []
                
                # Common generic EnvO terms that exist in most EnvO versions
                generic_terms = [
                    "ENVO:00010483",  # environmental material
                    "ENVO:00002297",  # environmental feature
                    "ENVO:00000428",  # biome
                    "ENVO:01000254",  # geographic feature
                    "ENVO:00002003",  # natural material
                    "ENVO:00000337",  # habitat
                ]
                
                # Try to get these generic terms
                for term_id in generic_terms:
                    term_info = self.envo_helper.get_term_info(term_id)
                    if term_info and term_info.label != "TERM NOT FOUND":
                        fallback_terms.append(term_info)
                        logger.info(f"Added fallback term: {term_id} ({term_info.label})")
                
                # If we found any fallback terms, use them
                if fallback_terms:
                    valid_terms = fallback_terms
                else:
                    logger.error(f"No fallback terms could be found - cannot map feature {feature.feature_id}")
                    return None
            
            # Step 5: Format for LLM to make a selection from valid terms
            terms_text = "\nValid EnvO terms found for this feature:\n"
            for i, term in enumerate(valid_terms):
                definition = f" - {term.definition}" if term.definition else ""
                terms_text += f"{i+1}. {term.id} ({term.label}){definition}\n"
            
            # Step 6: Have the LLM select from the valid terms
            query = f"""Analyze this OpenStreetMap feature and select the most appropriate EnvO term from the list provided:

Feature Description:
{feature_desc}
{env_context}

{terms_text}

Your task:
1. Select ONE term from the numbered list above that best represents this geographical feature's environmental significance
2. Determine which NMDC environmental field this term would be most appropriate for:
   - env_broad_scale: The broad-scale environment context (e.g., biomes, large environmental systems)
   - env_local_scale: The local environment context (e.g., habitats, ecosystems)
   - env_medium: The environmental material (e.g., soil, water, air, sediment)

Respond with a JSON object containing:
1. selection: The number of your selected term from the list (e.g., 1, 2, 3)
2. confidence: A score between 0.0 and 1.0 indicating your confidence in this selection
3. reasoning: Your explanation for why this EnvO term is appropriate
4. nmdc_field: The NMDC field this term would be most appropriate for
5. nmdc_field_confidence: A score between 0.0 and 1.0 indicating your confidence in the field assignment

JSON format:
{{
  "selection": 1,
  "confidence": 0.95,
  "reasoning": "explanation",
  "nmdc_field": "env_local_scale",
  "nmdc_field_confidence": 0.85
}}
"""
            
            # Get the agent's response
            result = await self.run(query)
            
            # Extract JSON from the response
            json_match = re.search(r'```json\s*(.*?)\s*```', result.data, re.DOTALL)
            if not json_match:
                json_match = re.search(r'{.*}', result.data, re.DOTALL)
            
            if not json_match:
                logger.warning(f"Could not extract JSON from response: {result.data[:100]}...")
                return None
                
            json_str = json_match.group(1) if json_match.group(0).startswith('```') else json_match.group(0)
            
            # Parse the mapping
            mapping_data = json.loads(json_str)
            
            # Get the selected term
            selection = mapping_data.get("selection", 1)
            if not isinstance(selection, int) or selection < 1 or selection > len(valid_terms):
                logger.warning(f"Invalid selection: {selection}")
                # Default to first term if selection is invalid
                selection = 1
            
            # Adjust to 0-based index
            selected_term = valid_terms[selection - 1]
            
            # Create the mapping with feature ID and type
            mapping = EnvOMapping(
                envo_id=selected_term.id,
                envo_label=selected_term.label,
                confidence=mapping_data.get("confidence", 0.5),
                reasoning=mapping_data.get("reasoning", "No reasoning provided"),
                feature_id=feature.feature_id,
                feature_type=feature.feature_type,
                distance=feature.distance_from_center,
                nmdc_field=mapping_data.get("nmdc_field"),
                nmdc_field_confidence=mapping_data.get("nmdc_field_confidence", 0.5)
            )
            
            return mapping
            
        except Exception as e:
            logger.error(f"Error mapping feature {feature.feature_id}: {e}")
            return None

# Function is no longer used - we process features directly in process_biosample

def extract_biosample_env_terms(biosample: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """
    Extract asserted environment terms from a biosample.
    
    Args:
        biosample: Dictionary containing biosample metadata
        
    Returns:
        Dictionary with environment terms by field
    """
    env_terms = {}
    
    # Extract environment terms
    for field in ['env_broad_scale', 'env_local_scale', 'env_medium']:
        if field in biosample:
            field_data = biosample[field]
            if isinstance(field_data, dict):
                if 'term' in field_data and isinstance(field_data['term'], dict):
                    env_terms[field] = {
                        'id': field_data['term'].get('id', ''),
                        'name': field_data['term'].get('name', '')
                    }
                elif 'has_raw_value' in field_data:
                    # Handle raw values that might be EnvO IDs
                    raw_val = field_data['has_raw_value']
                    if raw_val.startswith('ENVO_'):
                        # Convert ENVO_XXXXXXXX to ENVO:XXXXXXXX format
                        envo_id = raw_val.replace('ENVO_', 'ENVO:')
                        env_terms[field] = {
                            'id': envo_id,
                            'name': raw_val  # We don't have the name in this case
                        }
                    else:
                        env_terms[field] = {
                            'id': '',
                            'name': raw_val
                        }
    
    return env_terms

def extract_osm_features(biosample: Dict[str, Any], include_distant: bool = False) -> List[OSMFeature]:
    """
    Extract OSM features from a biosample's metadata.
    
    Args:
        biosample: Biosample dictionary with OSM features
        include_distant: Whether to include features beyond MAX_FEATURE_DISTANCE
                        (useful for feature aggregation analysis)
        
    Returns:
        List of OSM features as structured objects
    """
    features = []
    
    if 'osm_features' not in biosample:
        logger.warning(f"No OSM features found in biosample {biosample.get('id', 'unknown')}")
        return features
        
    # Log the feature metadata
    if 'metadata' in biosample['osm_features']:
        metadata = biosample['osm_features']['metadata']
        logger.info(f"OSM features metadata: total={metadata.get('total_features', 0)}, "
                   f"coords={metadata.get('query_coordinates', [])}")
        if 'feature_type_counts' in metadata:
            logger.info(f"Feature type counts: {metadata['feature_type_counts']}")
            
    # Get asserted environment terms for context
    env_terms = extract_biosample_env_terms(biosample)
    
    # Track categories to avoid duplicate processing
    processed_categories = set()
    
    # Process primary categories first (water, natural, landuse, etc.)
    primary_categories = ['water', 'natural', 'landuse', 'ecosystem', 'protected_area']
    
    # First pass: extract features from primary categories
    for category in primary_categories:
        if category in biosample['osm_features'].get('features', {}):
            processed_categories.add(category)
            category_features = biosample['osm_features']['features'][category]
            logger.info(f"Found {len(category_features)} features in category '{category}'")
            
            # For each feature in the category
            for feature_data in category_features:
                try:
                    # Extract coordinates
                    if isinstance(feature_data.get('coordinates'), list) and len(feature_data.get('coordinates')) == 2:
                        coordinates = tuple(feature_data['coordinates'])
                    else:
                        logger.warning(f"Invalid coordinates for feature {feature_data.get('id')}: {feature_data.get('coordinates')}")
                        continue
                    
                    # Get distance
                    distance = feature_data.get('distance_from_center', 0.0)
                    
                    # Create feature object
                    feature = OSMFeature(
                        feature_id=feature_data.get('id', f"unknown-{len(features)}"),
                        feature_type=feature_data.get('type', f"{category}:unknown"),
                        tags=feature_data.get('environmental_tags', {}),
                        coordinates=coordinates,
                        distance_from_center=distance,
                        area=feature_data.get('area')
                    )
                    
                    # Check if we should include this feature
                    if distance <= MAX_FEATURE_DISTANCE or include_distant:
                        features.append(feature)
                        logger.debug(f"Added feature {feature.feature_id}: {feature.feature_type} (distance: {distance}m)")
                    else:
                        logger.info(f"Skipping feature {feature.feature_id}: {feature.feature_type} - too far ({distance}m > {MAX_FEATURE_DISTANCE}m)")
                    
                except Exception as e:
                    logger.warning(f"Error processing feature: {e}")
                    continue
    
    # Second pass: extract features from remaining categories
    for category, category_features in biosample['osm_features'].get('features', {}).items():
        if category in processed_categories:
            continue
            
        processed_categories.add(category)
        logger.info(f"Found {len(category_features)} features in category '{category}'")
        
        for feature_data in category_features:
            try:
                # Extract coordinates
                if isinstance(feature_data.get('coordinates'), list) and len(feature_data.get('coordinates')) == 2:
                    coordinates = tuple(feature_data['coordinates'])
                else:
                    logger.warning(f"Invalid coordinates for feature {feature_data.get('id')}: {feature_data.get('coordinates')}")
                    continue
                
                # Get distance
                distance = feature_data.get('distance_from_center', 0.0)
                
                # Create feature object
                feature = OSMFeature(
                    feature_id=feature_data.get('id', f"unknown-{len(features)}"),
                    feature_type=feature_data.get('type', f"{category}:unknown"),
                    tags=feature_data.get('environmental_tags', {}),
                    coordinates=coordinates,
                    distance_from_center=distance,
                    area=feature_data.get('area')
                )
                
                # Check if we should include this feature
                if distance <= MAX_FEATURE_DISTANCE or include_distant:
                    features.append(feature)
                    logger.debug(f"Added feature {feature.feature_id}: {feature.feature_type} (distance: {distance}m)")
                else:
                    logger.info(f"Skipping feature {feature.feature_id}: {feature.feature_type} - too far ({distance}m > {MAX_FEATURE_DISTANCE}m)")
                    
            except Exception as e:
                logger.warning(f"Error processing feature: {e}")
                continue
    
    # Sort by distance
    features.sort(key=lambda f: f.distance_from_center)
    
    # Limit to a reasonable number of features, with bias toward diverse types
    if len(features) > 20:
        # Extract feature types
        feature_types = set(f.feature_type for f in features)
        
        # Keep at least one of each type
        selected_features = []
        for ftype in feature_types:
            type_features = [f for f in features if f.feature_type == ftype]
            # Take the closest one of each type
            if type_features:
                selected_features.append(type_features[0])
        
        # If we still have room, add more features based on distance
        remaining_slots = 20 - len(selected_features)
        if remaining_slots > 0:
            # Get features not already selected
            remaining_features = [f for f in features if f not in selected_features]
            # Sort by distance and take the closest ones
            remaining_features.sort(key=lambda f: f.distance_from_center)
            selected_features.extend(remaining_features[:remaining_slots])
            
        # Sort final selection by distance
        selected_features.sort(key=lambda f: f.distance_from_center)
        return selected_features
    
    return features

def analyze_feature_aggregations(features: List[OSMFeature]) -> List[FeatureAggregation]:
    """
    Analyze feature density to make inferences about broader environmental context.
    
    Args:
        features: List of OSM features
    
    Returns:
        List of environmental inferences from feature density
    """
    # Convert OSMFeature objects to dictionaries for analyze_feature_density
    feature_dicts = []
    for feature in features:
        feature_dicts.append({
            "feature_id": feature.feature_id,
            "feature_type": feature.feature_type,
            "distance_from_center": feature.distance_from_center,
            "tags": feature.tags
        })
    
    # Get aggregation inferences
    return analyze_feature_density(feature_dicts)

async def process_biosample(agent: EnvoNormalizerAgent, biosample: Dict[str, Any], 
                         max_features: int = 20) -> Dict[str, Any]:
    """
    Process a single biosample to add EnvO mappings for its OSM features.
    
    Args:
        agent: EnvO normalizer agent
        biosample: Dictionary containing biosample metadata with OSM features
        max_features: Maximum number of features to process
        
    Returns:
        Biosample dictionary enriched with EnvO mappings
    """
    # Create a copy of the biosample to avoid modifying the original
    enriched = biosample.copy()
    
    # Get biosample ID and coordinates
    biosample_id = biosample.get('id', 'unknown')
    
    # Extract coordinates
    lat, lon = None, None
    lat_lon = biosample.get('lat_lon', {})
    if isinstance(lat_lon, dict) and 'latitude' in lat_lon and 'longitude' in lat_lon:
        try:
            lat = float(lat_lon['latitude'])
            lon = float(lat_lon['longitude'])
        except (ValueError, TypeError):
            pass
    
    logger.info(f"Processing biosample {biosample_id} at coordinates: {lat}, {lon}")
    
    # Add a timestamp
    enriched['envo_mapping_debug'] = {
        'processed_at': datetime.now().isoformat(),
        'status': 'Processing started'
    }
    
    # Initialize empty mappings
    enriched['envo_mappings'] = {}
    enriched['envo_mappings_by_field'] = {
        'env_broad_scale': [],
        'env_local_scale': [],
        'env_medium': []
    }
    
    # Add field for feature aggregation inferences
    enriched['feature_aggregations'] = []
    
    # Initialize stats
    enriched['envo_mapping_stats'] = {
        'total_features_processed': 0,
        'features_with_mappings': 0,
        'mapping_coverage': 0.0,
        'confidence_threshold': CONFIDENCE_THRESHOLD,
        'field_coverage': {
            'env_broad_scale': False,
            'env_local_scale': False,
            'env_medium': False
        },
        'agreement_with_asserted': {
            'env_broad_scale': False,
            'env_local_scale': False,
            'env_medium': False
        },
        'aggregation_inferences': 0
    }
    
    try:
        # Step 1: Extract OSM features from the biosample
        features = extract_osm_features(biosample)
        
        # Log feature information
        logger.info(f"Extracted {len(features)} features from biosample {biosample_id}")
        for f in features:
            logger.info(f"  Biosample {biosample_id}: Feature {f.feature_id}: {f.feature_type}, distance={f.distance_from_center}m")
        
        if not features:
            enriched['envo_mapping_debug']['status'] = 'No OSM features found'
            return enriched
            
        # Limit to max_features if needed
        if max_features and len(features) > max_features:
            features = features[:max_features]
        
        # Step 2: Extract asserted environment terms for context
        env_terms = extract_biosample_env_terms(biosample)
        
        # Step 3: Process each feature to map it to an EnvO term
        mappings = []
        
        for feature in features:
            # Update the processing status
            enriched['envo_mapping_debug']['status'] = f'Processing feature {feature.feature_id}'
            
            # Map feature to EnvO term
            mapping = await agent.map_feature_to_envo(
                feature, 
                biosample_id=biosample_id,
                biosample_coords=(lat, lon),
                biosample_env_terms=env_terms
            )
            
            if mapping and mapping.confidence >= CONFIDENCE_THRESHOLD:
                mappings.append(mapping)
                
                # Add to the mappings dictionary indexed by feature ID
                enriched['envo_mappings'][feature.feature_id] = mapping.model_dump()
                
                # Add to the appropriate field-specific mapping list if the field is specified
                if mapping.nmdc_field and mapping.nmdc_field in enriched['envo_mappings_by_field']:
                    enriched['envo_mappings_by_field'][mapping.nmdc_field].append(mapping.model_dump())
        
        # Step 4: Update statistics
        enriched['envo_mapping_stats']['total_features_processed'] = len(features)
        enriched['envo_mapping_stats']['features_with_mappings'] = len(mappings)
        
        # Calculate mapping coverage (percentage of features that were mapped)
        if features:
            enriched['envo_mapping_stats']['mapping_coverage'] = len(mappings) / len(features)
        
        # Step 5: Check if each field has at least one mapping
        for field in ['env_broad_scale', 'env_local_scale', 'env_medium']:
            enriched['envo_mapping_stats']['field_coverage'][field] = len(enriched['envo_mappings_by_field'][field]) > 0
        
        # Step 6: Check agreement with asserted terms
        for field, term in env_terms.items():
            if field in enriched['envo_mappings_by_field'] and term.get('id'):
                # Check if any of our mappings match the asserted term
                field_mappings = enriched['envo_mappings_by_field'][field]
                for mapping in field_mappings:
                    if mapping['envo_id'] == term['id']:
                        enriched['envo_mapping_stats']['agreement_with_asserted'][field] = True
                        break
        
        # Step 7: Rank mappings by confidence
        for field in ['env_broad_scale', 'env_local_scale', 'env_medium']:
            enriched['envo_mappings_by_field'][field].sort(
                key=lambda x: (x.get('nmdc_field_confidence', 0) * x.get('confidence', 0)), 
                reverse=True
            )
        
        # Step 8: Add feature aggregation inferences
        # This analyzes feature density to make broader environmental inferences
        # For example, if there are many trees, we can infer it's a forest
        try:
            # Get all features (not just the ones we processed for EnvO mapping)
            all_features = extract_osm_features(biosample, include_distant=True)
            
            if all_features:
                aggregations = analyze_feature_aggregations(all_features)
                
                if aggregations:
                    logger.info(f"Found {len(aggregations)} feature aggregation inferences")
                    
                    # Add to enriched biosample
                    for aggregation in aggregations:
                        enriched['feature_aggregations'].append(aggregation.dict())
                        
                        # Also add to the appropriate field
                        if aggregation.suggested_nmdc_field in enriched['envo_mappings_by_field']:
                            # Create a mapping entry
                            aggregation_mapping = {
                                'envo_id': aggregation.envo_id,
                                'envo_label': aggregation.name,
                                'confidence': aggregation.confidence,
                                'reasoning': aggregation.reasoning,
                                'feature_id': f"aggregation-{aggregation.feature_type}",
                                'feature_type': f"aggregation:{aggregation.feature_type}",
                                'distance': 0.0,  # Aggregation doesn't have a single distance
                                'nmdc_field': aggregation.suggested_nmdc_field,
                                'nmdc_field_confidence': 0.9,  # High confidence in the field assignment
                                'is_aggregation': True,
                                'feature_count': aggregation.feature_count
                            }
                            
                            enriched['envo_mappings_by_field'][aggregation.suggested_nmdc_field].append(aggregation_mapping)
                    
                    # Update stats
                    enriched['envo_mapping_stats']['aggregation_inferences'] = len(aggregations)
                    
                    # Set field coverage for any fields that got aggregation mappings
                    for field in ['env_broad_scale', 'env_local_scale', 'env_medium']:
                        if any(a.get('is_aggregation', False) for a in enriched['envo_mappings_by_field'][field]):
                            enriched['envo_mapping_stats']['field_coverage'][field] = True
        except Exception as e:
            logger.error(f"Error processing feature aggregations: {e}")
        
        # Final status update
        enriched['envo_mapping_debug']['status'] = 'Successfully processed'
        
    except Exception as e:
        logger.error(f"Error processing biosample: {e}")
        enriched['envo_mapping_debug']['status'] = f'Error: {str(e)}'
        enriched['envo_mapping_debug']['error'] = str(e)
    
    return enriched

@click.command(context_settings=dict(ignore_unknown_options=True))
@click.option('--input', '-i', 'input_path', type=click.Path(exists=True), required=True,
              help='Input JSON file containing NMDC biosamples with OSM features')
@click.option('--output', '-o', 'output_path', type=click.Path(), required=True,
              help='Output path for enriched biosamples JSON with EnvO mappings')
@click.option('--max-samples', type=int, default=None,
              help='Maximum number of samples to process (default: all)')
@click.option('--max-features', type=int, default=20,
              help='Maximum number of features to process per biosample (default: 20)')
@click.option('--confidence', type=float, default=0.7,
              help='Confidence threshold for accepting EnvO mappings (default: 0.7)')
@click.option('--biosample-index', type=int, default=0,
              help='Index of the specific biosample to process (default: 0, use -1 to process all or max-samples)')
@click.option('--debug', is_flag=True, default=False,
              help='Enable debug logging')
def main_cli(input_path: str, output_path: str, max_samples: int,
          max_features: int, confidence: float, biosample_index: int, debug: bool):
    """Command-line entry point that runs the async main function."""
    import asyncio
    # Set debug logging if requested
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
        
    asyncio.run(main(input_path, output_path, max_samples, max_features, confidence, biosample_index))

async def main(input_path: str, output_path: str, max_samples: int, 
               max_features: int, confidence: float, biosample_index: int = 0):
    """
    Process NMDC biosamples with OSM features to add EnvO mappings.
    Uses PydanticAI agent with OAK integration to map OSM features to
    standardized EnvO terms.
    """
    global CONFIDENCE_THRESHOLD
    CONFIDENCE_THRESHOLD = confidence
    
    # Load input data
    logger.info(f"Loading biosamples from {input_path}")
    with open(input_path) as f:
        data = json.load(f)
    
    if isinstance(data, dict) and 'biosamples' in data:
        biosamples = data['biosamples']
    else:
        biosamples = data
    
    logger.info(f"Found {len(biosamples)} biosamples with OSM features")
    
    # Handle biosample selection
    if biosample_index >= 0 and biosample_index < len(biosamples):
        # If a specific index is requested, just process that biosample
        logger.info(f"Selecting biosample at index {biosample_index}: {biosamples[biosample_index].get('id', 'unknown')}")
        biosamples = [biosamples[biosample_index]]
    elif biosample_index >= len(biosamples):
        # Index out of range
        logger.warning(f"Biosample index {biosample_index} is out of range. Using first biosample.")
        biosamples = [biosamples[0]]
    elif biosample_index < 0:
        # Negative index means we should use max_samples if specified
        if max_samples and max_samples < len(biosamples):
            logger.info(f"Randomly selecting {max_samples} biosamples out of {len(biosamples)} total")
            biosamples = random.sample(biosamples, max_samples)
        else:
            logger.info(f"Processing all {len(biosamples)} biosamples")
    # This is the default case with biosample_index=0
    elif max_samples and max_samples < len(biosamples) and biosample_index == 0:
        logger.info(f"Randomly selecting {max_samples} biosamples out of {len(biosamples)} total")
        biosamples = random.sample(biosamples, max_samples)
    
    # Initialize agent
    agent = EnvoNormalizerAgent()
    
    # Process each biosample
    logger.info(f"Processing {len(biosamples)} biosamples")
    enriched_samples = []
    
    for biosample in tqdm(biosamples):
        enriched = await process_biosample(agent, biosample, max_features=max_features)
        enriched_samples.append(enriched)
    
    # Save results
    output_data = {
        'biosamples': enriched_samples,
        'metadata': {
            'total_input_samples': len(biosamples),
            'processed_samples': len(enriched_samples),
            'confidence_threshold': CONFIDENCE_THRESHOLD,
            'max_features_per_sample': max_features
        }
    }
    
    logger.info(f"Writing results to {output_path}")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)

if __name__ == "__main__":
    main_cli()