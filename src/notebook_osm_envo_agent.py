"""
Notebook-friendly PydanticAI OSM to EnvO interpretation agent.

This module provides a PydanticAI agent that can interpret OSM features 
as EnvO classes within Jupyter notebooks using nest_asyncio to handle
event loop conflicts.
"""

import os
import asyncio
import logging
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from dotenv import load_dotenv

try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    print("nest_asyncio not available. Install with: pip install nest-asyncio")

# Load environment variables
load_dotenv(verbose=True)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OSMFeatureInput(BaseModel):
    """Input model for OSM feature to be interpreted"""
    feature_type: str = Field(..., description="OSM feature type (e.g., 'natural:water')")
    tags: Dict[str, str] = Field(..., description="OSM tags dictionary")
    distance_from_center: Optional[float] = Field(None, description="Distance from query center in meters")

class EnvOMapping(BaseModel):
    """EnvO mapping result with validation"""
    envo_id: str = Field(..., pattern=r"^ENVO:\d{8}$", description="EnvO identifier")
    envo_label: str = Field(..., min_length=1, description="EnvO term label")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0.0-1.0")
    reasoning: str = Field(..., min_length=10, description="Explanation for mapping")

class OSMEnvOAgent:
    """PydanticAI agent for OSM to EnvO interpretation"""
    
    def __init__(self):
        """Initialize the agent with CBORG API configuration"""
        api_key = os.getenv("CBORG_API_KEY")
        if not api_key:
            raise ValueError("CBORG_API_KEY environment variable not set")
            
        self.agent = Agent(
            OpenAIModel(
                "anthropic/claude-sonnet",
                provider=OpenAIProvider(
                    base_url="https://api.cborg.lbl.gov",
                    api_key=api_key,
                )
            ),
            result_type=EnvOMapping,
            system_prompt="""You are an expert in environmental ontology helping to map OpenStreetMap features 
            to standardized Environment Ontology (EnvO) terms.
            
            Common EnvO terms to consider:
            - ENVO:00000020 (lake)
            - ENVO:00000025 (river)
            - ENVO:00000087 (forest)
            - ENVO:00000174 (grassland)
            - ENVO:00000134 (agricultural land)
            - ENVO:00002030 (aquatic environment)
            - ENVO:00000077 (wetland)
            - ENVO:00000446 (terrestrial environment)
            - ENVO:00000562 (park)
            - ENVO:00000856 (building)
            - ENVO:00000078 (urban area)
            - ENVO:00000295 (residential area)
            
            For each OSM feature, determine the most appropriate EnvO term considering:
            1. The primary feature type and OSM tags
            2. Spatial context and distance from point of interest
            3. Environmental relevance and biological significance
            
            Provide high confidence (>0.8) only for clear, unambiguous mappings.
            Use moderate confidence (0.5-0.8) for reasonable but not perfect matches.
            Use low confidence (<0.5) for uncertain or generic mappings.
            
            Always use valid EnvO IDs in the format ENVO:########."""
        )
    
    async def interpret_feature(self, osm_feature: Any) -> Optional[EnvOMapping]:
        """
        Interpret a single OSM feature as an EnvO term.
        
        Args:
            osm_feature: OSMFeature object from query_osm_features()
            
        Returns:
            EnvOMapping or None if interpretation fails
        """
        try:
            # Convert OSMFeature to input model
            feature_input = OSMFeatureInput(
                feature_type=osm_feature.feature_type,
                tags=osm_feature.tags,
                distance_from_center=getattr(osm_feature, 'distance_from_center', None)
            )
            
            # Create interpretation prompt
            prompt = f"""Analyze this OpenStreetMap feature and map it to the most appropriate EnvO term:

Feature Type: {feature_input.feature_type}
OSM Tags: {feature_input.tags}
Distance from center: {feature_input.distance_from_center} meters

Consider the environmental and biological significance of this feature.
Map it to the most appropriate EnvO term."""
            
            # Run the agent
            result = await self.agent.run(prompt)
            return result.data
            
        except Exception as e:
            logger.error(f"Error interpreting feature {osm_feature.feature_type}: {e}")
            return None
    
    def interpret_feature_sync(self, osm_feature: Any) -> Optional[EnvOMapping]:
        """
        Synchronous wrapper for interpret_feature (notebook-friendly).
        
        Args:
            osm_feature: OSMFeature object
            
        Returns:
            EnvOMapping or None
        """
        try:
            # Get or create event loop
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Run the async function
            return loop.run_until_complete(self.interpret_feature(osm_feature))
            
        except Exception as e:
            logger.error(f"Error in sync interpretation: {e}")
            return None

