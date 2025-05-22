#!/usr/bin/env python3
"""
Script to create and maintain a consolidated test cases file from individual test samples.
This allows adding new test cases over time to build a comprehensive test suite.
"""

import json
import os
import argparse
import glob
from datetime import datetime
from typing import Dict, List, Any

def calculate_agreement_score(biosample: Dict[str, Any]) -> float:
    """
    Calculate an agreement score between asserted and inferred EnvO terms.
    
    A higher score indicates better agreement between what was asserted in the 
    biosample metadata and what was inferred from OSM features.
    
    Returns:
        float: Score between 0.0 (no agreement) and 1.0 (perfect agreement)
    """
    # Get the agreement status for each field
    stats = biosample.get("envo_mapping_stats", {})
    agreement = stats.get("agreement_with_asserted", {})
    
    # Check if there's any agreement information
    if not agreement:
        return 0.0
    
    # Count how many fields have agreement
    agreed_fields = sum(1 for field, has_agreement in agreement.items() if has_agreement)
    total_fields = len(agreement)
    
    # Calculate basic agreement score
    if total_fields == 0:
        return 0.0
    
    agreement_score = agreed_fields / total_fields
    
    # Factor in field coverage and mapping coverage for a more nuanced score
    field_coverage = stats.get("field_coverage", {})
    fields_with_coverage = sum(1 for field, has_coverage in field_coverage.items() if has_coverage)
    coverage_factor = fields_with_coverage / total_fields if total_fields > 0 else 0
    
    mapping_coverage = stats.get("mapping_coverage", 0.0)
    
    # Final score is a weighted combination of agreement and coverage
    final_score = (0.7 * agreement_score) + (0.15 * coverage_factor) + (0.15 * mapping_coverage)
    
    return min(final_score, 1.0)  # Cap at 1.0

