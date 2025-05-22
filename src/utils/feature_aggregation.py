#!/usr/bin/env python3
"""
Script for making higher-level inferences from OSM feature aggregations.
This allows determining broader environmental contexts like "forest" from multiple tree features.
"""

import json
from typing import Dict, List, Any, Optional, Tuple
from pydantic import BaseModel
from dataclasses import dataclass
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Feature type to environmental context mappings
FEATURE_AGGREGATIONS = {
    "natural:tree": {
        "threshold": 20,  # Number of features needed to trigger
        "radius": 200,    # Within this radius (meters)
        "inferences": [
            {
                "name": "forest",
                "envo_id": "ENVO:01001243",
                "description": "Area with high density of trees",
                "confidence_function": lambda count, radius: min(0.5 + (count / 100) * 0.5, 0.95)  # More trees = higher confidence
            }
        ]
    },
    "natural:water": {
        "threshold": 3,
        "radius": 1000,
        "inferences": [
            {
                "name": "lake district",
                "envo_id": "ENVO:00000485",  # Fictional ID for demonstration
                "description": "Region with multiple lakes or ponds",
                "confidence_function": lambda count, radius: min(0.6 + (count / 10) * 0.3, 0.9)
            }
        ]
    },
    "waterway:stream": {
        "threshold": 2,
        "radius": 500,
        "inferences": [
            {
                "name": "stream network",
                "envo_id": "ENVO:00000558",  # Fictional ID for demonstration
                "description": "Network of interconnected streams",
                "confidence_function": lambda count, radius: min(0.7 + (count / 5) * 0.2, 0.9)
            }
        ]
    }
}

class FeatureAggregation(BaseModel):
    """Environmental inference made from aggregating multiple OSM features"""
    name: str
    envo_id: str
    description: str
    confidence: float
    feature_count: int
    feature_type: str
    radius: int
    reasoning: str
    suggested_nmdc_field: str = "env_broad_scale"  # Aggregations are typically broad-scale

def analyze_feature_density(features: List[Dict[str, Any]]) -> List[FeatureAggregation]:
    """
    Analyze feature density to make higher-level environmental inferences.
    
    Args:
        features: List of OSM features
        
    Returns:
        List of environmental inferences based on feature aggregations
    """
    # Count features by type
    feature_counts = {}
    for feature in features:
        feature_type = feature.get("feature_type")
        if feature_type not in feature_counts:
            feature_counts[feature_type] = []
        feature_counts[feature_type].append(feature)
    
    # Make inferences based on density
    inferences = []
    
    for feature_type, features_of_type in feature_counts.items():
        if feature_type in FEATURE_AGGREGATIONS:
            config = FEATURE_AGGREGATIONS[feature_type]
            count = len(features_of_type)
            
            # Check if we meet the threshold for this type
            if count >= config["threshold"]:
                radius = config["radius"]
                
                # Create inferences
                for inference in config["inferences"]:
                    # Calculate confidence
                    confidence = inference["confidence_function"](count, radius)
                    
                    # Create reasoning text
                    reasoning = (
                        f"Based on the presence of {count} {feature_type} features within a {radius}m radius. "
                        f"This density of features strongly suggests a {inference['name']} environment. "
                        f"The confidence is {confidence:.2f}, calculated based on the number of features detected."
                    )
                    
                    # Create the aggregation
                    aggregation = FeatureAggregation(
                        name=inference["name"],
                        envo_id=inference["envo_id"],
                        description=inference["description"],
                        confidence=confidence,
                        feature_count=count,
                        feature_type=feature_type,
                        radius=radius,
                        reasoning=reasoning
                    )
                    
                    inferences.append(aggregation)
    
    return inferences

def main():
    """Main function to demonstrate feature aggregation"""
    # Load a sample file
    with open("local/nmdc-osm-enriched-test.json", "r") as f:
        data = json.load(f)
    
    # Process the first biosample
    if "biosamples" in data and len(data["biosamples"]) > 0:
        biosample = data["biosamples"][0]
        
        # Extract OSM features
        features = []
        if "osm_features" in biosample and "features" in biosample["osm_features"]:
            for category, category_features in biosample["osm_features"]["features"].items():
                for feature_data in category_features:
                    # Simplify for demo purposes
                    features.append({
                        "feature_id": feature_data.get("id", "unknown"),
                        "feature_type": feature_data.get("type", f"{category}:unknown"),
                        "distance_from_center": feature_data.get("distance_from_center", 0.0)
                    })
        
        # Analyze feature density
        inferences = analyze_feature_density(features)
        
        # Print results
        print(f"Biosample ID: {biosample.get('id')}")
        print(f"Total features: {len(features)}")
        print("\nInferences from feature density:")
        
        if inferences:
            for inference in inferences:
                print(f"- {inference.name} ({inference.envo_id})")
                print(f"  Description: {inference.description}")
                print(f"  Confidence: {inference.confidence:.2f}")
                print(f"  Reasoning: {inference.reasoning}")
                print()
        else:
            print("No inferences could be made from feature density.")
    
if __name__ == "__main__":
    main()