class OSMEnvOInterpreter:
    """High-level interface for OSM to EnvO interpretation"""
    
    def __init__(self):
        """Initialize the interpreter with agent"""
        self.agent = OSMEnvOAgent()
    
    def interpret_osm_features(self, osm_features: List[Any], 
                             max_features: int = 10) -> List[EnvOMapping]:
        """
        Interpret multiple OSM features as EnvO terms.
        
        Args:
            osm_features: List of OSMFeature objects
            max_features: Maximum number of features to process
            
        Returns:
            List of successful EnvOMapping objects
        """
        mappings = []
        features_to_process = osm_features[:max_features]
        
        logger.info(f"Processing {len(features_to_process)} OSM features")
        
        for i, feature in enumerate(features_to_process):
            try:
                mapping = self.agent.interpret_feature_sync(feature)
                if mapping:
                    mappings.append(mapping)
                    logger.info(f"✓ Mapped {feature.feature_type} to {mapping.envo_id}")
                else:
                    logger.warning(f"✗ Failed to map {feature.feature_type}")
                    
            except Exception as e:
                logger.error(f"Error processing {feature.feature_type}: {e}")
                continue
            
            # Progress indicator
            if (i + 1) % 5 == 0 or i == len(features_to_process) - 1:
                logger.info(f"Progress: {i + 1}/{len(features_to_process)} features")
        
        logger.info(f"Successfully mapped {len(mappings)}/{len(features_to_process)} features")
        return mappings
    
    def interpret_location(self, lat: float, lon: float, 
                          radius: int = 1000, max_features: int = 10) -> List[EnvOMapping]:
        """
        Complete workflow: query OSM features and interpret as EnvO terms.
        
        Args:
            lat: Latitude
            lon: Longitude
            radius: Search radius in meters
            max_features: Maximum features to process
            
        Returns:
            List of EnvOMapping objects
        """
        try:
            # Import OSM query function
            from src.agent_test.osm_features import query_osm_features
            
            # Query OSM features
            logger.info(f"Querying OSM features at ({lat}, {lon}) within {radius}m")
            osm_features = query_osm_features(lat, lon, radius)
            
            if not osm_features:
                logger.warning("No OSM features found")
                return []
            
            # Interpret features
            return self.interpret_osm_features(osm_features, max_features)
            
        except Exception as e:
            logger.error(f"Error in location interpretation: {e}")
            return []

def display_envo_mappings(mappings: List[EnvOMapping]) -> None:
    """Display EnvO mappings in notebook-friendly format"""
    if not mappings:
        print("No EnvO mappings found.")
        return
    
    print(f"🌍 Found {len(mappings)} EnvO mappings:\n")
    
    for i, mapping in enumerate(mappings, 1):
        confidence_emoji = "🟢" if mapping.confidence >= 0.8 else "🟡" if mapping.confidence >= 0.5 else "🔴"
        
        print(f"{i}. {confidence_emoji} {mapping.envo_label} ({mapping.envo_id})")
        print(f"   Confidence: {mapping.confidence:.2f}")
        print(f"   Reasoning: {mapping.reasoning}")
        print("-" * 60)

def summarize_envo_mappings(mappings: List[EnvOMapping]) -> Dict[str, Any]:
    """Create summary statistics for EnvO mappings"""
    if not mappings:
        return {"total": 0}
    
    # Group by EnvO class
    envo_counts = {}
    confidences = [m.confidence for m in mappings]
    
    for mapping in mappings:
        key = f"{mapping.envo_label} ({mapping.envo_id})"
        envo_counts[key] = envo_counts.get(key, 0) + 1
    
    return {
        "total_mappings": len(mappings),
        "unique_envo_classes": len(envo_counts),
        "envo_class_counts": envo_counts,
        "confidence_stats": {
            "mean": sum(confidences) / len(confidences),
            "min": min(confidences),
            "max": max(confidences),
            "high_confidence": len([c for c in confidences if c >= 0.8]),
            "medium_confidence": len([c for c in confidences if 0.5 <= c < 0.8]),
            "low_confidence": len([c for c in confidences if c < 0.5])
        }
    }

# Convenience functions for notebook use
def interpret_osm_to_envo(osm_features: List[Any], max_features: int = 10) -> List[EnvOMapping]:
    """Simple function to interpret OSM features as EnvO terms"""
    interpreter = OSMEnvOInterpreter()
    return interpreter.interpret_osm_features(osm_features, max_features)

def interpret_location_to_envo(lat: float, lon: float, 
                              radius: int = 1000, max_features: int = 10) -> List[EnvOMapping]:
    """Simple function to get location EnvO interpretation"""
    interpreter = OSMEnvOInterpreter()
    return interpreter.interpret_location(lat, lon, radius, max_features)

if __name__ == "__main__":
    # Test example
    test_lat, test_lon = 35.97583846, -84.2743123
    
    print(f"Testing PydanticAI OSM to EnvO interpretation at {test_lat}, {test_lon}")
    
    try:
        mappings = interpret_location_to_envo(test_lat, test_lon, radius=500, max_features=5)
        display_envo_mappings(mappings)
        
        summary = summarize_envo_mappings(mappings)
        print(f"\n📊 Summary:")
        print(f"Total mappings: {summary.get('total_mappings', 0)}")
        print(f"Unique EnvO classes: {summary.get('unique_envo_classes', 0)}")
        
    except Exception as e:
        logger.error(f"Test failed: {e}")