def process_test_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single test case and extract relevant data"""
    try:
        with open(case["input_file"], "r") as f:
            data = json.load(f)
            # Find the biosample
            for biosample in data.get("biosamples", []):
                if biosample.get("id") == case["biosample_id"]:
                    # Extract mappings and metrics
                    case["envo_mappings"] = biosample.get("envo_mappings", {})
                    case["stats"] = biosample.get("envo_mapping_stats", {})
                    
                    # Calculate agreement score
                    case["agreement_score"] = calculate_agreement_score(biosample)
                    
                    # Extract OSM features overview
                    if "osm_features" in biosample:
                        case["osm_features_summary"] = {
                            "total_features": biosample["osm_features"].get("metadata", {}).get("total_features", 0),
                            "feature_types": biosample["osm_features"].get("metadata", {}).get("feature_type_counts", {})
                        }
                    
                    # Extract asserted environment terms for reference
                    asserted_terms = {}
                    for field in ["env_broad_scale", "env_local_scale", "env_medium"]:
                        if field in biosample:
                            term_data = biosample[field]
                            if isinstance(term_data, dict) and "term" in term_data:
                                term = term_data["term"]
                                asserted_terms[field] = {
                                    "id": term.get("id", ""),
                                    "name": term.get("name", "")
                                }
                    
                    if asserted_terms:
                        case["asserted_terms"] = asserted_terms
                    
                    break
            
            # Delete the input file field to clean up output
            if "input_file" in case:
                del case["input_file"]
        
    except Exception as e:
        print(f"Error processing {case.get('name', 'unknown')}: {e}")
        case["error"] = str(e)
    
    return case

def discover_test_files(pattern: str = "local/nmdc-envo-normalized-*.json") -> List[str]:
    """Discover test files matching a pattern"""
    return glob.glob(pattern)

def create_test_case_from_file(file_path: str) -> Dict[str, Any]:
    """Create a test case entry from a normalized file"""
    # Extract sample number or identifier from filename
    file_name = os.path.basename(file_path)
    if "sample" in file_name:
        sample_id = file_name.split("sample")[1].split(".")[0]
        source = f"Sample {sample_id}"
    else:
        sample_id = "1"
        source = "Sample 1"
    
    # Load the file to get biosample ID and feature types
    try:
        with open(file_path, "r") as f:
            data = json.load(f)
            if "biosamples" in data and len(data["biosamples"]) > 0:
                biosample = data["biosamples"][0]
                biosample_id = biosample.get("id", "unknown")
                
                # Determine feature types
                feature_types = []
                if "osm_features" in biosample and "features" in biosample["osm_features"]:
                    for category, features in biosample["osm_features"]["features"].items():
                        if features and len(features) > 0:
                            # Get types from the first few features
                            for feature in features[:3]:
                                if "type" in feature and feature["type"] not in feature_types:
                                    feature_types.append(feature["type"])
                
                # Create a name based on feature types
                if feature_types:
                    name = f"{feature_types[0].split(':')[1].capitalize()} Sample"
                    description = f"Biosample with {', '.join(ft.split(':')[1] for ft in feature_types)} features"
                else:
                    name = f"Sample {sample_id}"
                    description = "Biosample with unknown features"
                
                return {
                    "name": name,
                    "source": source,
                    "description": description,
                    "feature_types": feature_types,
                    "biosample_id": biosample_id,
                    "input_file": file_path
                }
    except Exception as e:
        print(f"Error creating test case from {file_path}: {e}")
    
    # Return a minimal entry if we couldn't extract details
    return {
        "name": f"Sample from {file_name}",
        "source": source,
        "description": "Failed to extract details",
        "feature_types": [],
        "biosample_id": "unknown",
        "input_file": file_path,
        "error": "Failed to extract details"
    }

def select_best_and_worst_samples(data_file: str, num_samples: int = 5) -> List[Dict[str, Any]]:
    """
    Select the best and worst performing samples from a dataset based on agreement scores.
    
    Args:
        data_file: Path to the normalized data file
        num_samples: Number of samples to select from each end (best and worst)
        
    Returns:
        List of test case dictionaries for the selected samples
    """
    try:
        with open(data_file, "r") as f:
            data = json.load(f)
            
        biosamples = data.get("biosamples", [])
        if not biosamples:
            print(f"No biosamples found in {data_file}")
            return []
        
        # Calculate agreement scores for each biosample
        scored_samples = []
        for biosample in biosamples:
            score = calculate_agreement_score(biosample)
            scored_samples.append((biosample, score))
        
        # Sort by score
        scored_samples.sort(key=lambda x: x[1])
        
        # Get worst and best samples
        worst_samples = scored_samples[:num_samples]
        best_samples = scored_samples[-num_samples:]
        
        # Create test cases
        test_cases = []
        
        # Process worst samples
        for i, (biosample, score) in enumerate(worst_samples):
            # Create a descriptive name based on feature types
            feature_types = []
            if "osm_features" in biosample and "features" in biosample["osm_features"]:
                for category, features in biosample["osm_features"]["features"].items():
                    if features and len(features) > 0:
                        for feature in features[:3]:
                            if "type" in feature and feature["type"] not in feature_types:
                                feature_types.append(feature["type"])
            
            if feature_types:
                feature_desc = ", ".join(ft.split(':')[1] for ft in feature_types[:3])
                name = f"Low Agreement - {feature_desc}"
                description = f"Biosample with low agreement score ({score:.2f}) featuring {feature_desc}"
            else:
                name = f"Low Agreement Sample {i+1}"
                description = f"Biosample with low agreement score ({score:.2f})"
            
            test_case = {
                "name": name,
                "source": "Auto-selected low agreement sample",
                "description": description,
                "feature_types": feature_types,
                "biosample_id": biosample.get("id", f"unknown-{i}"),
                "input_file": data_file,
                "agreement_category": "low",
                "agreement_score": score
            }
            
            test_cases.append(test_case)
        
        # Process best samples
        for i, (biosample, score) in enumerate(best_samples):
            # Create a descriptive name based on feature types
            feature_types = []
            if "osm_features" in biosample and "features" in biosample["osm_features"]:
                for category, features in biosample["osm_features"]["features"].items():
                    if features and len(features) > 0:
                        for feature in features[:3]:
                            if "type" in feature and feature["type"] not in feature_types:
                                feature_types.append(feature["type"])
            
            if feature_types:
                feature_desc = ", ".join(ft.split(':')[1] for ft in feature_types[:3])
                name = f"High Agreement - {feature_desc}"
                description = f"Biosample with high agreement score ({score:.2f}) featuring {feature_desc}"
            else:
                name = f"High Agreement Sample {i+1}"
                description = f"Biosample with high agreement score ({score:.2f})"
            
            test_case = {
                "name": name,
                "source": "Auto-selected high agreement sample",
                "description": description,
                "feature_types": feature_types,
                "biosample_id": biosample.get("id", f"unknown-{i}"),
                "input_file": data_file,
                "agreement_category": "high",
                "agreement_score": score
            }
            
            test_cases.append(test_case)
        
        return test_cases
        
    except Exception as e:
        print(f"Error selecting samples from {data_file}: {e}")
        return []

def main():
    parser = argparse.ArgumentParser(description="Create and maintain test cases file")
    parser.add_argument("--output", default="nmdc-osm-envo-test-cases.json", help="Output file path")
    parser.add_argument("--add-files", nargs="+", help="Additional test files to add")
    parser.add_argument("--discover", action="store_true", help="Discover new test files")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild the entire test cases file")
    parser.add_argument("--select-best-worst", type=str, help="Select best and worst performing samples from a file")
    parser.add_argument("--num-samples", type=int, default=5, help="Number of samples to select from each category (best/worst)")
    args = parser.parse_args()
    
    output_file = args.output
    
    # Start with existing test cases or create new
    if os.path.exists(output_file) and not args.rebuild:
        print(f"Loading existing test cases from {output_file}")
        with open(output_file, "r") as f:
            output = json.load(f)
            test_cases = output.get("test_cases", [])
            
            # Create a set of existing biosample IDs for deduplication
            existing_ids = {case.get("biosample_id") for case in test_cases if "biosample_id" in case}
    else:
        print("Creating new test cases file")
        test_cases = []
        existing_ids = set()
        
        # Define initial test cases if rebuilding
        if args.rebuild:
            base_cases = [
                {
                    "name": "Trees Sample",
                    "source": "Sample 1",
                    "description": "Biosample with tree features (natural:tree) - evaluates how the system maps trees to EnvO terms",
                    "feature_types": ["natural:tree"],
                    "biosample_id": "nmdc:bsm-11-5jd2b969",
                    "input_file": "local/nmdc-envo-normalized-test.json"
                },
                {
                    "name": "Streams Sample",
                    "source": "Sample 2",
                    "description": "Biosample with stream features (waterway:stream) - evaluates how the system handles water features",
                    "feature_types": ["waterway:stream"],
                    "biosample_id": "nmdc:bsm-11-rp3gs545",
                    "input_file": "local/nmdc-envo-normalized-test-sample2.json"
                },
                {
                    "name": "Water Bodies Sample",
                    "source": "Sample 3",
                    "description": "Biosample with water features (natural:water with pond and lake tags) - evaluates handling of distant features",
                    "feature_types": ["natural:water"],
                    "biosample_id": "nmdc:bsm-11-dc12zg61",
                    "input_file": "local/nmdc-envo-normalized-test-sample3.json"
                }
            ]
            
            for case in base_cases:
                processed_case = process_test_case(case)
                test_cases.append(processed_case)
                existing_ids.add(processed_case.get("biosample_id"))
    
    # Add best and worst performing samples if requested
    if args.select_best_worst:
        if os.path.exists(args.select_best_worst):
            print(f"Selecting best and worst samples from {args.select_best_worst}")
            selected_cases = select_best_and_worst_samples(args.select_best_worst, args.num_samples)
            
            for case in selected_cases:
                biosample_id = case.get("biosample_id")
                if biosample_id and biosample_id not in existing_ids:
                    print(f"Adding {'high' if case.get('agreement_category') == 'high' else 'low'} agreement sample: {case['name']} ({biosample_id})")
                    processed_case = process_test_case(case)
                    test_cases.append(processed_case)
                    existing_ids.add(biosample_id)
        else:
            print(f"Warning: File not found - {args.select_best_worst}")
    
    # Discover new test files if requested
    if args.discover:
        print("Discovering new test files")
        discovered_files = discover_test_files()
        for file_path in discovered_files:
            test_case = create_test_case_from_file(file_path)
            biosample_id = test_case.get("biosample_id")
            
            # Only add if not already in the list
            if biosample_id and biosample_id not in existing_ids:
                print(f"Adding discovered test case: {test_case['name']} ({biosample_id})")
                processed_case = process_test_case(test_case)
                test_cases.append(processed_case)
                existing_ids.add(biosample_id)
    
    # Add specific files if provided
    if args.add_files:
        print(f"Adding {len(args.add_files)} specified test files")
        for file_path in args.add_files:
            if os.path.exists(file_path):
                test_case = create_test_case_from_file(file_path)
                biosample_id = test_case.get("biosample_id")
                
                # Only add if not already in the list
                if biosample_id and biosample_id not in existing_ids:
                    print(f"Adding specified test case: {test_case['name']} ({biosample_id})")
                    processed_case = process_test_case(test_case)
                    test_cases.append(processed_case)
                    existing_ids.add(biosample_id)
            else:
                print(f"Warning: File not found - {file_path}")
    
    # Update metadata
    output = {
        "test_cases": test_cases,
        "metadata": {
            "description": "Test cases for EnvO normalization of OSM features",
            "version": "1.1.0",
            "created": "2025-05-22",
            "updated": datetime.now().strftime("%Y-%m-%d"),
            "count": len(test_cases)
        }
    }
    
    # Save the consolidated test cases
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"Created/updated consolidated test cases file: {output_file}")
    print(f"Total test cases: {len(test_cases)}")

if __name__ == "__main__":
    main()